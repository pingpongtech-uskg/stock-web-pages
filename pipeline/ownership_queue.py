"""Durable, fair queue for bounded public ownership acquisition batches."""
from __future__ import annotations

import copy
import csv
import io
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from pipeline.ownership_inputs import merge_ownership_rows
from pipeline.source_receipts import safe_directory, _write
from scripts.fetch_ownership import OwnershipBudget, OwnershipLimit, completed_months, shift_month

QUEUE_VERSION = 'ownership-queue-v1'


def new_state(roster: list[str], priority: list[str], verified_market_date: str) -> dict:
    if (not roster or len(roster)>100 or len(set(roster))!=len(roster)
            or any(not isinstance(code,str) or not re.fullmatch(r'\d{4,6}[A-Z]?',code) for code in roster)
            or any(code not in roster for code in priority)):
        raise ValueError('invalid frozen ownership roster')
    months = completed_months(verified_market_date)
    ordered = list(dict.fromkeys([*priority,*roster]))
    def job(source,code='',period=''):
        return {'key':f'{source}:{code}:{period}', 'source':source,'code':code,'period':period,
                'sourceDate':None,'status':'pending','attempts':0,'nextAttemptAt':0}
    jobs = [job('TDCC_DATES'),job('TDCC_LATEST'),job('DIRECTOR_PERIODS')]
    requests = [('TDCC',month) for month in months] + [('MOPS',shift_month(months[-1],-12)),('MOPS',months[-1])]
    # Round-robin companies within each source/period: one failed company cannot
    # consume every future batch while all others wait behind it.
    groups = ([code for code in ordered if code in priority], [code for code in ordered if code not in priority])
    jobs += [job(source,code,period) for group in groups for source,period in requests for code in group]
    return {'schemaVersion':QUEUE_VERSION,'verifiedMarketDate':verified_market_date,
            'roster':ordered,'priorityCodes':list(priority),'targetMonths':months,
            'availableDates':[],'directorPeriods':{},'jobs':jobs,'rows':[],'receipts':[],'cursor':0}


def _job_group(job: dict,priority: set[str]) -> int:
    return 0 if not job['code'] else 1 if job['code'] in priority else 2


def prioritize_state(state: dict) -> dict:
    """Migrate source-major ordering without changing any job or source evidence."""
    priority=set(state['priorityCodes'])
    rank={code:index for index,code in enumerate(state['roster'])}
    global_rank={'TDCC_DATES':0,'TDCC_LATEST':1,'DIRECTOR_PERIODS':2}
    def order(job):
        group=_job_group(job,priority)
        if group==0:
            return (group,global_rank[job['source']],'',0)
        return (group,0 if job['source']=='TDCC' else 1,job['period'],rank[job['code']])
    jobs=sorted(state['jobs'],key=order)
    changed=[job['key'] for job in jobs]!=[job['key'] for job in state['jobs']]
    return {**state,'jobs':jobs,'cursor':0 if changed else state.get('cursor',0)}


def _batch_indices(state: dict) -> list[int]:
    """Priority retries get first opportunity; each group keeps its own rotation."""
    priority=set(state['priorityCodes'])
    cursor=state.get('cursor',0)%len(state['jobs'])
    groups=[[index for index,job in enumerate(state['jobs']) if _job_group(job,priority)==group] for group in range(3)]
    result=[]
    for indices in groups:
        offset=indices.index(cursor) if cursor in indices else 0
        result.extend([*indices[offset:],*indices[:offset]])
    return result


def load_state(path: Path) -> dict | None:
    if path.is_symlink():
        raise ValueError('ownership state must not be a symlink')
    if not path.exists():
        return None
    state = json.loads(path.read_text(encoding='utf-8'))
    if state.get('schemaVersion') != QUEUE_VERSION:
        raise ValueError('invalid ownership queue version')
    # Revalidate frozen identities before trusting resumable state.
    new_state(state['roster'], state['priorityCodes'], state['verifiedMarketDate'])
    if not isinstance(state.get('jobs'),list) or len({job['key'] for job in state['jobs']}) != len(state['jobs']):
        raise ValueError('invalid ownership queue jobs')
    return state


def save_state(directory: Path, state: dict) -> None:
    _write(directory,'queue.json',json.dumps(state,ensure_ascii=False,sort_keys=True,allow_nan=False).encode())


def save_receipt(directory: Path, raw: bytes, *, source: str, url: str, parameters: dict,
                 retrieved_at: str, source_date: str | None, rows: list[dict], selected_codes: list[str] | None=None) -> dict:
    """Content-address exact bytes and public request metadata before use."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'mops.twse.com.tw','www.tdcc.com.tw','opendata.tdcc.com.tw','openapi.twse.com.tw','www.tpex.org.tw'} or parsed.username or parsed.password:
        raise ValueError('invalid official source URL')
    keys = [*parameters,*[key for key,_ in parse_qsl(parsed.query)]]
    if any(re.search('token|secret|password|authorization|credential|apikey',str(key),re.I) for key in keys):
        raise ValueError('private receipt parameter')
    if not isinstance(raw,bytes) or len(raw)>16*1024*1024:
        raise ValueError('invalid receipt bytes')
    if selected_codes is not None and (not 1<=len(selected_codes)<=100 or len(set(selected_codes))!=len(selected_codes)
            or any(not isinstance(code,str) or not re.fullmatch(r'\d{4,6}[A-Z]?',code) for code in selected_codes)):
        raise ValueError('invalid receipt selected roster')
    directory = safe_directory(directory)
    original_digest = hashlib.sha256(raw).hexdigest()
    sanitized = re.sub(rb'<input\b(?=[^>]*(?:SYNCHRONIZER_TOKEN|SYNCHRONIZER_URI|csrf|sessiontoken))[^>]*>', b'', raw, flags=re.I) if source.startswith('TDCC') else raw
    sanitization = 'transient-session-controls-removed' if sanitized != raw else 'none'
    if source=='TDCC_LATEST' and selected_codes is not None:
        source_rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
        if not source_rows or '證券代號' not in source_rows[0]:
            raise ValueError('invalid TDCC CSV header')
        code_index=source_rows[0].index('證券代號')
        output=io.StringIO()
        writer=csv.writer(output,lineterminator='\n')
        writer.writerows([source_rows[0],*[row for row in source_rows[1:] if len(row)>code_index and row[code_index].strip() in selected_codes]])
        sanitized=output.getvalue().encode('utf-8')
        sanitization='roster-filtered-csv-v1'
    raw = sanitized
    digest = hashlib.sha256(raw).hexdigest()
    raw_file = f'{digest}.raw'
    target = directory / raw_file
    if target.is_symlink():
        raise ValueError('receipt file must not be a symlink')
    if target.exists() and target.read_bytes()!=raw:
        raise ValueError('immutable receipt mismatch')
    if not target.exists():
        _write(directory,raw_file,raw)
    receipt = {'source':source,'sourceURL':url,'parameters':parameters,'rawSha256':digest,
               'rawBytes':len(raw),'rawFile':raw_file,'sourceDate':source_date,
               'originalResponseSha256':original_digest,'rawSanitization':sanitization,
               'selectedCodes':selected_codes,
               'publishedAt':None,'retrievedAt':retrieved_at,'availableAt':None,
               'availabilityBasis':'retrieval-only','rows':rows,
               'units':{'largeHolderPct':'percent','shareholderCount':'persons',
                        'directorSupervisorShares':'shares','directorSupervisorPct':'percent'}}
    identity = hashlib.sha256(json.dumps(receipt,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    receipt['receiptFile'] = f'{identity}.json'
    if not (directory / receipt['receiptFile']).exists():
        _write(directory,receipt['receiptFile'],json.dumps(receipt,ensure_ascii=False,sort_keys=True,allow_nan=False).encode())
    return receipt


def run_batch(state: dict, directory: Path, worker, *, max_requests: int=20,
              max_runtime_seconds: int=180, now: float | None=None) -> dict:
    if type(max_requests) is not int or not 1<=max_requests<=20 or not 0<max_runtime_seconds<=180:
        raise ValueError('invalid ownership batch limits')
    budget=OwnershipBudget(max_requests=max_requests,max_history_requests=max_requests,max_runtime_seconds=max_runtime_seconds)
    result=copy.deepcopy(prioritize_state(state))
    wall_now=time.time() if now is None else now
    jobs=result['jobs']
    for index in _batch_indices(result):
        job=jobs[index]
        if job['status']!='pending' or job.get('nextAttemptAt',0)>wall_now:
            continue
        if job['source']=='MOPS' and job['code'] in result.get('directorPeriods',{}):
            reference=result['directorPeriods'][job['code']]
            selected=shift_month(reference,-12) if job.get('comparisonPrevious') or job['period']<result['targetMonths'][0] else reference
            job={**job,'period':selected,'sourceDate':selected,'key':f"MOPS:{job['code']}:{selected}",
                 'comparisonPrevious':selected!=reference}
        if job['source']=='TDCC':
            dates=[value for value in result['availableDates'] if value[:7]==job['period']]
            if not dates:
                continue
            selected=max(dates)
            job={**job,'sourceDate':selected,'key':f"TDCC:{job['code']}:{job['period']}:{selected}"}
        try:
            budget.check()
            output=worker(copy.deepcopy(job),budget)
            status=output.get('outcome','complete')
            if status not in {'complete','pending','unavailable'}:
                raise ValueError('invalid worker outcome')
            if output.get('directorPeriods'):
                result={**result,'directorPeriods':{**result.get('directorPeriods',{}),**output['directorPeriods']}}
            if output.get('availableDates'):
                result={**result,'availableDates':sorted(set(output['availableDates']))}
            result={**result,'rows':merge_ownership_rows(result['rows'],output.get('rows',[])),
                    'receipts':[*result['receipts'],*output.get('receipts',[])]}
            job={**job,'status':status,'attempts':job['attempts']+1,'lastError':None}
        except OwnershipLimit:
            break
        except Exception as exc:
            attempts=job['attempts']+1
            job={**job,'attempts':attempts,'lastError':type(exc).__name__,
                 'nextAttemptAt':wall_now+min(3600,30*2**min(attempts-1,7))}
        jobs=[*jobs[:index],job,*jobs[index+1:]]
        result={**result,'jobs':jobs,'cursor':(index+1)%len(jobs)}
        # Commit progress after every task, including failed HTTP attempts.
        save_state(directory,result)
    jobs=[{**job,'comparisonPrevious':job.get('comparisonPrevious',job['period']<result['targetMonths'][0]),
           'period':shift_month(result['directorPeriods'][job['code']],-12) if job.get('comparisonPrevious',job['period']<result['targetMonths'][0]) else result['directorPeriods'][job['code']],
           'sourceDate':shift_month(result['directorPeriods'][job['code']],-12) if job.get('comparisonPrevious',job['period']<result['targetMonths'][0]) else result['directorPeriods'][job['code']],
           'key':f"MOPS:{job['code']}:"+(shift_month(result['directorPeriods'][job['code']],-12) if job.get('comparisonPrevious',job['period']<result['targetMonths'][0]) else result['directorPeriods'][job['code']])}
          if job['source']=='MOPS' and job['code'] in result.get('directorPeriods',{}) and job['status']=='pending' else job for job in jobs]
    result={**result,'jobs':jobs,'lastBatch':{'requests':budget.requests,'maxRequests':max_requests,
            'maxRuntimeSeconds':max_runtime_seconds,'finishedAt':wall_now,
            'counts':{status:sum(job['status']==status for job in jobs) for status in ('complete','pending','unavailable')}}}
    save_state(directory,result)
    return result
