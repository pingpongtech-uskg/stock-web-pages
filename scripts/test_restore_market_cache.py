"""Runner boundary: no credentials copied, safe pinned data-only Git tree."""
import json
from pathlib import Path

import pytest
from pipeline.market_cache import canonical, sha, MarketCacheError
from pipeline.test_market_cache_restore import restore_fixture


def arguments(backup, trust, tmp_path):
    return ['--directory', str(backup), '--descriptor-sha256', trust['descriptor_sha256'],
            '--cache-market-date', trust['market_date'], '--market-date', '2026-10-03',
            '--source-git-commit', trust['source']['sourceGitCommit'], '--actions-run-id', trust['source']['actionsRunId'],
            '--request-id', trust['source']['requestId'], '--source-cache-dir', str(tmp_path / 'out'),
            '--stock-cache-dir', str(tmp_path / 'stocks')]


def test_local_runner_prints_sanitized_restore_proof(tmp_path, capsys):
    from scripts.restore_market_cache import main
    backup, trust, *_ = restore_fixture(tmp_path)
    assert main(arguments(backup, trust, tmp_path)) == 0
    proof = json.loads(capsys.readouterr().out)
    assert proof['restoreUsable'] is True
    assert 'sourceUrl' not in proof and 'token' not in proof


def test_runner_failure_never_echoes_input_or_secret(tmp_path, capsys, monkeypatch):
    from scripts.restore_market_cache import main
    backup, trust, *_ = restore_fixture(tmp_path)
    monkeypatch.setenv('GITHUB_TOKEN', 'do-not-print-secret')
    args = arguments(backup, {**trust, 'descriptor_sha256': '0'*64}, tmp_path)
    assert main(args) == 1
    output = capsys.readouterr()
    assert output.err.strip() == 'market_cache_restore_unavailable'
    assert output.out == ''


def test_git_fetch_validates_exact_flat_tree_and_blob_identity(tmp_path):
    from scripts.restore_market_cache import fetch_restore_commit
    import base64, hashlib
    backup, trust, *_ = restore_fixture(tmp_path)
    files = {path.name: path.read_bytes() for path in backup.iterdir()}
    blob_id = lambda raw: hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    tree = [{'path':name,'mode':'100644','type':'blob','sha':blob_id(raw),'size':len(raw)} for name,raw in files.items()]
    by_sha = {blob_id(raw):raw for raw in files.values()}
    calls = []
    def get(path, limit):
        calls.append(path)
        if path == '/git/commits/'+'b'*40: return {'sha':'b'*40,'tree':{'sha':'c'*40}}
        if path == '/git/trees/'+'c'*40: return {'sha':'c'*40,'truncated':False,'tree':tree}
        raw=by_sha[path.rsplit('/',1)[1]]
        return {'sha':blob_id(raw),'encoding':'base64','size':len(raw),'content':base64.b64encode(raw).decode()}
    fetched = fetch_restore_commit('b'*40,tmp_path/'fetched',trust=trust,get=get)
    assert {path.name:path.read_bytes() for path in fetched.iterdir()} == files
    assert len(calls) == len(files)+2


@pytest.mark.parametrize('bad', ['symlink','directory','executable','traversal','oversize','extra','truncated'])
def test_git_fetch_rejects_unsafe_tree_before_blob_requests(tmp_path, bad):
    from scripts.restore_market_cache import fetch_restore_commit
    calls=[]
    item={'path':'restore.json','mode':'100644','type':'blob','sha':'d'*40,'size':10}
    if bad=='symlink': item['mode']='120000'
    elif bad=='directory': item['type']='tree'
    elif bad=='executable': item['mode']='100755'
    elif bad=='traversal': item['path']='../restore.json'
    elif bad=='oversize': item['size']=2**40
    elif bad=='extra': item['path']='script.py'
    def get(path, limit):
        calls.append(path)
        if '/commits/' in path:return {'sha':'b'*40,'tree':{'sha':'c'*40}}
        others = [{'path': name, 'mode': '100644', 'type': 'blob', 'sha': 'e'*40, 'size': 10}
                  for name in ['manifest.json', 'proof.json', 'expected.json', 'safe.json.gz']]
        return {'sha': 'c'*40, 'truncated': bad == 'truncated', 'tree': [item, *others]}
    category = 'cache_restore_tree_size' if bad == 'oversize' else 'cache_restore_tree'
    with pytest.raises(MarketCacheError, match='^' + category + '$'):
        fetch_restore_commit('b'*40,tmp_path/'fetched',trust={'descriptor_sha256':'a'*64,'market_date':'2026-10-02','source':{}},get=get)
    assert len(calls)==2


def test_github_transport_is_origin_pinned_bounded_and_no_redirect(monkeypatch):
    from scripts.restore_market_cache import github_get, NoRedirect
    calls=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self,size):calls.append(('read',size));return b'{}'
    class Opener:
        def open(self,request,timeout):
            calls.append((request.full_url,request.get_header('Authorization'),timeout));return Response()
    monkeypatch.setenv('GITHUB_TOKEN','sensitive-test-value')
    monkeypatch.setattr('scripts.restore_market_cache.build_opener',lambda handler:Opener())
    assert github_get('/git/blobs/'+'a'*40,100)=={}
    assert calls==[('https://api.github.com/repos/pingpongtech-uskg/stock-web-pages/git/blobs/'+'a'*40,'Bearer sensitive-test-value',30),('read',101)]
    with pytest.raises(MarketCacheError):github_get('https://malicious.example',100)
    with pytest.raises(MarketCacheError):NoRedirect().redirect_request(None,None,302,'',{},'https://malicious.example')


def test_blob_digest_mismatch_and_invalid_base64_fail_closed():
    from scripts.restore_market_cache import _blob
    item={'sha':'a'*40,'size':1}
    for content in ['eA==','!invalid']:
        with pytest.raises(MarketCacheError):
            _blob(item,lambda path,limit:{'sha':'a'*40,'size':1,'encoding':'base64','content':content})


def test_explicit_ownership_restore_preserves_exact_producer_bytes(tmp_path, monkeypatch):
    import base64
    from pipeline.ownership_queue import new_state, save_state
    from scripts.update_ownership_checkpoint import build_manifest
    import scripts.restore_market_cache as tool
    import pipeline.market_cache_restore as restore
    state_dir = tmp_path / 'producer'; state_dir.mkdir()
    save_state(state_dir, new_state(['2547'], ['2547'], '2026-10-02'))
    (state_dir / 'snapshot.json').write_text(json.dumps({'schemaVersion': 'ownership-snapshot-v1', 'verifiedMarketDate': '2026-10-02', 'rows': []}))
    manifest = build_manifest(state_dir, state_dir / 'snapshot.json', 'a'*40, request_id='test', actions_run_id='1', actions_run_attempt='1')
    names = ['manifest.json', *(item['path'] for item in manifest['files'])]
    raw = {name: (state_dir / name).read_bytes() for name in names}
    bundle = {'schemaVersion': 'ownership-bundle-v1', 'generationCommit': 'b'*40, 'manifestSha256': sha(raw['manifest.json']), 'filesBase64': {name: base64.b64encode(value).decode() for name, value in raw.items()}}
    monkeypatch.setattr(tool, '_descriptor', lambda *args: {})
    monkeypatch.setattr(restore, '_load', lambda *args: ([{'kind': 'published_stock_inputs', 'body': {'rows': [], 'ownershipBundle': bundle}}], {}, {}))
    trust = {'descriptor_sha256': 'c'*64, 'market_date': '2026-10-02', 'source': {}}
    output = tmp_path / 'restored'
    proof = tool.restore_ownership_bundle(tmp_path, trust=trust, target_market_date='2026-10-05', output=output)
    assert proof['ownershipBackupComplete'] and proof['ownershipStateRestored']
    assert all((output / name).read_bytes() == value for name, value in raw.items())
    with pytest.raises(MarketCacheError): tool.restore_ownership_bundle(tmp_path, trust=trust, target_market_date='2026-10-05', output=output)


def test_legacy_cache_never_claims_ownership_backup(tmp_path, monkeypatch):
    import scripts.restore_market_cache as tool
    import pipeline.market_cache_restore as restore
    monkeypatch.setattr(tool, '_descriptor', lambda *args: {})
    monkeypatch.setattr(restore, '_load', lambda *args: ([{'kind': 'published_stock_inputs', 'body': {'rows': []}}], {}, {}))
    proof = tool.restore_ownership_bundle(tmp_path, trust={'descriptor_sha256': '', 'market_date': '', 'source': {}}, target_market_date='2026-10-05', output=tmp_path / 'out')
    assert proof == {'ownershipBackupComplete': False, 'ownershipStateRestored': False}
    assert not (tmp_path / 'out').exists()
