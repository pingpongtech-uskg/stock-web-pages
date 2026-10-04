import json
from pathlib import Path
import pytest


def queue_module():
    from pipeline import ownership_queue
    return ownership_queue


def test_jobs_frozen_roster_priority_and_completed_months():
    q = queue_module()
    state = q.new_state(['2330','3293'], ['3293'], '2026-10-02')
    assert state['targetMonths'] == ['2026-07','2026-08','2026-09']
    assert state['roster'] == ['3293','2330']
    assert state['jobs'][3]['code'] == '3293'
    assert len(state['jobs']) == 13
    assert len({job['key'] for job in state['jobs']}) == 13


def test_fair_failures_persist_and_completed_jobs_never_repeat(tmp_path):
    q = queue_module()
    state = q.new_state(['2330','3293'], [], '2026-10-02')
    calls = []
    def work(job, budget):
        budget.consume()
        calls.append(job['key'])
        if job['source'] == 'TDCC_DATES':
            return {'availableDates':['2026-07-31','2026-08-28','2026-09-24'],'rows':[]}
        if job['code'] == '2330':
            raise TimeoutError('private details')
        return {'rows':[],'outcome':'unavailable'}
    first = q.run_batch(state, tmp_path, work, max_requests=6, now=100)
    assert first['lastBatch']['requests'] == 6
    assert any(job['code']=='3293' and job['status']=='unavailable' for job in first['jobs'])
    saved = q.load_state(tmp_path / 'queue.json')
    assert saved == first and 'private details' not in json.dumps(first)
    complete = {job['key'] for job in first['jobs'] if job['status']=='complete'}
    second = q.run_batch(first, tmp_path, work, max_requests=20, now=101)
    assert not complete.intersection(calls[6:])
    assert second['lastBatch']['requests'] <= 20
    assert state['jobs'][0]['status'] == 'pending'


def test_transport_attempt_and_deadline_limits(tmp_path, monkeypatch):
    q = queue_module()
    state = q.new_state(['2330'], [], '2026-10-02')
    clock=[0]
    monkeypatch.setattr(q.time,'monotonic',lambda:clock[0])
    seen=[]
    def work(job,budget):
        seen.append(budget.consume(30)); clock[0]+=seen[-1]
        raise TimeoutError()
    result=q.run_batch(state,tmp_path,work,max_requests=20,max_runtime_seconds=5,now=0)
    assert seen == [5] and result['lastBatch']['requests']==1


def test_exact_raw_receipts_immutable_and_public_parameters(tmp_path):
    q = queue_module()
    record=q.save_receipt(tmp_path,b'raw bytes',source='MOPS',url='https://mops.twse.com.tw/mops/api/stapap1',
                          parameters={'companyId':'2330','year':'115','month':'9'},retrieved_at='2026-10-04T00:00:00+00:00',
                          source_date='2026-09',rows=[{'code':'2330'}])
    assert (tmp_path / record['rawFile']).read_bytes()==b'raw bytes'
    assert record['publishedAt'] is None and record['sourceDate']=='2026-09'
    with pytest.raises(ValueError):
        q.save_receipt(tmp_path,b'x',source='MOPS',url='https://mops.twse.com.tw/api?token=x',parameters={},
                       retrieved_at='2026-10-04T00:00:00+00:00',source_date=None,rows=[])


def test_state_rejects_duplicate_and_invalid_codes():
    q=queue_module()
    with pytest.raises(ValueError): q.new_state(['oops'],[],'2026-10-02')
    with pytest.raises(ValueError): q.new_state(['2330','2330'],[],'2026-10-02')


def test_tdcc_transient_response_controls_sanitized_with_distinct_original_hash(tmp_path):
    q=queue_module()
    raw=b'<html><input name="SYNCHRONIZER_TOKEN" value="ephemeral"><table>public report</table></html>'
    record=q.save_receipt(tmp_path,raw,source='TDCC',url='https://www.tdcc.com.tw/portal/zh/smWeb/qryStock',parameters={'stockNo':'2330'},
                          retrieved_at='2026-10-04T00:00:00+00:00',source_date='2026-09-24',rows=[])
    stored=(tmp_path/record['rawFile']).read_bytes()
    assert b'ephemeral' not in stored and b'public report' in stored
    assert record['originalResponseSha256']!=record['rawSha256']
    assert record['rawSanitization']=='transient-session-controls-removed'


def test_verified_director_discovery_rekeys_exact_month_comparison(tmp_path):
    q=queue_module()
    state=q.new_state(['2330'],[],'2026-10-02')
    def worker(job,budget):
        budget.consume()
        return {'rows':[],'directorPeriods':{'2330':'2026-08'}} if job['source']=='DIRECTOR_PERIODS' else {'rows':[]}
    state=q.run_batch(state,tmp_path,worker,max_requests=3,now=0)
    assert state['directorPeriods']=={'2330':'2026-08'}
    assert {job['period'] for job in state['jobs'] if job['source']=='MOPS'}=={'2025-08','2026-08'}


def test_latest_csv_receipt_limits_roster_and_preserves_original_response_hash(tmp_path):
    q=queue_module()
    raw='資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n20261002,2330,15,1,100,10\n20261002,9999,15,1,100,20\n'.encode()
    record=q.save_receipt(tmp_path,raw,source='TDCC_LATEST',url='https://opendata.tdcc.com.tw/getOD.ashx?id=1-5',parameters={'id':'1-5'},
                          retrieved_at='2026-10-04T00:00:00+00:00',source_date='2026-10-02',rows=[],selected_codes=['2330'])
    stored=(tmp_path/record['rawFile']).read_bytes()
    assert b'9999' not in stored and b'2330' in stored
    assert record['rawSanitization']=='roster-filtered-csv-v1'
    assert record['originalResponseSha256']!=record['rawSha256']
