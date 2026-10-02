import json,hashlib
from scripts.verify_history_archive import verify_archive
from pipeline.history_archive import canonical_json_bytes

def test_verifier_rejects_hash_and_suffix(tmp_path):
 a=tmp_path/'archive'; (a/'months').mkdir(parents=True)
 p=a/'months/2026-09.aaaaaaaaaaaa.json'; payload=canonical_json_bytes({'schemaVersion':'screening-history-month-v1','month':'2026-09','records':[]}); p.write_bytes(payload)
 (a/'index.json').write_text(json.dumps({'schemaVersion':'screening-history-index-v1','months':[{'month':'2026-09','path':'/data/archive/v1/months/'+p.name,'sha256':'0'*64}] }))
 assert verify_archive(a)


def valid_archive(tmp_path):
 from pipeline.history_archive import project_release_to_history,write_archive_atomic
 record=project_release_to_history({'marketDate':'2026-10-02','runId':'r1','generatedAt':'2026-10-02T10:00:00Z','freshness':'current','rankings':{}})
 archive=tmp_path/'archive'
 write_archive_atomic(tmp_path/'staging',archive,{'2026-10':[record]},'2026-10-02T10:00:00Z')
 return archive


def test_verifier_checks_bounds_counts_retention_and_missing_objects(tmp_path):
 a=valid_archive(tmp_path); index=json.loads((a/'index.json').read_bytes())
 index['earliestMarketDate']='2026-10-01'; index['latestMarketDate']='2026-10-01'
 index['generatedAt']='2027-12-31'; index['months'][0]['recordCount']=99; index['months'][0]['bytes']=0
 index['months'][0]['marketDates']=[]; index['months'][0]['marketDateStart']='2026-01-01'
 (a/'index.json').write_text(json.dumps(index))
 errors=verify_archive(a)
 assert 'earliest date' in errors and 'latest date' in errors and 'retention dates' in errors
 assert any(e.startswith('month count:') for e in errors)
 assert any(e.startswith('month bounds:') for e in errors)
 p=a/'months'/index['months'][0]['path'].split('/')[-1]; p.unlink()
 assert any(e.startswith('month missing:') for e in verify_archive(a))


def test_revision_tampering_and_missing_file_are_rejected(tmp_path):
 a=valid_archive(tmp_path); index=json.loads((a/'index.json').read_bytes())
 record=json.loads((a/'months'/index['months'][0]['path'].split('/')[-1]).read_bytes())['records'][0]
 ref=record['revisionRefs'][0]; p=a/'revisions'/ref['path'].split('/')[-1]
 value=json.loads(p.read_bytes()); value['runId']='tampered'; p.write_text(json.dumps(value))
 errors=verify_archive(a)
 assert any(e.startswith('revision hash:') for e in errors)
 assert any(e.startswith('saved revision:') for e in errors)
 p.write_text('not json')
 assert any(e.startswith('saved revision invalid:') for e in verify_archive(a))
 p.unlink()
 assert any(e.startswith('revision missing:') for e in verify_archive(a))


def test_verifier_cli_and_malformed_index_fail_closed(tmp_path):
 from scripts.verify_history_archive import main
 a=tmp_path/'empty'; a.mkdir()
 assert verify_archive(a)==['index missing']
 (a/'index.json').write_text('broken')
 assert verify_archive(a)[0].startswith('index invalid:')
 (a/'index.json').write_text('[]')
 assert verify_archive(a)==['index shape']
 assert main(['--archive',str(a)])==1
 assert main(['--archive',str(valid_archive(tmp_path))])==0


def test_rebuild_never_drops_indexed_history_when_month_missing(tmp_path):
 from scripts.build_history_archive import main
 a=valid_archive(tmp_path)
 data=tmp_path/'data'; (data/'archive').mkdir(parents=True)
 import shutil
 shutil.move(str(a),str(data/'archive/v1'))
 archive=data/'archive/v1'; original=(archive/'index.json').read_bytes()
 index=json.loads(original); (archive/'months'/index['months'][0]['path'].split('/')[-1]).unlink()
 (data/'latest.json').write_text(json.dumps({'marketDate':'2026-10-02','runId':'new','generatedAt':'2026-10-02T10:00:00Z','freshness':'current','rankings':{}}))
 assert main(['--data-dir',str(data),'--as-of','2026-10-02'])==1
 assert (archive/'index.json').read_bytes()==original
