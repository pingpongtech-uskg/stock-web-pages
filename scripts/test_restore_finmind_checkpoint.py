import io
import json
import zipfile
from scripts.restore_finmind_checkpoint import merge_states, recover_zip


def test_recovery_never_resets_same_day_attempts_ceiling_or_block():
    current = {'days': {'2026-10-02': {'attempts': 280, 'ceiling': 285, 'blocked': '429'}}, 'retryNotBefore': 100}
    old = {'days': {'2026-10-02': {'attempts': 240, 'ceiling': 300}}, 'retryNotBefore': 50}
    merged = merge_states(current, old)
    assert merged['days']['2026-10-02']['attempts'] == 280
    assert merged['days']['2026-10-02']['ceiling'] == 285
    assert merged['days']['2026-10-02']['blocked'] == '429'
    assert merged['retryNotBefore'] == 100


def test_same_day_artifact_checkpoint_restores_and_old_day_does_not(tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('state.json', json.dumps({'version': 1, 'days': {'2026-10-02': {'attempts': 9, 'ceiling': 200}}}))
        archive.writestr('rows.json', json.dumps({'2330:financial': {'checkedAt': '2026-10-02', 'rows': [{'value':1}]}}))
    assert not recover_zip(tmp_path, payload.getvalue(), '2026-10-03')
    assert recover_zip(tmp_path, payload.getvalue(), '2026-10-02')
    assert json.loads((tmp_path/'state.json').read_bytes())['days']['2026-10-02']['attempts'] == 9
    assert json.loads((tmp_path/'rows.json').read_bytes())['2330:financial']['rows'] == [{'value':1}]


def test_restore_main_consumes_artifact_once_and_preserves_more_recent_budget(tmp_path,monkeypatch):
    import scripts.restore_finmind_checkpoint as module
    monkeypatch.setenv('GITHUB_TOKEN','test-token')
    artifact = {'id': 10, 'name':'finmind-checkpoint-1','created_at':'2026-10-02T10:00:00Z','expired':False, 'workflow_run': {'id':1,'head_sha':'a'*40,'head_branch':'main'}}
    def api(path, token):
        if path.endswith('daily.yml'): return {'id': 50}
        if path.endswith('runs/1'): return {'id':1,'head_sha':'a'*40,'head_branch':'main','event':'workflow_dispatch','workflow_id':50,'head_repository':{'full_name':'org/repo'}}
        return {'artifacts':[artifact] if path.endswith('page=1') else []}
    monkeypatch.setattr(module,'_api',api)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('state.json',json.dumps({'version':1,'days':{'2026-10-02':{'attempts':280,'ceiling':300}}}))
    monkeypatch.setattr(module,'_download',lambda path, token: payload.getvalue())
    assert module.main(['--cache-dir',str(tmp_path),'--budget-date','2026-10-02','--repository','org/repo']) == 0
    assert json.loads((tmp_path/'state.json').read_bytes())['days']['2026-10-02']['attempts'] == 280


def test_restore_network_failure_and_missing_auth_fail_closed(tmp_path,monkeypatch):
    import scripts.restore_finmind_checkpoint as module
    monkeypatch.delenv('GITHUB_TOKEN',raising=False)
    args = ['--cache-dir',str(tmp_path),'--budget-date','2026-10-02','--repository','org/repo']
    assert module.main(args) == 1
    monkeypatch.setenv('GITHUB_TOKEN','test-token')
    def failure(path,token): raise OSError('unavailable')
    monkeypatch.setattr(module,'_api',failure)
    assert module.main(args) == 1


def test_untrusted_pr_artifact_never_downloaded(tmp_path,monkeypatch):
    import scripts.restore_finmind_checkpoint as module
    monkeypatch.setenv('GITHUB_TOKEN','test-token')
    artifact={'id':10,'name':'finmind-checkpoint-1','created_at':'2026-10-02T10:00:00Z','expired':False,
              'workflow_run':{'id':1,'head_sha':'a'*40,'head_branch':'main'}}
    def api(path, token):
        if path.endswith('daily.yml'): return {'id':50}
        if path.endswith('runs/1'): return {'id':1,'head_sha':'a'*40,'head_branch':'main','event':'pull_request','workflow_id':50,'head_repository':{'full_name':'fork/repo'}}
        return {'artifacts':[artifact] if path.endswith('page=1') else []}
    monkeypatch.setattr(module,'_api',api)
    def forbidden(*args): raise AssertionError('untrusted artifact downloaded')
    monkeypatch.setattr(module,'_download',forbidden)
    assert module.main(['--cache-dir',str(tmp_path),'--budget-date','2026-10-02','--repository','org/repo']) == 0
    assert not (tmp_path/'state.json').exists()


def test_invalid_state_and_duplicate_zip_names_fail_before_writing(tmp_path):
    import pytest
    for items in [
        [('state.json',{'version':2,'days':{'2026-10-02':{'attempts':'280','ceiling':300}}})],
        [('state.json',{'version':2,'days':{'2026-10-02':{'attempts':301,'ceiling':300}}})],
        [('state.json',{}),('nested/state.json',{})],
        [('../state.json',{})],
        [('state.json',{'version':2,'days':{'2026-10-02':{'attempts':5,'ceiling':300}}}),('rows.json',[])],
    ]:
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as archive:
            for name,value in items: archive.writestr(name,json.dumps(value))
        with pytest.raises(ValueError): recover_zip(tmp_path,raw.getvalue(),'2026-10-02')
        assert not (tmp_path/'state.json').exists()


def test_newer_verified_window_preserved_and_legacy_allowance_migrated():
    import scripts.restore_finmind_checkpoint as module
    old={'version':2,'days':{'2026-10-02':{'attempts':10,'ceiling':300,'accountCeiling':12,'blocked':'429'}}}
    new={'version':2,'days':{'2026-10-02':{'attempts':11,'ceiling':300,'accountCeiling':250,'blocked':None}}}
    assert merge_states(new,old)['days']['2026-10-02']['accountCeiling'] == 250
    assert merge_states(new,old)['days']['2026-10-02']['blocked'] is None
    legacy=module._valid_state({'version':1,'days':{'2026-10-02':{'attempts':10,'ceiling':12,'quotaKnown':True}}})
    assert legacy['days']['2026-10-02']['ceiling'] == 300
    assert legacy['days']['2026-10-02']['accountCeiling'] == 12
