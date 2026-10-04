#!/usr/bin/env python3
"""Run one bounded ownership batch or verify/materialize an offline generation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))
from pipeline.ownership_queue import new_state,load_state,run_batch,save_receipt,save_state
from pipeline.source_receipts import _write,safe_directory
from pipeline.screening_export import validate_export
from pipeline.ownership_checks import evaluate_chip_reference, FORMULA_VERSION
from scripts.fetch_ownership import (TDCC_URL,TDCC_HISTORY_URL,MOPS_URL,_NoRedirect,_read_body,_request,
    parse_tdcc_csv,parse_tdcc_available_dates,parse_tdcc_history_html,parse_mops_payload,
    normalize_tdcc_rows,completed_months,_save_snapshot,shift_month,OWNERSHIP_SNAPSHOT_VERSION)

GENERATION_VERSION='ownership-generation-v1'


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def tdcc_reported_date(document: str) -> str | None:
    match=re.search(r'資料日期\s*[：:]?\s*(\d{3})年\s*(\d{1,2})月\s*(\d{1,2})日',document)
    if not match:
        return None
    try:
        return date(int(match[1])+1911,int(match[2]),int(match[3])).isoformat()
    except ValueError:
        return None


def validated_mops_rows(payload: dict, *, code: str,period: str,retrieved_at: str) -> list[dict]:
    parent=payload.get('result',{}).get('parentCompany',{})
    expected=f'{int(period[:4])-1911:03d}{period[5:]}'
    if str(parent.get('companyId'))!=code or str(parent.get('yymm'))!=expected:
        raise ValueError('official MOPS identity or period mismatch')
    rows=parse_mops_payload(payload,code=code,period=period,retrieved_at=retrieved_at)
    market={'上市公司':'TWSE','上櫃公司':'TPEX'}.get(parent.get('marketName'))
    return [{**row,'market':market,'availableAt':None,'availabilityBasis':'retrieval-only'} for row in rows]


def make_worker(state_dir: Path, roster: list[str], verified_market_date=None):
    receipts_dir=state_dir/'receipts'
    def worker(job,budget):
        retrieved=utc_now()
        source=job['source']
        def capture(raw,url,parameters,source_date,rows):
            return save_receipt(receipts_dir,raw,source=source,url=url,parameters=parameters,
                                retrieved_at=retrieved,source_date=source_date,rows=rows,selected_codes=roster if source=='TDCC_LATEST' else None)
        if source=='DIRECTOR_PERIODS':
            periods={}
            captured=[]
            endpoints=[('https://openapi.twse.com.tw/v1/opendata/t187ap11_L','TWSE'),
                       ('https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O','TPEX')]
            for url,market in endpoints:
                raw=_request(url,budget=budget,retries=0)
                payload=json.loads(raw)
                observations=[]
                for row in payload if isinstance(payload,list) else []:
                    code=str(row.get('公司代號','')).strip()
                    period=str(row.get('資料年月',''))
                    if code not in roster or not re.fullmatch(r'\d{5}',period):
                        continue
                    month=f'{int(period[:3])+1911:04d}-{period[3:]}'
                    if verified_market_date and month>verified_market_date[:7]:
                        continue
                    periods[code]=max(periods.get(code,''),month)
                    observations.append({'code':code,'period':month,'market':market})
                captured.append(capture(raw,url,{},max(periods.values(),default=None),observations))
            if not periods:
                raise ValueError('official director period discovery absent')
            return {'rows':[],'directorPeriods':periods,'receipts':captured}
        if source=='TDCC_LATEST':
            raw=_request(TDCC_URL,budget=budget,retries=0)
            rows=[row for row in parse_tdcc_csv(raw.decode('utf-8-sig'),retrieved_at=retrieved) if row['code'] in roster]
            source_date=max((row['asOf'] for row in rows),default=None)
            receipt=capture(raw,TDCC_URL,{'id':'1-5'},source_date,rows)
        elif source in {'TDCC_DATES','TDCC'}:
            opener=build_opener(HTTPCookieProcessor(CookieJar()),_NoRedirect())
            with opener.open(Request(TDCC_HISTORY_URL),timeout=budget.consume(20,historical=True)) as response:
                page_raw=_read_body(response,budget)
            page=page_raw.decode('utf-8','replace')
            dates=parse_tdcc_available_dates(page)
            if not dates:
                raise ValueError('TDCC official available dates absent')
            if source=='TDCC_DATES':
                receipt=capture(page_raw,TDCC_HISTORY_URL,{},None,[])
                return {'availableDates':dates,'rows':[],'receipts':[receipt]}
            selected=job['sourceDate']
            if selected not in dates:
                return {'outcome':'unavailable','rows':[]}
            def hidden(name):
                match=re.search(r'name=["\']'+name+r'["\'][^>]*value=["\']([^"\']*)',page,re.I)
                if not match:
                    raise ValueError('TDCC session field absent')
                return match[1]
            public={'method':'submit','firDate':selected.replace('-',''),'scaDate':selected.replace('-',''),
                    'sqlMethod':'StockNo','stockNo':job['code'],'stockName':''}
            form={**public,'SYNCHRONIZER_TOKEN':hidden('SYNCHRONIZER_TOKEN'),'SYNCHRONIZER_URI':hidden('SYNCHRONIZER_URI')}
            request=Request(TDCC_HISTORY_URL,data=urlencode(form).encode(),headers={'Content-Type':'application/x-www-form-urlencoded'})
            with opener.open(request,timeout=budget.consume(20,historical=True)) as response:
                raw=_read_body(response,budget)
            document=raw.decode('utf-8','replace')
            if tdcc_reported_date(document)!=selected:
                raise ValueError('TDCC official report date mismatch')
            rows=normalize_tdcc_rows(parse_tdcc_history_html(document,code=job['code'],as_of=selected),
                                     retrieved_at=retrieved,source='TDCC',dataset='history')
            if not rows or any(row['largeHolderPct'] is None or row['shareholderCount'] is None for row in rows):
                raise ValueError('TDCC official metric rows absent')
            receipt=capture(raw,TDCC_HISTORY_URL,public,selected,rows)
        elif source=='MOPS':
            period=job['period']
            parameters={'companyId':job['code'],'dataType':'2','year':str(int(period[:4])-1911),'month':str(int(period[5:]))}
            raw=_request(MOPS_URL,data=json.dumps(parameters).encode(),budget=budget,retries=0)
            payload=json.loads(raw)
            if payload.get('code')!=200:
                return {'outcome':'unavailable','rows':[], 'receipts':[capture(raw,MOPS_URL,parameters,None,[])]}
            rows=validated_mops_rows(payload,code=job['code'],period=period,retrieved_at=retrieved)
            receipt=capture(raw,MOPS_URL,parameters,period,rows)
        else:
            raise ValueError('unknown official ownership source')
        rows=[{**row,'rawSha256':receipt['rawSha256'],'rawReceiptPath':'receipts/'+receipt['receiptFile'],
               'sourceURL':receipt['sourceURL'],'availableAt':None,'availabilityBasis':'retrieval-only',
               'historicalBackfill':bool(row.get('sourceDate') and str(row['sourceDate'])[:7]<retrieved[:7])} for row in rows]
        return {'rows':rows,'receipts':[receipt],'outcome':'complete' if rows else 'unavailable'}
    return worker


def import_bootstrap(state: dict,state_dir: Path,probe_directory: Path) -> dict:
    """Reparse verified public probe responses without issuing HTTP requests."""
    from pipeline.ownership_inputs import merge_ownership_rows
    from urllib.parse import parse_qs
    rows=[]
    receipts=[]
    periods=dict(state.get('directorPeriods',{}))
    dates=set(state.get('availableDates',[]))
    evidence=json.loads((probe_directory/'all-receipts.json').read_bytes())
    for original in evidence:
        name=original['name']
        match=re.fullmatch(r'(mops|tdcc)-(\d{4,6}[A-Z]?)-(\d{6}|\d{8})',name)
        if not match or match[2] not in state['roster']:
            continue
        source,code,requested=match.groups()
        path=probe_directory/(name+'.raw')
        raw=path.read_bytes()
        if _hash(raw)!=original['rawSha256']:
            raise ValueError('bootstrap original response hash mismatch')
        retrieved=original['retrievedAt']
        if source=='mops':
            period=requested[:4]+'-'+requested[4:6]
            if period>state['verifiedMarketDate'][:7]:
                raise ValueError('bootstrap future director period')
            parsed=validated_mops_rows(json.loads(raw),code=code,period=period,retrieved_at=retrieved)
            parameters=json.loads(original['requestBody'])
            if int(parameters['year'])+1911!=int(period[:4]) or int(parameters['month'])!=int(period[5:]) or parameters['companyId']!=code:
                raise ValueError('bootstrap MOPS request identity mismatch')
            source_date=period
            if period>=state['targetMonths'][0]:
                periods[code]=max(periods.get(code,''),period)
            url=MOPS_URL
        else:
            source_date=requested[:4]+'-'+requested[4:6]+'-'+requested[6:]
            if source_date[:7] not in state['targetMonths']:
                continue
            document=raw.decode('utf-8')
            if tdcc_reported_date(document)!=source_date:
                continue
            official_dates=parse_tdcc_available_dates(document)
            if not official_dates or source_date!=max(value for value in official_dates if value[:7]==source_date[:7]):
                raise ValueError('bootstrap TDCC date is not official last week')
            dates.update(official_dates)
            parsed=normalize_tdcc_rows(parse_tdcc_history_html(document,code=code,as_of=source_date),retrieved_at=retrieved,source='TDCC',dataset='history')
            parameters={'stockNo':code,'firDate':requested,'scaDate':requested,'sqlMethod':'StockNo','method':'submit','stockName':''}
            url=TDCC_HISTORY_URL
        receipt=save_receipt(state_dir/'receipts',raw,source=source.upper(),url=url,parameters=parameters,
                             retrieved_at=retrieved,source_date=source_date,rows=parsed)
        receipts.append(receipt)
        rows.extend({**row,'rawSha256':receipt['rawSha256'],'rawReceiptPath':'receipts/'+receipt['receiptFile'],
                     'sourceURL':url,'availableAt':None,'availabilityBasis':'retrieval-only','historicalBackfill':True} for row in parsed)
    jobs=[]
    for job in state['jobs']:
        if job['source']=='MOPS' and job['code'] in periods:
            period=shift_month(periods[job['code']],-12) if job['period']<state['targetMonths'][0] else periods[job['code']]
            job={**job,'period':period,'sourceDate':period,'key':f"MOPS:{job['code']}:{period}",
                 'comparisonPrevious':period!=periods[job['code']]}
        if job['source']=='TDCC':
            available=[value for value in dates if value[:7]==job['period']]
            if available:
                selected=max(available)
                job={**job,'sourceDate':selected,'key':f"TDCC:{job['code']}:{job['period']}:{selected}"}
        if any(row['code']==job['code'] and row['period']==job['period'] and
               ((job['source']=='TDCC' and row['source']=='TDCC') or (job['source']=='MOPS' and row['source']=='MOPS')) for row in rows):
            job={**job,'status':'complete','lastError':None}
        if job['source']=='TDCC_DATES' and dates:
            job={**job,'status':'complete'}
        jobs.append(job)
    result={**state,'directorPeriods':periods,'availableDates':sorted(dates),'jobs':jobs,
            'rows':merge_ownership_rows(state['rows'],rows),'receipts':[*state['receipts'],*receipts]}
    save_state(state_dir,result)
    return result


def advance_state(state: dict,roster: list[str],priority: list[str],verified_market_date: str) -> dict:
    """Roll a frozen daily queue forward while retaining verified source evidence."""
    fresh=new_state(roster,priority,verified_market_date)
    old={job['key']:job for job in state['jobs'] if job['source'] not in {'TDCC_DATES','TDCC_LATEST','DIRECTOR_PERIODS'}}
    jobs=[]
    for job in fresh['jobs']:
        if job['source']=='TDCC':
            dates=[value for value in state['availableDates'] if value[:7]==job['period']]
            if dates:
                selected=max(dates)
                job={**job,'sourceDate':selected,'key':f"TDCC:{job['code']}:{job['period']}:{selected}"}
        jobs.append(dict(old.get(job['key'],job)))
    return {**fresh,'jobs':jobs,'availableDates':state['availableDates'],'rows':state['rows'],
            'receipts':state['receipts'],'directorPeriods':state.get('directorPeriods',{})}


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def build_manifest(state_dir: Path,snapshot_path: Path,source_git_commit: str, *,request_id='',actions_run_id='',
                   actions_run_attempt='',previous_generation=None) -> dict:
    directory=safe_directory(state_dir)
    state=load_state(directory/'queue.json')
    if state is None or not re.fullmatch(r'[a-f0-9]{40}',source_git_commit):
        raise ValueError('generation requires queue and full source commit')
    snapshot=json.loads(snapshot_path.read_bytes())
    binding={'verifiedMarketDate':state['verifiedMarketDate'],'sourceGitCommit':source_git_commit,
             'requestId':str(request_id),'actionsRunId':str(actions_run_id),'actionsRunAttempt':str(actions_run_attempt),
             'previousGeneration':previous_generation,'rosterHash':_hash(_canonical(state['roster'])),
             'targetMonths':state['targetMonths'],'formulaVersion':FORMULA_VERSION,
             'priorityRosterMarketDate':state.get('priorityRosterMarketDate'),
             'priorityRosterPublicationHash':state.get('priorityRosterPublicationHash')}
    generation=_hash(_canonical({'binding':binding,'queueHash':_hash((directory/'queue.json').read_bytes())}))
    snapshot={**snapshot,'generationId':generation}
    _write(directory,'snapshot.json',_canonical(snapshot))
    if snapshot_path.resolve()!= (directory/'snapshot.json').resolve():
        _save_snapshot(snapshot_path,snapshot)
    files=[]
    candidates=[directory/'queue.json',directory/'snapshot.json',*sorted((directory/'receipts').glob('*'))]
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            raise ValueError('generation files must be regular')
        raw=path.read_bytes()
        files.append({'path':str(path.relative_to(directory)),'sha256':_hash(raw),'size':len(raw)})
    manifest={'schemaVersion':GENERATION_VERSION,'generationId':generation,**binding,'files':files,
              'coverage':{**{status:sum(job['status']==status for job in state['jobs']) for status in ('complete','pending','unavailable')},**metric_coverage(state)}}
    _write(directory,'manifest.json',_canonical(manifest))
    return manifest


def _semantic_errors(directory: Path,state: dict,snapshot: dict) -> list[str]:
    errors=[]
    date_value=state['verifiedMarketDate']
    roster=set(state['roster'])
    allowed={TDCC_URL,TDCC_HISTORY_URL,MOPS_URL,
             'https://openapi.twse.com.tw/v1/opendata/t187ap11_L',
             'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O'}
    receipts={}
    for receipt in state.get('receipts',[]):
        if (receipt.get('sourceURL') not in allowed or not re.fullmatch(r'[a-f0-9]{64}\.raw',receipt.get('rawFile',''))
                or not re.fullmatch(r'[a-f0-9]{64}\.json',receipt.get('receiptFile',''))
                or not 0<=receipt.get('rawBytes',-1)<=16*1024*1024):
            errors.append('generation_receipt_contract_invalid')
            continue
        if any(re.search('token|cookie|secret|authorization|password',key,re.I) for key in receipt.get('parameters',{})):
            errors.append('generation_receipt_private_parameter')
        encoded=_canonical({key:value for key,value in receipt.items() if key!='receiptFile'})
        if _hash(encoded)+'.json'!=receipt['receiptFile']:
            # save_receipt uses the standard JSON separators for its identity.
            original=json.dumps({key:value for key,value in receipt.items() if key!='receiptFile'},sort_keys=True,ensure_ascii=False).encode()
            if _hash(original)+'.json'!=receipt['receiptFile']:
                errors.append('generation_receipt_metadata_hash_invalid')
        stored=json.loads((directory/'receipts'/receipt['receiptFile']).read_bytes())
        if stored!=receipt:
            errors.append('generation_receipt_metadata_mismatch')
        raw=(directory/'receipts'/receipt['rawFile']).read_bytes()
        if _hash(raw)!=receipt['rawSha256'] or len(raw)!=receipt['rawBytes']:
            errors.append('generation_receipt_raw_invalid')
        if receipt['sourceURL']==TDCC_HISTORY_URL and re.search(rb'<input\b(?=[^>]*(?:SYNCHRONIZER_TOKEN|csrf|sessiontoken))[^>]*>',raw,re.I):
            errors.append('generation_receipt_transient_token')
        if receipt['sourceURL'] in {'https://openapi.twse.com.tw/v1/opendata/t187ap11_L','https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O'}:
            market='TWSE' if 'twse.com.tw' in receipt['sourceURL'] else 'TPEX'
            normalized=[]
            for raw_row in json.loads(raw):
                code=str(raw_row.get('公司代號','')).strip()
                period=str(raw_row.get('資料年月',''))
                if code not in roster or not re.fullmatch(r'\d{5}',period):
                    continue
                month=f'{int(period[:3])+1911:04d}-{period[3:]}'
                if month<=date_value[:7]:
                    normalized.append({'code':code,'period':month,'market':market})
            if normalized!=receipt['rows']:
                errors.append('generation_receipt_period_proof_invalid')
        if receipt['sourceURL']==TDCC_URL:
            normalized=parse_tdcc_csv(raw.decode('utf-8'),retrieved_at=receipt['retrievedAt'])
            if normalized!=receipt['rows'] or receipt.get('rawSanitization')!='roster-filtered-csv-v1' or not set(receipt.get('selectedCodes') or [])<=roster:
                errors.append('generation_receipt_normalization_mismatch')
        if receipt['sourceURL']==MOPS_URL and receipt.get('rows'):
            parameters=receipt['parameters']
            period=f"{int(parameters['year'])+1911:04d}-{int(parameters['month']):02d}"
            normalized=validated_mops_rows(json.loads(raw),code=parameters['companyId'],period=period,retrieved_at=receipt['retrievedAt'])
            if normalized!=receipt['rows']:
                errors.append('generation_receipt_normalization_mismatch')
        if receipt['sourceURL']==TDCC_HISTORY_URL and receipt.get('rows'):
            parameters=receipt['parameters']
            reported=tdcc_reported_date(raw.decode('utf-8'))
            if reported!=receipt['sourceDate'] or reported.replace('-','')!=parameters['scaDate']:
                errors.append('generation_receipt_date_mismatch')
            normalized=normalize_tdcc_rows(parse_tdcc_history_html(raw.decode('utf-8'),code=parameters['stockNo'],as_of=reported),
                                           retrieved_at=receipt['retrievedAt'],source='TDCC',dataset='history')
            if normalized!=receipt['rows']:
                errors.append('generation_receipt_normalization_mismatch')
        receipts['receipts/'+receipt['receiptFile']]=receipt
    encoded_rows={_canonical(row) for row in state['rows']}
    if any(_canonical(row) not in encoded_rows for row in snapshot.get('rows',[])):
        errors.append('generation_snapshot_not_from_queue')
    for row in state['rows']:
        if row.get('code') not in roster or any(str(row[field])>date_value for field in ('period','asOf','sourceDate','publishedAt','availableAt') if row.get(field)):
            errors.append('generation_observation_identity_invalid')
        observations=row.get('sourceObservations') or [row]
        from pipeline.ownership_inputs import merge_ownership_rows
        derived=merge_ownership_rows(observations)
        metrics=('largeHolderPct','shareholderCount','directorSupervisorPct','directorSupervisorShares',
                 'officialDirectorSupervisorShares','directorDenominator','directorIdentityConsistent')
        if len(derived)!=1 or any(row.get(field)!=derived[0].get(field) for field in metrics):
            errors.append('generation_merged_values_invalid')
        for observation in observations:
            if any(str(observation[field])>date_value for field in ('period','asOf','sourceDate','publishedAt','availableAt') if observation.get(field)):
                errors.append('generation_source_observation_future')
            receipt=receipts.get(observation.get('rawReceiptPath'))
            if (not receipt or observation.get('rawSha256')!=receipt['rawSha256']
                    or observation.get('sourceURL')!=receipt['sourceURL']):
                errors.append('generation_observation_receipt_invalid')
                continue
            fields=('code','period','asOf','sourceDate','largeHolderPct','shareholderCount','directorSupervisorPct',
                    'directorSupervisorShares','officialDirectorSupervisorShares','directorDenominator','directorIdentityConsistent')
            if not any(all(observation.get(field)==raw_row.get(field) for field in fields) for raw_row in receipt['rows']):
                errors.append('generation_observation_values_invalid')
    return errors


def validate_generation(directory: Path,expected_date=None,expected_commit=None) -> list[str]:
    """Fail closed on content, identity, and receipt corruption; no HTTP."""
    try:
        directory=safe_directory(directory)
        manifest_path=directory/'manifest.json'
        if manifest_path.is_symlink() or manifest_path.stat().st_size>4*1024*1024:
            raise ValueError('manifest symlink')
        manifest=json.loads(manifest_path.read_bytes())
        if manifest.get('schemaVersion')!=GENERATION_VERSION:
            return ['generation_schema_invalid']
        allowed_keys={'schemaVersion','generationId','verifiedMarketDate','sourceGitCommit','requestId','actionsRunId',
                      'actionsRunAttempt','previousGeneration','rosterHash','targetMonths','formulaVersion',
                      'priorityRosterMarketDate','priorityRosterPublicationHash','files','coverage'}
        files=manifest.get('files')
        if set(manifest)-allowed_keys or not isinstance(files,list) or len(files)>10000:
            raise ValueError('invalid generation manifest bounds')
        if any(not isinstance(item,dict) or set(item)!={'path','sha256','size'} or type(item['size']) is not int
               or not 0<=item['size']<=32*1024*1024 for item in files):
            raise ValueError('invalid generation file bounds')
        if sum(item['size'] for item in files)>256*1024*1024:
            raise ValueError('generation exceeds aggregate byte limit')
        actual_bytes=0
        for item in files:
            if not re.fullmatch(r'(?:queue\.json|snapshot\.json|receipts/[a-f0-9]{64}\.(?:raw|json))',item['path']):
                raise ValueError('invalid generation file path')
            path=directory/item['path']
            if path.is_symlink() or not path.is_file() or safe_directory(path.parent)!=path.parent.resolve():
                raise ValueError('invalid generation file')
            size=path.stat().st_size
            if size>32*1024*1024:
                raise ValueError('generation file exceeds limit')
            actual_bytes+=size
        if actual_bytes>256*1024*1024:
            raise ValueError('generation exceeds aggregate byte limit')
        errors=[]
        if expected_date and manifest.get('verifiedMarketDate')!=expected_date:
            errors.append('generation_date_mismatch')
        if expected_commit and manifest.get('sourceGitCommit')!=expected_commit:
            errors.append('generation_commit_mismatch')
        declared=set()
        for item in manifest['files']:
            relative=Path(item['path'])
            if relative.is_absolute() or '..' in relative.parts or item['path'] in declared or not re.fullmatch(r'(?:queue\.json|snapshot\.json|receipts/[a-f0-9]{64}\.(?:raw|json))',item['path']):
                raise ValueError('invalid generation file path')
            declared.add(item['path'])
            path=directory/relative
            if path.is_symlink() or safe_directory(path.parent)!=path.parent.resolve():
                raise ValueError('generation symlink')
            if item.get('size',0)>32*1024*1024 or path.stat().st_size>32*1024*1024:
                raise ValueError('generation file exceeds limit')
            raw=path.read_bytes()
            if len(raw)!=item['size'] or _hash(raw)!=item['sha256']:
                errors.append('generation_file_hash_mismatch:'+item['path'])
        actual={'queue.json','snapshot.json'}|{str(path.relative_to(directory)) for path in (directory/'receipts').glob('*')}
        if declared!=actual:
            errors.append('generation_file_set_mismatch')
        state=load_state(directory/'queue.json')
        binding={key:manifest[key] for key in ('verifiedMarketDate','sourceGitCommit','requestId','actionsRunId',
            'actionsRunAttempt','previousGeneration','rosterHash','targetMonths','formulaVersion','priorityRosterMarketDate','priorityRosterPublicationHash')}
        expected_generation=_hash(_canonical({'binding':binding,'queueHash':_hash((directory/'queue.json').read_bytes())}))
        snapshot=json.loads((directory/'snapshot.json').read_bytes())
        if (manifest['generationId']!=expected_generation or snapshot.get('generationId')!=expected_generation
                or snapshot.get('schemaVersion')!=OWNERSHIP_SNAPSHOT_VERSION):
            errors.append('generation_identity_invalid')
        if (binding['verifiedMarketDate']!=state['verifiedMarketDate'] or binding['targetMonths']!=completed_months(state['verifiedMarketDate'])
                or binding['rosterHash']!=_hash(_canonical(state['roster']))):
            errors.append('generation_roster_invalid')
        if state.get('priorityRosterMarketDate') and (state['priorityRosterMarketDate']>state['verifiedMarketDate'] or manifest['priorityRosterMarketDate']!=state['priorityRosterMarketDate'] or manifest['priorityRosterPublicationHash']!=state.get('priorityRosterPublicationHash')):
            errors.append('generation_priority_roster_invalid')
        expected_coverage={**{status:sum(job['status']==status for job in state['jobs']) for status in ('complete','pending','unavailable')},**metric_coverage(state)}
        if manifest.get('coverage')!=expected_coverage or manifest.get('formulaVersion')!=FORMULA_VERSION:
            errors.append('generation_coverage_invalid')
        errors.extend(_semantic_errors(directory,state,snapshot))
        return errors
    except (OSError,ValueError,KeyError,TypeError):
        return ['generation_invalid']


def metric_coverage(state: dict) -> dict:
    by_code={code:[row for row in state['rows'] if row['code']==code] for code in state['roster']}
    tdcc=0
    directors=0
    for code,rows in by_code.items():
        evaluated=evaluate_chip_reference(rows,evaluation_date=state['verifiedMarketDate'])
        tdcc+=int(all(evaluated[field]['status'] in {'pass','fail'} for field in ('largeHolderTrend','shareholderCountTrend')))
        directors+=int(evaluated['directorSupervisor12m']['status'] in {'pass','fail'})
    return {'rosterStockCount':len(state['roster']),'tdccThreeMonthStockCount':tdcc,
            'directorComparableStockCount':directors,'pendingTaskCount':sum(job['status']=='pending' for job in state['jobs']),
            'retryTaskCount':sum(job['status']=='pending' and job['attempts']>0 for job in state['jobs']),
            'blockedTaskCount':sum(job['status']=='unavailable' for job in state['jobs']),
            'httpRequestsLastBatch':state.get('lastBatch',{}).get('requests',0)}


def _snapshot(state):
    rows=[row for row in state['rows'] if row.get('code') in state['roster']
          and str(row.get('asOf') or row.get('period') or '')<=state['verifiedMarketDate']]
    coverage=metric_coverage(state)
    complete=all(job['status']=='complete' for job in state['jobs']) and coverage['directorComparableStockCount']==len(state['roster'])
    return {'schemaVersion':OWNERSHIP_SNAPSHOT_VERSION,'verifiedMarketDate':state['verifiedMarketDate'],
            'targetMonths':state['targetMonths'],'status':'current' if complete else 'stale' if rows else 'unavailable',
            'retrievedAt':utc_now(),'requestedCodes':state['roster'],'rows':rows,
            'sourceRefs':list(dict.fromkeys(ref for row in rows for ref in row.get('sourceRefs',[]))),
            'queueSummary':state.get('lastBatch',{}),'coverage':coverage}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--verified-market-date')
    parser.add_argument('--state-dir',required=True)
    parser.add_argument('--snapshot-output')
    parser.add_argument('--roster-publication')
    parser.add_argument('--universe',default=str(ROOT/'config/tracked_symbols.json'))
    parser.add_argument('--priority-codes')
    parser.add_argument('--bootstrap-directory')
    parser.add_argument('--import-only',action='store_true')
    parser.add_argument('--max-requests',type=int,default=20)
    parser.add_argument('--max-runtime-seconds',type=int,default=180)
    parser.add_argument('--source-git-commit',default='')
    parser.add_argument('--request-id',default='')
    parser.add_argument('--actions-run-id',default='')
    parser.add_argument('--actions-run-attempt',default='')
    parser.add_argument('--previous-generation')
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--materialize-output')
    args=parser.parse_args(argv)
    try:
        if args.verified_market_date:
            completed_months(args.verified_market_date)
        directory=safe_directory(Path(args.state_dir))
        if args.verify_only:
            errors=validate_generation(directory,expected_date=args.verified_market_date,expected_commit=args.source_git_commit or None)
            if errors:
                raise ValueError(','.join(errors))
            if args.materialize_output:
                _save_snapshot(Path(args.materialize_output),json.loads((directory/'snapshot.json').read_bytes()))
            print(json.dumps({'verified':True}))
            return 0
        if not args.verified_market_date or not args.roster_publication or not args.snapshot_output or not re.fullmatch(r'[a-f0-9]{40}',args.source_git_commit):
            raise ValueError('acquisition requires publication, snapshot output and source commit')
        publication=json.loads(Path(args.roster_publication).read_bytes())
        if validate_export(publication) or not publication.get('marketDate') or publication['marketDate']>args.verified_market_date:
            raise ValueError('invalid frozen roster publication')
        universe=json.loads(Path(args.universe).read_bytes())['symbols']
        priority=args.priority_codes.split(',') if args.priority_codes else [row['code'] for row in publication['selectedStocks']]
        state=load_state(directory/'queue.json')
        if state is None:
            state=new_state(universe,priority,args.verified_market_date)
        elif state['verifiedMarketDate']!=args.verified_market_date or set(state['roster'])!=set(universe) or state['priorityCodes']!=priority:
            state=advance_state(state,universe,priority,args.verified_market_date)
        state={**state,'priorityRosterMarketDate':publication['marketDate'],
               'priorityRosterPublicationHash':_hash(_canonical(publication))}
        if args.bootstrap_directory:
            state=import_bootstrap(state,directory,Path(args.bootstrap_directory))
        result=state if args.import_only else run_batch(state,directory,make_worker(directory,state['roster'],args.verified_market_date),max_requests=args.max_requests,
                         max_runtime_seconds=args.max_runtime_seconds)
        output=Path(args.snapshot_output)
        _save_snapshot(output,_snapshot(result))
        manifest=build_manifest(directory,output,args.source_git_commit,request_id=args.request_id,
                 actions_run_id=args.actions_run_id,actions_run_attempt=args.actions_run_attempt,previous_generation=args.previous_generation)
        print(json.dumps({'generationId':manifest['generationId'],'coverage':manifest['coverage'],'batch':result.get('lastBatch',{})}))
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('ownership_checkpoint_invalid='+type(exc).__name__,file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
