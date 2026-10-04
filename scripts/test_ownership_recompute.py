import copy
import json
from pathlib import Path
import pytest
from scripts import refresh_snapshot as module
from scripts.verify_snapshot import compute_input_hash


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def baseline(tmp_path):
    detail = {'code': '2547', 'asOf': '2026-10-02', 'priceSeries': [{'date': '2026-10-02', 'close': 10}], 'financials': {'eps': 4}, 'growthHealth': {'status': 'pass'}, 'institutionalDaily': [{'net': 7}], 'chipReference': {'old': True}}
    release = {'runId': 'original', 'marketDate': '2026-10-02', 'generatedAt': '2026-10-02T10:00:00+00:00', 'inputCodes': ['2547'], 'stocks': [{'code': '2547', 'chipReference': {'old': True}, 'peg': 2}], 'rankings': {'trust': [{'code': '2547', 'rank': 1, 'chipReference': {'old': True}}]}, 'funnel': {'count': 1}, 'coverage': {'count': 1}, 'marketIndicators': {'volume': 5}, 'sourceRefs': ['old']}
    write(tmp_path / 'latest.json', release)
    write(tmp_path / 'releases/original/stocks/2547.json', detail)
    write(tmp_path / 'releases/original/manifest.json', {**release, 'formulaVersions': module.FORMULA_VERSIONS})
    return release, detail


def cache(tmp_path):
    rows = [{'code': '2547', 'period': f'2026-{month}', 'asOf': f'2026-{month}-28', 'largeHolderPct': pct, 'shareholderCount': count, 'sourceRefs': ['TDCC:history']} for month, pct, count in [('07', 10, 30), ('08', 11, 29), ('09', 12, 28), ('10', 1, 100)]]
    path = tmp_path / 'ownership.json'
    write(path, {'schemaVersion': module.OWNERSHIP_SNAPSHOT_VERSION, 'status': 'current', 'rows': rows})
    return path


def test_recompute_preserves_strategy_and_detail_fields_and_hashes(tmp_path, monkeypatch):
    release, detail = baseline(tmp_path)
    path = cache(tmp_path)
    for name in ['build_release', 'enrich_detail', 'build_health_inputs', 'fetch_adjusted_history']:
        monkeypatch.setattr(module, name, lambda *a, **k: pytest.fail('network/financial recompute forbidden'))
    result = module.recompute_ownership_release(tmp_path, as_of='2026-10-02', ownership_snapshot=path)
    current = module.load_json(tmp_path / 'latest.json')
    changed_detail = module.load_json(tmp_path / 'releases' / result['run_id'] / 'stocks/2547.json')
    for key in ['funnel', 'coverage', 'marketIndicators', 'sourceRefs']:
        assert current[key] == release[key]
    assert changed_detail['chipReference']['largeHolderTrend']['rawValues'] == [10, 11, 12]
    assert current['rankings']['trust'][0]['chipReference'] == changed_detail['chipReference']
    for key in detail.keys() - {'chipReference'}:
        assert changed_detail[key] == detail[key]
    manifest = module.load_json(tmp_path / 'releases' / result['run_id'] / 'manifest.json')
    assert manifest['inputHash'] == compute_input_hash(manifest, current, [changed_detail])
    assert module.load_json(tmp_path / 'releases/original/stocks/2547.json') == detail


@pytest.mark.parametrize('kind', ['missing', 'malformed', 'schema', 'empty'])
def test_missing_cache_preserves_display_evidence(tmp_path, kind):
    release, detail = baseline(tmp_path)
    path = tmp_path / 'missing.json'
    if kind == 'malformed': path.write_text('{')
    if kind == 'schema': write(path, {'schemaVersion': 'bad', 'rows': []})
    if kind == 'empty': write(path, {'schemaVersion': module.OWNERSHIP_SNAPSHOT_VERSION, 'rows': []})
    result = module.recompute_ownership_release(tmp_path, as_of='2026-10-02', ownership_snapshot=path)
    assert result['run_id'] == 'original'
    assert module.load_json(tmp_path / 'latest.json') == release


@pytest.mark.parametrize('kind', ['date', 'detail', 'code', 'manifest'])
def test_incomplete_or_wrong_date_rejected_without_writes(tmp_path, kind):
    release, detail = baseline(tmp_path)
    path = cache(tmp_path)
    if kind == 'detail': (tmp_path / 'releases/original/stocks/2547.json').unlink()
    if kind == 'manifest': write(tmp_path / 'releases/original/manifest.json', {'runId': 'wrong'})
    if kind == 'code': write(tmp_path / 'releases/original/stocks/2547.json', {'code': 'wrong'})
    with pytest.raises(ValueError):
        module.recompute_ownership_release(tmp_path, as_of='2026-10-01' if kind == 'date' else '2026-10-02', ownership_snapshot=path)
    assert module.load_json(tmp_path / 'latest.json') == release


def test_chip_loader_uses_explicit_release_cutoff(tmp_path):
    path = cache(tmp_path)
    chips, _, _ = module.load_ownership_chips(path, ['2547'], offline=False, evaluation_date='2026-10-02')
    assert chips['2547']['largeHolderTrend']['rawValues'] == [10, 11, 12]


@pytest.mark.parametrize('kind', ['missing', 'malformed', 'schema'])
def test_loader_invalid_cache_unavailable(tmp_path, kind):
    path = tmp_path / 'invalid.json'
    if kind == 'malformed': path.write_text('{')
    if kind == 'schema': write(path, {'schemaVersion': 'bad', 'rows': []})
    chips, status, refs = module.load_ownership_chips(path, ['2547'], offline=False, evaluation_date='2026-10-02')
    assert status == 'unavailable'
    assert chips['2547']['status'] == 'unknown'
    assert refs == []


def test_current_week_cache_only_does_not_imply_three_month_coverage(tmp_path):
    baseline(tmp_path)
    path = tmp_path / 'future.json'
    write(path, {'schemaVersion': module.OWNERSHIP_SNAPSHOT_VERSION, 'rows': [{'code': '2547', 'period': '2026-11', 'asOf': '2026-11-30'}]})
    assert module.recompute_ownership_release(tmp_path, as_of='2026-10-02', ownership_snapshot=path)['ownership_updated'] is False


def test_guard_fails_before_publishing(tmp_path, monkeypatch):
    baseline(tmp_path)
    path = cache(tmp_path)
    project = module._chip_projection
    def detect_changed_detail(value):
        result = project(value)
        if isinstance(value, dict) and 'ownershipMonthly' in value:
            result['financials'] = 'bad'
        return result
    monkeypatch.setattr(module, '_chip_projection', detect_changed_detail)
    with pytest.raises(ValueError, match='non-chip'):
        module.recompute_ownership_release(tmp_path, as_of='2026-10-02', ownership_snapshot=path)
    assert module.load_json(tmp_path / 'latest.json')['runId'] == 'original'
