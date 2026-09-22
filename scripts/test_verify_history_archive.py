import json,hashlib
from scripts.verify_history_archive import verify_archive
from pipeline.history_archive import canonical_json_bytes

def test_verifier_rejects_hash_and_suffix(tmp_path):
 a=tmp_path/'archive'; (a/'months').mkdir(parents=True)
 p=a/'months/2026-09.aaaaaaaaaaaa.json'; payload=canonical_json_bytes({'schemaVersion':'screening-history-month-v1','month':'2026-09','records':[]}); p.write_bytes(payload)
 (a/'index.json').write_text(json.dumps({'schemaVersion':'screening-history-index-v1','months':[{'month':'2026-09','path':'/data/archive/v1/months/'+p.name,'sha256':'0'*64}] }))
 assert verify_archive(a)
