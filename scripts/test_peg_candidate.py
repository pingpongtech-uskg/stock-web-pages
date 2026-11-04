import json
from pathlib import Path

import pytest

from scripts.peg_candidate import create, restore


def fixture(root):
    data = root / 'public/data'
    data.mkdir(parents=True)
    stocks = [{'code': f'{i:04d}', 'name': f'Stock {i}'} for i in range(100)]
    (data / 'latest.json').write_text(json.dumps({'marketDate': '2026-11-03', 'runId': 'release', 'stocks': stocks}))
    details = data / 'releases/release/stocks'
    details.mkdir(parents=True)
    for row in stocks:
        (details / (row['code'] + '.json')).write_text(json.dumps({**row, 'pegReview': {'status': 'needs_review'}, 'currentPeriod': '2026-Q3'}))
    config = {'stale': False, 'symbols': [r['code'] for r in stocks],
              'metadata': {r['code']: {'name': r['name']} for r in stocks},
              'universe': {'marketDates': ['2026-11-03'], 'rows': [{'code': r['code']} for r in stocks]}}
    (root / 'config').mkdir(parents=True)
    (root / 'config/tracked_symbols.json').write_text(json.dumps(config))
    (data / 'institutional_universe.json').write_text(json.dumps(config))
    return data


def test_candidate_round_trip_and_identity(tmp_path):
    fixture(tmp_path)
    artifact = tmp_path / 'artifact'
    preview = create(tmp_path, artifact, 'req-1', '2026-11-03', '123', '1', 'a' * 40)
    assert len(preview['stocks']) == 100
    assert preview['stocks'][0]['currentPeriod'] == '2026-Q3'
    target = tmp_path / 'target'
    restore(target, artifact, 'req-1', '2026-11-03', '123', '1', preview['candidateSha256'])
    assert json.loads((target / 'public/data/latest.json').read_text())['runId'] == 'release'
    with pytest.raises(ValueError, match='identity'):
        restore(target, artifact, 'other', '2026-11-03', '123', '1', preview['candidateSha256'])
    with pytest.raises(ValueError, match='digest'):
        restore(target, artifact, 'req-1', '2026-11-03', '123', '1', '0' * 64)


def test_workflow_separates_preparation_from_publication():
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/daily.yml').read_text()
    prepare = workflow.split('- name: Freeze new candidate and preview for PEG discovery', 1)[1].split('- uses: actions/download-artifact', 1)[0]
    assert "if: inputs.source_mode == 'prepare_peg'" in prepare
    assert 'compression-level: 0' in prepare
    restore = workflow.split('- name: Restore exact candidate and correlated search manifest', 1)[1].split('- name: Apply fresh PEG evidence', 1)[0]
    for key in ('requestId', 'marketDate', 'prepareRunId', 'prepareRunAttempt', 'candidateSha256'):
        assert key in restore
    publication = workflow.split('- name: Publish validated release to main', 1)[1].split('- uses: actions/upload-artifact', 1)[0]
    assert "if: inputs.source_mode != 'prepare_peg'" in publication
    assert 'scripts/publish_validated_release.sh' in publication


def test_prepare_run_provenance_rejects_foreign_or_wrong_run():
    from scripts.peg_candidate import validate_prepare_run
    preview = {'requestId': 'req-1', 'marketDate': '2026-11-03', 'prepareRunId': '123', 'prepareRunAttempt': 1, 'sourceGitCommit': 'a' * 40}
    run = {'id': 123, 'run_attempt': 1, 'head_sha': 'a' * 40, 'head_branch': 'main', 'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'success', 'display_title': 'Daily PEG prepare | req-1 | 2026-11-03', 'path': '.github/workflows/daily.yml', 'repository': {'full_name': 'org/repo'}}
    validate_prepare_run(preview, run, 'org/repo')
    with pytest.raises(ValueError, match='provenance'):
        validate_prepare_run(preview, {**run, 'head_sha': 'b' * 40}, 'org/repo')
    with pytest.raises(ValueError, match='provenance'):
        validate_prepare_run(preview, {**run, 'repository': {'full_name': 'evil/repo'}}, 'org/repo')


def test_restore_rejects_traversal_and_symlinks(tmp_path):
    import hashlib
    import io
    import tarfile
    artifact = tmp_path / 'artifact'
    artifact.mkdir()
    preview = {'requestId': 'req-1', 'marketDate': '2026-11-03', 'prepareRunId': '123', 'prepareRunAttempt': 1}
    for name, kind in [('public/data/../../escape', 'file'), ('public/data/link', 'link')]:
        archive = artifact / 'candidate.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            info = tarfile.TarInfo(name)
            if kind == 'link':
                info.type = tarfile.SYMTYPE
                info.linkname = '../../outside'
                tar.addfile(info)
            else:
                info.size = 1
                tar.addfile(info, io.BytesIO(b'x'))
        expected = hashlib.sha256(archive.read_bytes()).hexdigest()
        (artifact / 'preview.json').write_text(json.dumps({**preview, 'candidateSha256': expected}))
        with pytest.raises(ValueError, match='unsafe'):
            restore(tmp_path / 'target', artifact, 'req-1', '2026-11-03', '123', '1', expected)


def test_candidate_freezes_matching_new_roster_and_metadata(tmp_path):
    fixture(tmp_path)
    artifact = tmp_path / 'artifact'
    preview = create(tmp_path, artifact, 'req-1', '2026-11-03', '123', '1', 'a' * 40)
    target = tmp_path / 'target'
    (target / 'config').mkdir(parents=True)
    (target / 'config/tracked_symbols.json').write_text(json.dumps({'symbols': ['OLD']}))
    restore(target, artifact, 'req-1', '2026-11-03', '123', '1', preview['candidateSha256'])
    config = json.loads((target / 'config/tracked_symbols.json').read_text())
    assert len(config['symbols']) == 100
    assert config['symbols'][0] == '0000'
    assert config['metadata']['0000']['name'] == 'Stock 0'
    assert config == json.loads((target / 'public/data/institutional_universe.json').read_text())


def test_candidate_rejects_mismatched_roster_metadata(tmp_path):
    fixture(tmp_path)
    config_path = tmp_path / 'config/tracked_symbols.json'
    config = json.loads(config_path.read_text())
    del config['metadata']['0000']
    config_path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match='universe'):
        create(tmp_path, tmp_path / 'artifact', 'req-1', '2026-11-03', '123', '1', 'a' * 40)


def test_candidate_rejects_preview_over_checkpoint_limit(tmp_path):
    fixture(tmp_path)
    path = tmp_path / 'public/data/releases/release/stocks/0000.json'
    detail = json.loads(path.read_text())
    detail['name'] = 'x' * (256 * 1024)
    path.write_text(json.dumps(detail))
    with pytest.raises(ValueError, match='preview exceeds'):
        create(tmp_path, tmp_path / 'artifact', 'req-1', '2026-11-03', '123', '1', 'a' * 40)
