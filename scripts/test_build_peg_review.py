import json

import pytest

from scripts.build_peg_review import build_review


def fixture(tmp_path):
    data = tmp_path / 'data'
    details = data / 'releases/new-run/stocks'
    details.mkdir(parents=True)
    stocks = [{'code': f'{i:04d}'} for i in range(100)]
    (data / 'latest.json').write_text(json.dumps({'marketDate': '2026-11-03', 'runId': 'new-run', 'stocks': stocks}))
    (data / 'screening-export.json').write_text(json.dumps({'marketDate': '2026-11-03', 'runId': 'new-run', 'requestId': 'req-1', 'actionsRunId': '456', 'sourceGitCommit': 'a' * 40}))
    (data / 'peg-review.json').write_text(json.dumps({'runId': 'old-run', 'prepareRunId': 'stale'}))
    for row in stocks:
        (details / (row['code'] + '.json')).write_text(json.dumps({**row, 'name': 'test', 'pegReview': {'status': 'needs_review', 'reasonCodes': ['missing_evidence']}}))
    return data


def test_review_replaces_old_proof_using_current_export_and_all_details(tmp_path):
    data = fixture(tmp_path)
    result = build_review(data, '2026-11-03', 'req-1', 'a' * 40, '456')
    assert result['runId'] == 'new-run'
    assert result['actionsRunId'] == '456'
    assert result['counts'] == {'needs_review': 100}
    assert 'prepareRunId' not in result
    assert json.loads((data / 'peg-review.json').read_text()) == result


def test_review_checks_manifest_lineage_and_exact_export(tmp_path):
    data = fixture(tmp_path)
    lineage = {'marketDate': '2026-11-03', 'requestId': 'req-1', 'prepareRunId': '123', 'prepareRunAttempt': 1, 'candidateSha256': 'b' * 64}
    result = build_review(data, '2026-11-03', 'req-1', 'a' * 40, '456', manifest=lineage, prepare_run='123', prepare_attempt='1', candidate_sha256='b' * 64)
    assert result['prepareRunId'] == '123'
    with pytest.raises(ValueError, match='lineage'):
        build_review(data, '2026-11-03', 'req-1', 'a' * 40, '456', manifest=lineage, prepare_run='124', prepare_attempt='1', candidate_sha256='b' * 64)
    with pytest.raises(ValueError, match='export'):
        build_review(data, '2026-11-03', 'wrong', 'a' * 40, '456')


def test_workflow_builds_current_proof_after_export_for_all_publication_modes():
    workflow = ( __import__('pathlib').Path(__file__).resolve().parents[1] / '.github/workflows/daily.yml').read_text()
    export = workflow.index('- name: Build canonical screening export')
    builder = workflow.index('- name: Build PEG review for final release')
    publish = workflow.index('- name: Publish validated release to main')
    assert export < builder < publish
    block = workflow[builder:workflow.index('- uses: actions/upload-artifact@v7', builder)]
    assert "if: inputs.source_mode != 'prepare_peg'" in block
    assert 'scripts/build_peg_review.py' in block
    assert 'if [ "$SOURCE_MODE" = finalize_peg ]' in block


def test_review_accepts_extended_taiwan_codes_and_rejects_invalid_status(tmp_path):
    data = fixture(tmp_path)
    latest_path = data / 'latest.json'
    latest = json.loads(latest_path.read_text())
    for old, new in [('0000', '123456'), ('0001', '1234A')]:
        next(row for row in latest['stocks'] if row['code'] == old)['code'] = new
        old_path = data / 'releases/new-run/stocks' / (old + '.json')
        detail = json.loads(old_path.read_text())
        detail['code'] = new
        (old_path.parent / (new + '.json')).write_text(json.dumps(detail))
        old_path.unlink()
    latest_path.write_text(json.dumps(latest))
    proof = build_review(data, '2026-11-03', 'req-1', 'a' * 40, '456')
    assert {'123456', '1234A'} <= {row['code'] for row in proof['stocks']}
    path = data / 'releases/new-run/stocks/1234A.json'
    detail = json.loads(path.read_text())
    detail['pegReview']['status'] = 'unknown_status'
    path.write_text(json.dumps(detail))
    with pytest.raises(ValueError, match='review detail'):
        build_review(data, '2026-11-03', 'req-1', 'a' * 40, '456')
