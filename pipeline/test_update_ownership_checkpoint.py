import json
import pytest


def module():
    from scripts import update_ownership_checkpoint
    return update_ownership_checkpoint


def test_manifest_binds_every_file_and_rejects_mutation(tmp_path):
    m=module()
    from pipeline.ownership_queue import new_state,save_state
    save_state(tmp_path,new_state(['2330'],[],'2026-10-02'))
    snapshot=tmp_path/'snapshot.json'
    snapshot.write_text(json.dumps({'schemaVersion':'ownership-snapshot-v1','rows':[],'verifiedMarketDate':'2026-10-02'}))
    manifest=m.build_manifest(tmp_path,snapshot,'a'*40,request_id='r',actions_run_id='123',actions_run_attempt='2')
    assert manifest['requestId']=='r' and manifest['targetMonths']==['2026-07','2026-08','2026-09']
    assert m.validate_generation(tmp_path,expected_date='2026-10-02',expected_commit='a'*40)==[]
    snapshot.write_text('{}')
    assert m.validate_generation(tmp_path)


def test_cli_verify_only_never_fetches_and_materializes_valid_generation(tmp_path,monkeypatch):
    m=module()
    from pipeline.ownership_queue import new_state,save_state
    state_dir=tmp_path/'state'; state_dir.mkdir()
    save_state(state_dir,new_state(['2330'],[],'2026-10-02'))
    snapshot=state_dir/'snapshot.json'
    snapshot.write_text(json.dumps({'schemaVersion':'ownership-snapshot-v1','rows':[],'verifiedMarketDate':'2026-10-02'}))
    m.build_manifest(state_dir,snapshot,'a'*40)
    monkeypatch.setattr(m,'make_worker',lambda *args:pytest.fail('must not fetch'))
    output=tmp_path/'materialized.json'
    assert m.main(['--state-dir',str(state_dir),'--verified-market-date','2026-10-02',
                   '--verify-only','--materialize-output',str(output),'--source-git-commit','a'*40])==0
    assert json.loads(output.read_text())['verifiedMarketDate']=='2026-10-02'


def test_raw_mops_period_mismatch_rejected():
    m=module()
    with pytest.raises(ValueError):
        m.validated_mops_rows({'result':{'parentCompany':{'companyId':'2330','yymm':'11508','data':[]}}},
                              code='2330',period='2026-09',retrieved_at='2026-10-04T00:00:00+00:00')


def test_tdcc_requested_and_returned_date_must_match():
    m=module()
    document='<div>資料日期：115年09月24日</div>'
    assert m.tdcc_reported_date(document)=='2026-09-24'
    assert m.tdcc_reported_date('<div>no date</div>') is None


def test_cli_validation_fails_before_network_or_state_write(tmp_path):
    m=module()
    assert m.main(['--state-dir',str(tmp_path/'state'),'--verified-market-date','2026-10-99',
                   '--roster-publication',str(tmp_path/'none'),'--snapshot-output',str(tmp_path/'snapshot')])==1
    assert not (tmp_path/'state').exists()


def test_bootstrap_import_checks_exact_response_hash_and_periods(tmp_path):
    m=module()
    from pipeline.ownership_queue import new_state
    raw='{"code":200,"result":{"parentCompany":{"companyId":"2330","marketName":"上市公司","yymm":"11508","data":[["董事本人","甲","0","100"]],"total":{"allDirectorSupervisor":["100"]}}}}'.encode()
    probe=tmp_path/'probe';probe.mkdir()
    (probe/'mops-2330-202608.raw').write_bytes(raw)
    import hashlib
    receipt={'name':'mops-2330-202608','url':'https://mops.twse.com.tw/mops/api/stapap1','rawSha256':hashlib.sha256(raw).hexdigest(),
             'retrievedAt':'2026-10-04T00:00:00+00:00','requestBody':'{"companyId":"2330","year":"115","month":"8","dataType":"2"}'}
    (probe/'all-receipts.json').write_text(json.dumps([receipt]))
    state=m.import_bootstrap(new_state(['2330'],[],'2026-10-02'),tmp_path/'state',probe)
    assert state['directorPeriods']=={'2330':'2026-08'}
    assert state['rows'][0]['officialDirectorSupervisorShares']==100
    assert any(job['status']=='complete' and job['period']=='2026-08' for job in state['jobs'])
    (probe/'mops-2330-202608.raw').write_bytes(b'tampered')
    with pytest.raises(ValueError):m.import_bootstrap(new_state(['2330'],[],'2026-10-02'),tmp_path/'other',probe)


def test_semantic_verifier_rejects_forged_future_or_unreceipted_observations(tmp_path):
    m=module()
    from pipeline.ownership_queue import new_state,save_state
    save_state(tmp_path,new_state(['2330'],[],'2026-10-02'))
    snapshot=tmp_path/'snapshot.json'
    snapshot.write_text(json.dumps({'schemaVersion':'ownership-snapshot-v1','verifiedMarketDate':'2026-10-02',
        'rows':[{'code':'2330','period':'2027-12','asOf':'2027-12-31','largeHolderPct':99,'sourceURL':'https://attacker.invalid/'}]}))
    m.build_manifest(tmp_path,snapshot,'a'*40)
    assert m.validate_generation(tmp_path)


def test_daily_rollover_retains_exact_completed_months_and_resets_discovery():
    m=module()
    from pipeline.ownership_queue import new_state
    old=new_state(['2330'],[],'2026-10-02')
    old['availableDates']=['2026-07-31','2026-08-28','2026-09-24']
    old['jobs'][3]={**old['jobs'][3],'status':'complete','sourceDate':'2026-07-31','key':'TDCC:2330:2026-07:2026-07-31'}
    fresh=m.advance_state(old,['2330'],[],'2026-10-05')
    assert fresh['jobs'][3]['status']=='complete' and fresh['jobs'][0]['status']=='pending'
    assert fresh['verifiedMarketDate']=='2026-10-05'


def test_roster_rollover_keeps_prior_official_evidence_without_leaking_it_to_snapshot(tmp_path):
    m=module()
    from pipeline.ownership_queue import new_state,save_receipt,save_state
    old_roster=['2330','2547']
    receipts_dir=tmp_path/'receipts'
    csv_raw=('資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n'
             '20261002,2330,15,1,100,5\n20261002,2547,15,2,200,6\n').encode()
    tdcc_rows=m.parse_tdcc_csv(csv_raw.decode(),retrieved_at='2026-10-02T12:00:00+00:00')
    tdcc=save_receipt(receipts_dir,csv_raw,source='TDCC_LATEST',url=m.TDCC_URL,
        parameters={'id':'1-5'},retrieved_at='2026-10-02T12:00:00+00:00',
        source_date='2026-10-02',rows=tdcc_rows,selected_codes=old_roster)
    period_raw=json.dumps([{'公司代號':'2330','資料年月':'11508'},
                           {'公司代號':'2547','資料年月':'11508'}],ensure_ascii=False).encode()
    period_url='https://openapi.twse.com.tw/v1/opendata/t187ap11_L'
    period_rows=[{'code':code,'period':'2026-08','market':'TWSE'} for code in old_roster]
    periods=save_receipt(receipts_dir,period_raw,source='DIRECTOR_PERIODS',url=period_url,
        parameters={},retrieved_at='2026-10-02T12:00:00+00:00',source_date='2026-08',
        rows=period_rows,selected_codes=old_roster)

    old=new_state(old_roster,[],'2026-10-02')
    old['receipts']=[tdcc,periods]
    fixture=(m.ROOT/'pipeline/fixtures/ownership/mops-2547-202608.json').read_bytes()
    parsed=m.validated_mops_rows(json.loads(fixture),code='2547',period='2026-08',retrieved_at='2026-10-02T12:00:00+00:00')
    mops=save_receipt(receipts_dir,fixture,source='MOPS',url=m.MOPS_URL,
        parameters={'companyId':'2547','year':'115','month':'8','dataType':'2'},
        retrieved_at='2026-10-02T12:00:00+00:00',source_date='2026-08',rows=parsed)
    observation={**parsed[0],'rawSha256':mops['rawSha256'],
        'rawReceiptPath':'receipts/'+mops['receiptFile'],'sourceURL':m.MOPS_URL}
    old['receipts'].append(mops)
    old['rows']=[{**observation,'sourceObservations':[observation]}]

    rolled=m.advance_state(old,['2330'],[],'2026-10-05')
    save_state(tmp_path,rolled)
    snapshot=tmp_path/'snapshot.json'
    m._save_snapshot(snapshot,m._snapshot(rolled))
    manifest=m.build_manifest(tmp_path,snapshot,'a'*40)

    assert m.validate_generation(tmp_path,expected_date='2026-10-05',expected_commit='a'*40)==[]
    assert [row['code'] for row in json.loads(snapshot.read_text())['rows']]==[]
    import base64
    from pipeline.market_cache import validate_ownership_bundle
    file_names=['manifest.json',*(item['path'] for item in manifest['files'])]
    bundle={'schemaVersion':'ownership-bundle-v1','generationCommit':'b'*40,
        'manifestSha256':m._hash((tmp_path/'manifest.json').read_bytes()),
        'filesBase64':{name:base64.b64encode((tmp_path/name).read_bytes()).decode() for name in file_names}}
    assert validate_ownership_bundle(bundle,'2026-10-05')['generationCommit']=='b'*40


@pytest.mark.parametrize('publication_date,accepted', [
    ('2026-10-02', True),
    ('2026-10-05', True),
    ('2026-10-06', False),
])
def test_producer_accepts_verified_priority_roster_without_relabel(tmp_path,monkeypatch,publication_date,accepted):
    m=module()
    from pipeline.screening_export import build_export, export_bytes, validate_export
    from pipeline.test_screening_export import release
    from pipeline.ownership_queue import save_state
    # Keep this test independent of the mutable publication rebuilt by daily.yml.
    baseline={**release(),'marketDate':publication_date,'generatedAt':publication_date+'T10:00:00Z'}
    publication=build_export(baseline,request_id='fixture-priority-roster',source_git_commit='a'*40,actions_run_id='1')
    assert validate_export(publication)==[]
    publication_path=tmp_path/'publication.json';publication_path.write_bytes(export_bytes(publication))
    universe=tmp_path/'universe.json';universe.write_text(json.dumps({'symbols':[row['code'] for row in publication['selectedStocks']]}))
    monkeypatch.setattr(m,'ROOT',tmp_path/'no-checked-in-publication')
    saved=[]
    def batch(state,directory,*args,**kwargs):
        saved.append(state);save_state(directory,state);return state
    monkeypatch.setattr(m,'run_batch',batch)
    state_dir=tmp_path/'state';output=tmp_path/'snapshot.json'
    result=m.main(['--verified-market-date','2026-10-05','--state-dir',str(state_dir),
                   '--snapshot-output',str(output),'--roster-publication',str(publication_path),
                   '--universe',str(universe),'--source-git-commit','a'*40])
    assert result==(0 if accepted else 1)
    if not accepted:
        assert saved==[] and not output.exists() and not (state_dir/'queue.json').exists()
        return
    assert saved[0]['priorityRosterMarketDate']==publication_date
    assert saved[0]['priorityRosterPublicationHash']==m._hash(m._canonical(publication))
    assert saved[0]['verifiedMarketDate']=='2026-10-05'
    manifest=json.loads((state_dir/'manifest.json').read_bytes())
    assert manifest['priorityRosterMarketDate']==publication_date
    assert manifest['priorityRosterPublicationHash']==saved[0]['priorityRosterPublicationHash']
    assert m.validate_generation(state_dir,expected_date='2026-10-05',expected_commit='a'*40)==[]


def test_official_fixture_transport_roundtrip_receipts_and_semantic_generation(tmp_path,monkeypatch):
    m=module()
    from pipeline.ownership_queue import new_state,run_batch
    import urllib.request
    import io
    fixtures=m.ROOT/'pipeline/fixtures/ownership'
    tdcc=(fixtures/'tdcc-2547-20260924.html').read_bytes()
    mops=(fixtures/'mops-2547-202608.json').read_bytes()
    calls=[]
    def request(url,**kwargs):
        kwargs['budget'].consume()
        calls.append(url)
        if url==m.MOPS_URL:return mops
        if url==m.TDCC_URL:return '資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n20261002,2547,15,1,100,5\n20261002,2547,17,10,1000,100\n'.encode()
        return json.dumps([{'公司代號':'2547','資料年月':'11508'}]).encode()
    class Opener:
        def open(self,request,timeout):
            calls.append(request.get_method())
            return io.BytesIO(tdcc if request.data else tdcc+b'<input name="SYNCHRONIZER_TOKEN" value="transient"><input name="SYNCHRONIZER_URI" value="/portal/zh/smWeb/qryStock">')
    monkeypatch.setattr(m,'_request',request)
    monkeypatch.setattr(m,'build_opener',lambda *args:Opener())
    state=new_state(['2547'],[],'2026-10-02')
    state=run_batch(state,tmp_path,m.make_worker(tmp_path,state['roster'],'2026-10-02'),max_requests=20,now=0)
    assert state['directorPeriods']=={'2547':'2026-08'}
    assert state['lastBatch']['requests']<=20 and state['rows']
    output=tmp_path/'snapshot.json';m._save_snapshot(output,m._snapshot(state))
    m.build_manifest(tmp_path,output,'a'*40)
    assert m.validate_generation(tmp_path)==[]
    assert all(b'transient' not in path.read_bytes() for path in (tmp_path/'receipts').glob('*.raw'))
    director=next(row for row in state['rows'] if row['period']=='2026-08')
    assert director['officialDirectorSupervisorShares']==130992090
    assert director['directorSupervisorShares']==130992090 and director['directorIdentityConsistent'] is True
    assert director['directorSupervisorPct'] is None


def test_top_merged_metric_forgery_rejected_even_with_valid_nested_receipt(tmp_path):
    m=module()
    from pipeline.ownership_queue import new_state,save_state,save_receipt
    fixture=(m.ROOT/'pipeline/fixtures/ownership/mops-2547-202608.json').read_bytes()
    parsed=m.validated_mops_rows(json.loads(fixture),code='2547',period='2026-08',retrieved_at='2026-10-04T00:00:00+00:00')
    receipt=save_receipt(tmp_path/'receipts',fixture,source='MOPS',url=m.MOPS_URL,
        parameters={'companyId':'2547','year':'115','month':'8','dataType':'2'},retrieved_at='2026-10-04T00:00:00+00:00',source_date='2026-08',rows=parsed)
    observation={**parsed[0],'rawSha256':receipt['rawSha256'],'rawReceiptPath':'receipts/'+receipt['receiptFile'],'sourceURL':m.MOPS_URL}
    state=new_state(['2547'],[],'2026-10-02');state['rows']=[{**observation,'directorSupervisorPct':99,'sourceObservations':[observation]}];state['receipts']=[receipt]
    save_state(tmp_path,state)
    output=tmp_path/'snapshot.json';m._save_snapshot(output,m._snapshot(state));m.build_manifest(tmp_path,output,'a'*40)
    assert 'generation_merged_values_invalid' in m.validate_generation(tmp_path)


def test_generation_verifier_rejects_oversized_manifest_before_read(tmp_path,monkeypatch):
    m=module()
    manifest=tmp_path/'manifest.json'
    with manifest.open('wb') as output:
        output.truncate(4*1024*1024+1)
    original=m.Path.read_bytes
    def bounded_read(path):
        if path==manifest:pytest.fail('oversized manifest must not be read')
        return original(path)
    monkeypatch.setattr(m.Path,'read_bytes',bounded_read)
    assert m.validate_generation(tmp_path)==['generation_invalid']


def test_generation_file_count_and_aggregate_size_fail_before_file_reads(tmp_path,monkeypatch):
    m=module()
    (tmp_path/'receipts').mkdir()
    (tmp_path/'receipts'/('0'*64+'.raw')).write_bytes(b'')
    original=m.Path.read_bytes
    def bounded_read(path):
        if path.name!='manifest.json':pytest.fail('resource-limit failure must precede payload reads')
        return original(path)
    monkeypatch.setattr(m.Path,'read_bytes',bounded_read)
    base={'schemaVersion':m.GENERATION_VERSION,'files':[{'path':f'receipts/{index:064x}.raw','sha256':'a'*64,'size':0} for index in range(10001)]}
    (tmp_path/'manifest.json').write_text(json.dumps(base))
    assert m.validate_generation(tmp_path)==['generation_invalid']
    base['files']=[{'path':f'receipts/{index:064x}.raw','sha256':'a'*64,'size':16*1024*1024} for index in range(17)]
    (tmp_path/'manifest.json').write_text(json.dumps(base))
    assert m.validate_generation(tmp_path)==['generation_invalid']
