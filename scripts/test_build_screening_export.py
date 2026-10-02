import json
from scripts.build_screening_export import main
from scripts.build_history_archive import main as build_archive
from pipeline.screening_export import validate_export
from scripts.verify_history_archive import verify_archive


def write_release(data,run='r1'):
    data.mkdir(exist_ok=True)
    release={'marketDate':'2026-10-02','generatedAt':'2026-10-02T10:00:00Z','runId':run,'freshness':'current',
        'formulaVersion':'v1','stocks':[{'code':'2330','name':'台積電','lastPrice':100}],
        'rankings':{'trust':[{'code':'2330','rank':1,'status':'pass','reason':'selected'}],'growth':[],'lowPosition':[]}}
    (data/'latest.json').write_text(json.dumps(release))
    detail=data/'releases'/run/'stocks';detail.mkdir(parents=True)
    (detail/'2330.json').write_text(json.dumps({'code':'2330','healthInputs':{'incomeQuarterly':[{'year':2025,'quarter':4,'source':'TWSE'}]}}))


def args(data,day='2026-10-02'):
    return ['--data-dir',str(data),'--request-id','request-1','--market-date',day,
            '--source-git-commit','a'*40,'--actions-run-id','123']


def test_cli_export_and_archive_share_payload_and_preserve_correction(tmp_path):
    data=tmp_path/'data';write_release(data)
    assert main(args(data))==0
    value=json.loads((data/'screening-export.json').read_bytes())
    assert not validate_export(value)
    assert value['selectedStocks'][0]['provenance']['inputPeriods']['incomeQuarterly'][0]['source']=='TWSE'
    assert build_archive(['--data-dir',str(data),'--require-export','--as-of','2026-10-02'])==0
    index=json.loads((data/'archive/v1/index.json').read_bytes())
    record=json.loads((data/'archive/v1/months'/index['months'][0]['path'].split('/')[-1]).read_bytes())['records'][0]
    assert record['payloadHash']==value['payloadHash']
    write_release(data,'corrected')
    assert main(args(data))==0
    assert build_archive(['--data-dir',str(data),'--require-export','--as-of','2026-10-02'])==0
    assert verify_archive(data/'archive/v1')==[]
    index=json.loads((data/'archive/v1/index.json').read_bytes())
    record=json.loads((data/'archive/v1/months'/index['months'][0]['path'].split('/')[-1]).read_bytes())['records'][0]
    assert record['runId']=='corrected'
    assert len(record['revisionRefs'])==2


def test_cli_rejects_wrong_date_or_missing_selected_detail(tmp_path):
    data=tmp_path/'data';write_release(data)
    assert main(args(data,'2026-10-01'))==1
    assert not (data/'screening-export.json').exists()
    (data/'releases/r1/stocks/2330.json').unlink()
    assert main(args(data))==1
    assert not (data/'screening-export.json').exists()
    assert build_archive(['--data-dir',str(data),'--require-export'])==1
