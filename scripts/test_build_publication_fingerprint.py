import hashlib
import importlib
import importlib.util
import json

import pytest


def producer():
    assert importlib.util.find_spec('scripts.build_publication_fingerprint') is not None, 'fingerprint producer missing'
    return importlib.import_module('scripts.build_publication_fingerprint')


def snapshot(**changes):
    return {'marketDate': '2026-10-02', 'runId': 'current-1', 'generatedAt': '2026-10-03T00:15:00+08:00',
            'stocks': [{'code': '2330', 'name': '台積電', 'lastPrice': 100}], **changes}


def raw(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


def test_fingerprint_hashes_exact_latest_bytes_and_exposes_only_publication_identity():
    body = raw(snapshot(privateNotes='must not appear in fingerprint'))
    value = producer().build_fingerprint(body)
    assert value == {'schemaVersion': 'publication-fingerprint-v1', 'marketDate': '2026-10-02',
                     'runId': 'current-1', 'generatedAt': '2026-10-03T00:15:00+08:00',
                     'contentHash': hashlib.sha256(body).hexdigest()}
    assert len(json.dumps(value).encode('utf-8')) < 400


def test_same_day_same_run_correction_changes_hash_but_repeated_bytes_are_stable():
    body = raw(snapshot())
    corrected = raw(snapshot(stocks=[{'code': '2330', 'lastPrice': 101}]))
    original = producer().build_fingerprint(body)
    assert producer().build_fingerprint(body) == original
    revised = producer().build_fingerprint(corrected)
    assert revised['runId'] == original['runId']
    assert revised['marketDate'] == original['marketDate']
    assert revised['contentHash'] != original['contentHash']


@pytest.mark.parametrize('changes', [
    {'marketDate': '20261002'}, {'marketDate': '2026-10-99'}, {'marketDate': None},
    {'runId': ''}, {'runId': '../outside'}, {'runId': 123},
    {'generatedAt': '2026-10-03T00:15:00'}, {'generatedAt': 'bad'}, {'generatedAt': None},
])
def test_invalid_publication_identity_rejected(changes):
    with pytest.raises(ValueError):
        producer().build_fingerprint(raw(snapshot(**changes)))


@pytest.mark.parametrize('body', [b'<html>error</html>', b'[]', b'null', b'{"bad":NaN}', b'\xff'])
def test_malformed_non_json_and_nonfinite_snapshots_rejected(body):
    with pytest.raises(ValueError):
        producer().build_fingerprint(body)


def test_cli_atomic_build_and_check_detect_correction_without_overwriting_old_fingerprint(tmp_path, capsys):
    latest = tmp_path / 'latest.json'
    latest.write_bytes(raw(snapshot()))
    args = ['--data-dir', str(tmp_path), '--market-date', '2026-10-02']
    assert producer().main(args) == 0
    fingerprint = tmp_path / 'publication.json'
    original = fingerprint.read_bytes()
    assert producer().main([*args, '--check']) == 0
    latest.write_bytes(raw(snapshot(stocks=[{'code': '2330', 'lastPrice': 101}])))
    assert producer().main([*args, '--check']) == 1
    assert fingerprint.read_bytes() == original
    assert producer().main(args) == 0
    assert fingerprint.read_bytes() != original
    assert producer().main([*args, '--check']) == 0
    assert not (tmp_path / 'publication.json.tmp').exists()
    assert 'publication_fingerprint_invalid=' in capsys.readouterr().err


def test_cli_wrong_requested_date_and_missing_snapshot_never_create_fingerprint(tmp_path):
    args = ['--data-dir', str(tmp_path), '--market-date', '2026-10-01']
    assert producer().main(args) == 1
    (tmp_path / 'latest.json').write_bytes(raw(snapshot()))
    assert producer().main(args) == 1
    assert not (tmp_path / 'publication.json').exists()


def test_cli_invalid_snapshot_preserves_prior_publication(tmp_path):
    (tmp_path / 'latest.json').write_bytes(raw(snapshot()))
    args = ['--data-dir', str(tmp_path), '--market-date', '2026-10-02']
    assert producer().main(args) == 0
    prior = (tmp_path / 'publication.json').read_bytes()
    (tmp_path / 'latest.json').write_bytes(b'{"bad":NaN}')
    assert producer().main(args) == 1
    assert (tmp_path / 'publication.json').read_bytes() == prior


def test_daily_gate_builds_and_rechecks_exact_snapshot_fingerprint_before_publish():
    from pathlib import Path
    workflow = Path('.github/workflows/daily.yml').read_text()
    strict = workflow.index('python scripts/verify_snapshot.py --require-growth-coverage')
    build = workflow.index('python scripts/build_publication_fingerprint.py --market-date "$MARKET_DATE"')
    check = workflow.index('python scripts/build_publication_fingerprint.py --check --market-date "$MARKET_DATE"')
    publish = workflow.index('git add config/tracked_symbols.json public/data')
    assert strict < build < check < publish
    headers = Path('public/_headers').read_text()
    assert '/data/publication.json\n  Cache-Control: no-cache, no-store, must-revalidate' in headers


def test_supplement_exposes_only_token_presence_for_authorized_runtime_verification():
    from pathlib import Path
    workflow = Path('.github/workflows/daily.yml').read_text()
    assert 'if [ -n "${FINMIND_TOKEN:-}" ]; then' in workflow
    assert 'echo "finmind_token_present=true"' in workflow
    assert 'echo "finmind_token_present=false"' in workflow
    assert 'echo "$FINMIND_TOKEN"' not in workflow
