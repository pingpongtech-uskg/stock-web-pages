import base64
import copy
import hashlib
import json
import pytest
from pipeline.market_cache import validate_ownership_bundle, MarketCacheError


def bundle():
    from pipeline.ownership_queue import new_state
    documents = {'snapshot.json': {'schemaVersion': 'ownership-snapshot-v1', 'verifiedMarketDate': '2026-10-02', 'rows': []}, 'queue.json': new_state(['2547'], ['2547'], '2026-10-02')}
    files = {key: json.dumps(value, ensure_ascii=False, sort_keys=True).encode() for key, value in documents.items()}
    binding = {'verifiedMarketDate': '2026-10-02', 'sourceGitCommit': 'a'*40, 'requestId': 'test:one', 'actionsRunId': '1', 'actionsRunAttempt': '1', 'previousGeneration': None, 'rosterHash': hashlib.sha256(json.dumps(['2547'], separators=(',', ':')).encode()).hexdigest(), 'targetMonths': ['2026-07', '2026-08', '2026-09'], 'formulaVersion': 'chip-reference-v1', 'priorityRosterMarketDate': None, 'priorityRosterPublicationHash': None}
    generation = hashlib.sha256(json.dumps({'binding': binding, 'queueHash': hashlib.sha256(files['queue.json']).hexdigest()}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    documents['snapshot.json']['generationId'] = generation
    files['snapshot.json'] = json.dumps(documents['snapshot.json']).encode()
    manifest = {'schemaVersion': 'ownership-generation-v1', 'generationId': generation, **binding, 'files': [{'path': key, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)} for key, raw in files.items()]}
    files['manifest.json'] = json.dumps(manifest).encode()
    return {'schemaVersion': 'ownership-bundle-v1', 'generationCommit': 'b'*40, 'manifestSha256': hashlib.sha256(files['manifest.json']).hexdigest(), 'filesBase64': {key: base64.b64encode(raw).decode() for key, raw in files.items()}}


def test_ownership_bundle_hashes_bind_exact_bytes():
    assert validate_ownership_bundle(bundle(), '2026-10-02')['generationCommit'] == 'b'*40
    value = bundle(); value['filesBase64']['queue.json'] = base64.b64encode(b'{}').decode()
    with pytest.raises(MarketCacheError): validate_ownership_bundle(value, '2026-10-02')

@pytest.mark.parametrize('mutation', ['traversal', 'future', 'manifest', 'generation', 'unknown'])
def test_ownership_bundle_rejects_unsafe_or_unbound_state(mutation):
    value = bundle()
    if mutation == 'traversal': value['filesBase64']['../evil'] = 'e30='
    if mutation == 'future':
        with pytest.raises(MarketCacheError): validate_ownership_bundle(value, '2026-10-01')
        return
    if mutation == 'manifest': value['manifestSha256'] = '0'*64
    if mutation == 'generation': value['generationCommit'] = 'main'
    if mutation == 'unknown': value['extra'] = True
    with pytest.raises(MarketCacheError): validate_ownership_bundle(value, '2026-10-02')


def test_javascript_semantic_verifier_matches_python(tmp_path):
    import subprocess
    from pathlib import Path
    validator = Path(__file__).resolve().parents[1] / 'scripts/n8n/market-cache.cjs'
    values = [bundle(), bundle()]
    values[1]['filesBase64']['queue.json'] = base64.b64encode(b'{}').decode()
    code = "const v = require(process.argv[1]);const values=JSON.parse(require('fs').readFileSync(0,'utf8')); console.log(JSON.stringify(values.map(b=>{try{v.validateOwnershipBundle(b,'2026-10-02');return true;}catch{return false;}})));"
    result = subprocess.run(['node', '-e', code, str(validator)], input=json.dumps(values), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == [True, False]


def test_receipt_bundle_sanitization_and_exact_byte_roundtrip(tmp_path):
    from pipeline.ownership_queue import new_state, save_state, save_receipt
    from scripts.update_ownership_checkpoint import build_manifest
    state = new_state(['2547'], ['2547'], '2026-10-02')
    receipt = save_receipt(tmp_path / 'receipts', b'<input name="SYNCHRONIZER_TOKEN" value="private">published official data', source='TDCC', url='https://www.tdcc.com.tw/portal/zh/smWeb/qryStock', parameters={}, retrieved_at='2026-10-04T00:00:00Z', source_date='2026-09-25', rows=[])
    state = {**state, 'receipts': [receipt]}
    save_state(tmp_path, state)
    (tmp_path / 'snapshot.json').write_text(json.dumps({'schemaVersion': 'ownership-snapshot-v1', 'verifiedMarketDate': '2026-10-02', 'rows': []}))
    manifest = build_manifest(tmp_path, tmp_path / 'snapshot.json', 'a'*40, request_id='test', actions_run_id='1', actions_run_attempt='1')
    names = ['manifest.json', *(item['path'] for item in manifest['files'])]
    value = {'schemaVersion': 'ownership-bundle-v1', 'generationCommit': 'b'*40, 'manifestSha256': hashlib.sha256((tmp_path / 'manifest.json').read_bytes()).hexdigest(), 'filesBase64': {name: base64.b64encode((tmp_path / name).read_bytes()).decode() for name in names}}
    checked = validate_ownership_bundle(value, '2026-10-05')
    assert checked['decodedFiles']['receipts/' + receipt['rawFile']] == b'published official data'
    assert receipt['originalResponseSha256'] != receipt['rawSha256']
    assert all(checked['decodedFiles'][name] == (tmp_path / name).read_bytes() for name in names)


def test_semantic_generation_rejects_rehashed_changed_queue():
    value = bundle()
    files = {name: base64.b64decode(raw) for name, raw in value['filesBase64'].items()}
    queue = json.loads(files['queue.json']); queue['roster'] = ['3005']
    files['queue.json'] = json.dumps(queue).encode()
    manifest = json.loads(files['manifest.json'])
    for item in manifest['files']:
        if item['path'] == 'queue.json': item.update(sha256=hashlib.sha256(files['queue.json']).hexdigest(), size=len(files['queue.json']))
    files['manifest.json'] = json.dumps(manifest).encode()
    value.update(manifestSha256=hashlib.sha256(files['manifest.json']).hexdigest(), filesBase64={name: base64.b64encode(raw).decode() for name, raw in files.items()})
    with pytest.raises(MarketCacheError, match='ownership_generation_hash'): validate_ownership_bundle(value, '2026-10-02')


@pytest.mark.parametrize('field', ['future', 'origin', 'unbound'])
def test_self_consistent_rehashed_unproven_rows_rejected_python_and_javascript(tmp_path, field):
    import subprocess
    from pathlib import Path
    from pipeline.ownership_queue import new_state, save_state
    from scripts.update_ownership_checkpoint import build_manifest
    row = {'code': '2547', 'period': '2026-09', 'asOf': '2026-09-25', 'sourceURL': 'https://www.tdcc.com.tw/portal/zh/smWeb/qryStock', 'rawSha256': 'd'*64, 'rawReceiptPath': 'receipts/' + 'e'*64 + '.json'}
    if field == 'future': row.update(period='2027-12', asOf='2027-12-31')
    if field == 'origin': row['sourceURL'] = 'https://attacker.invalid/'
    state = {**new_state(['2547'], ['2547'], '2026-10-02'), 'rows': [row]}
    save_state(tmp_path, state)
    (tmp_path / 'snapshot.json').write_text(json.dumps({'schemaVersion': 'ownership-snapshot-v1', 'verifiedMarketDate': '2026-10-02', 'rows': [row]}))
    manifest = build_manifest(tmp_path, tmp_path / 'snapshot.json', 'a'*40, request_id='test', actions_run_id='1', actions_run_attempt='1')
    names = ['manifest.json', *(item['path'] for item in manifest['files'])]
    value = {'schemaVersion': 'ownership-bundle-v1', 'generationCommit': 'b'*40, 'manifestSha256': hashlib.sha256((tmp_path / 'manifest.json').read_bytes()).hexdigest(), 'filesBase64': {name: base64.b64encode((tmp_path / name).read_bytes()).decode() for name in names}}
    with pytest.raises(MarketCacheError): validate_ownership_bundle(value, '2026-10-02')
    code = "const v=require(process.argv[1]);try{v.validateOwnershipBundle(JSON.parse(require('fs').readFileSync(0,'utf8')),'2026-10-02');process.exit(1);}catch{process.exit(0);}"
    validator = Path(__file__).resolve().parents[1] / 'scripts/n8n/market-cache.cjs'
    assert subprocess.run(['node', '-e', code, str(validator)], input=json.dumps(value), text=True).returncode == 0


@pytest.mark.parametrize('change', ['none', 'merged', 'observation', 'nested_future'])
def test_receipt_metric_binding_and_merged_observations(change, tmp_path):
    import subprocess
    from pathlib import Path
    from pipeline.ownership_queue import new_state, save_state, save_receipt
    from scripts.update_ownership_checkpoint import build_manifest
    original = {'code': '2547', 'period': '2026-09', 'asOf': '2026-09-25', 'sourceDate': '2026-09-25', 'largeHolderPct': 12, 'shareholderCount': 100}
    receipt = save_receipt(tmp_path / 'receipts', b'official dataset bytes', source='TDCC_LATEST', url='https://opendata.tdcc.com.tw/getOD.ashx?id=1-5', parameters={'id': '1-5'}, retrieved_at='2026-10-04T00:00:00Z', source_date='2026-09-25', rows=[original])
    observation = {**original, 'rawReceiptPath': 'receipts/' + receipt['receiptFile'], 'rawSha256': receipt['rawSha256'], 'sourceURL': receipt['sourceURL']}
    row = {**observation, 'sourceObservations': [dict(observation)]}
    if change == 'merged': row['largeHolderPct'] = 99
    if change == 'observation': row['largeHolderPct'] = row['sourceObservations'][0]['largeHolderPct'] = 99
    if change == 'nested_future': row['sourceObservations'][0]['publishedAt'] = '2027-12-01'
    state = {**new_state(['2547'], ['2547'], '2026-10-02'), 'rows': [row], 'receipts': [receipt]}
    save_state(tmp_path, state)
    (tmp_path / 'snapshot.json').write_text(json.dumps({'schemaVersion': 'ownership-snapshot-v1', 'verifiedMarketDate': '2026-10-02', 'rows': [row]}))
    manifest = build_manifest(tmp_path, tmp_path / 'snapshot.json', 'a'*40, request_id='test', actions_run_id='1', actions_run_attempt='1')
    names = ['manifest.json', *(item['path'] for item in manifest['files'])]
    value = {'schemaVersion': 'ownership-bundle-v1', 'generationCommit': 'b'*40, 'manifestSha256': hashlib.sha256((tmp_path / 'manifest.json').read_bytes()).hexdigest(), 'filesBase64': {name: base64.b64encode((tmp_path / name).read_bytes()).decode() for name in names}}
    if change == 'none': assert validate_ownership_bundle(value, '2026-10-02')
    else:
        with pytest.raises(MarketCacheError): validate_ownership_bundle(value, '2026-10-02')
    code = "const v=require(process.argv[1]);try{v.validateOwnershipBundle(JSON.parse(require('fs').readFileSync(0,'utf8')),'2026-10-02');process.exit(0);}catch{process.exit(1);}"
    validator = Path(__file__).resolve().parents[1] / 'scripts/n8n/market-cache.cjs'
    result = subprocess.run(['node', '-e', code, str(validator)], input=json.dumps(value), text=True)
    assert (result.returncode == 0) == (change == 'none')


def test_roster_filtered_latest_receipt_bundle(tmp_path):
    from pipeline.ownership_queue import new_state, save_state, save_receipt
    from scripts.update_ownership_checkpoint import build_manifest
    raw = '證券代號,資料日期,持股分級,人數,股數,占集保庫存數比例%\n2547,20260925,15,1,100,12\n9999,20260925,15,1,100,99\n'.encode()
    receipt = save_receipt(tmp_path / 'receipts', raw, source='TDCC_LATEST', url='https://opendata.tdcc.com.tw/getOD.ashx?id=1-5', parameters={'id':'1-5'}, retrieved_at='2026-10-04T00:00:00Z', source_date='2026-09-25', rows=[], selected_codes=['2547'])
    state = {**new_state(['2547'], ['2547'], '2026-10-02'), 'receipts': [receipt]}
    save_state(tmp_path, state)
    (tmp_path / 'snapshot.json').write_text(json.dumps({'schemaVersion': 'ownership-snapshot-v1', 'verifiedMarketDate': '2026-10-02', 'rows': []}))
    manifest = build_manifest(tmp_path, tmp_path / 'snapshot.json', 'a'*40, request_id='test', actions_run_id='1', actions_run_attempt='1')
    names = ['manifest.json', *(item['path'] for item in manifest['files'])]
    value = {'schemaVersion': 'ownership-bundle-v1', 'generationCommit': 'b'*40, 'manifestSha256': hashlib.sha256((tmp_path / 'manifest.json').read_bytes()).hexdigest(), 'filesBase64': {name: base64.b64encode((tmp_path / name).read_bytes()).decode() for name in names}}
    checked = validate_ownership_bundle(value, '2026-10-02')
    stored = checked['decodedFiles']['receipts/' + receipt['rawFile']]
    assert b'9999' not in stored and b'2547' in stored
    assert receipt['originalResponseSha256'] != receipt['rawSha256']
    import subprocess
    from pathlib import Path
    validator = Path(__file__).resolve().parents[1] / 'scripts/n8n/market-cache.cjs'
    script = "require(process.argv[1]).validateOwnershipBundle(JSON.parse(require('fs').readFileSync(0,'utf8')),'2026-10-02')"
    assert subprocess.run(['node', '-e', script, str(validator)], input=json.dumps(value), text=True).returncode == 0
