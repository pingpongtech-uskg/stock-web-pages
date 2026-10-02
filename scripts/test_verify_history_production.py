import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.history_archive import project_release_to_history, write_archive_atomic
from pipeline.history_archive import project_export_to_history
from pipeline.screening_export import build_export, export_bytes
from scripts import verify_history_production as production
from scripts.build_publication_fingerprint import build_fingerprint


INDEX_HEADERS = {'cache-control': 'no-cache, no-store, must-revalidate'}
OBJECT_HEADERS = {'cache-control': 'public, max-age=31536000, immutable'}


@pytest.fixture
def candidate(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    releases = [
        {'marketDate': day, 'runId': 'run-' + day, 'generatedAt': day + 'T10:00:00Z',
         'freshness': 'current', 'rankings': {}}
        for day in ['2026-09-18', '2026-10-01', '2026-10-02']
    ]
    records = [project_release_to_history(release) for release in releases]
    write_archive_atomic(tmp_path / 'staging', data / 'archive/v1',
                         {'2026-09': records[:1], '2026-10': records[1:]},
                         '2026-10-02T10:00:00Z')
    (data / 'latest.json').write_text(json.dumps(releases[-1]), encoding='utf-8')
    return data


def served_candidate(data):
    responses = {}
    for path in data.rglob('*.json'):
        public_path = '/data/' + str(path.relative_to(data))
        raw = path.read_bytes()
        headers = INDEX_HEADERS if path.name in ['latest.json', 'index.json', 'publication.json'] else OBJECT_HEADERS
        responses[public_path] = (json.loads(raw), headers, raw)
    return responses


def test_production_rejects_corrupted_older_month(candidate):
    responses = served_candidate(candidate)
    index = responses['/data/archive/v1/index.json'][0]
    path = min(index['months'], key=lambda month: month['month'])['path']
    value, headers, raw = responses[path]
    altered = {**value, 'records': []}
    responses[path] = (altered, headers, json.dumps(altered).encode())
    with patch.object(production, 'get_json', side_effect=lambda base, path, key: responses[path]):
        with pytest.raises(ValueError, match='history_month_payload_mismatch'):
            production.verify('https://example.invalid', candidate)


def test_production_rejects_corrupted_earlier_date_revision(candidate):
    responses = served_candidate(candidate)
    path = next(path for path in responses if '/revisions/2026-10-01.' in path)
    value, headers, raw = responses[path]
    responses[path] = (value, headers, raw + b' ')
    with patch.object(production, 'get_json', side_effect=lambda base, path, key: responses[path]):
        with pytest.raises(ValueError, match='history_revision_hash_mismatch'):
            production.verify('https://example.invalid', candidate)


def test_production_reads_all_months_and_all_retained_revisions(candidate):
    responses = served_candidate(candidate)
    with patch.object(production, 'get_json', side_effect=lambda base, path, key: responses[path]) as fetch:
        result = production.verify('https://example.invalid', candidate)
    assert result['valid'] is True
    assert {call.args[1] for call in fetch.call_args_list} == set(responses)


def add_export(data):
    latest = json.loads((data / 'latest.json').read_bytes())
    funnel = {'version': 'funnel-v2-independent-trust-low-position', 'universe': 0,
              'instrumentExcluded': 0, 'growthCandidates': 0,
              'strategyCandidates': {'trust': 0, 'growth': 0, 'lowPosition': 0},
              'growthCoverageVersion': 'growth-coverage-v1', 'growthEvaluationState': 'not_evaluable',
              'growthInputComplete': 0, 'growthValuationComplete': 0,
              'growthThresholdCandidates': 0, 'growthHealthCandidates': 0,
              'growthMissingReasons': [], 'growthTerminalOutcomes': {
                  'universe': 0, 'missing': 0, 'knownInvalid': 0, 'extreme': 0,
                  'belowThreshold': 0, 'healthBlocked': 0, 'selected': 0}}
    value = build_export({**latest, 'formulaVersion': 'fixture-v1', 'stocks': [],
                          'coverage': {'universeCount': 0}, 'funnel': funnel},
                         request_id='fixture-request', source_git_commit='a' * 40,
                         actions_run_id='123')
    months = {}
    index = json.loads((data / 'archive/v1/index.json').read_bytes())
    for meta in index['months']:
        month = json.loads((data / 'archive/v1/months' / Path(meta['path']).name).read_bytes())
        months[meta['month']] = [project_export_to_history(value)
                                if record['marketDate'] == latest['marketDate'] else record
                                for record in month['records']]
    write_archive_atomic(data / 'staging', data / 'archive/v1', months, latest['generatedAt'])
    (data / 'screening-export.json').write_bytes(export_bytes(value))
    return value


def test_production_export_and_history_are_verified_together(candidate):
    add_export(candidate)
    responses = served_candidate(candidate)
    responses['/data/screening-export.json'] = (
        responses['/data/screening-export.json'][0], INDEX_HEADERS,
        responses['/data/screening-export.json'][2])
    with patch.object(production, 'get_json', side_effect=lambda base, path, key: responses[path]):
        assert production.verify('https://example.invalid', candidate)['valid'] is True


def test_production_rejects_different_export_bytes_even_when_json_matches(candidate):
    add_export(candidate)
    responses = served_candidate(candidate)
    value, headers, raw = responses['/data/screening-export.json']
    responses['/data/screening-export.json'] = (value, headers, raw + b'\n')
    with patch.object(production, 'get_json', side_effect=lambda base, path, key: responses[path]):
        with pytest.raises(ValueError, match='screening_export_payload_mismatch'):
            production.verify('https://example.invalid', candidate)


@pytest.mark.parametrize('cache,index,error', [
    ('no-cache', True, 'cache_header_index'),
    ('public, max-age=31536000', False, 'cache_header_month'),
    ('public, max-age=3600, immutable', False, 'cache_age_month'),
    ('public, immutable', False, 'cache_age_month'),
])
def test_production_rejects_cache_policies_that_can_mix_releases(cache, index, error):
    with pytest.raises(ValueError, match=error):
        production.require_headers('/fixture', {'cache-control': cache}, index)


def test_http_fetch_uses_cache_busting_and_preserves_exact_bytes():
    raw = b'{"code":"0050","price":100.0}'
    class Response:
        status = 200
        headers = {'Cache-Control': 'no-store'}
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return raw
    with patch.object(production.urllib.request, 'urlopen', return_value=Response()) as request:
        value, headers, body = production.get_json('https://example.invalid', '/data/latest.json?existing=1', 'run:1')
    assert value['code'] == '0050'
    assert body == raw
    assert headers == {'cache-control': 'no-store'}
    assert request.call_args.args[0].full_url.endswith('existing=1&cachebust=run%3A1')
    assert request.call_args.args[0].get_header('Cache-control') == 'no-cache'
    assert request.call_args.kwargs['timeout'] == 30


def test_http_fetch_rejects_unsuccessful_response_and_cli_reports_failure(candidate, capsys):
    class Response:
        status = 503
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{}'
    with patch.object(production.urllib.request, 'urlopen', return_value=Response()):
        assert production.main(['--base-url', 'https://example.invalid', '--expected-dir', str(candidate)]) == 1
    assert 'production_invalid=http_status:' in capsys.readouterr().out


def test_cli_success_reports_verified_month_count(candidate, capsys):
    responses = served_candidate(candidate)
    with patch.object(production, 'get_json', side_effect=lambda base, path, key: responses[path]):
        assert production.main(['--base-url', 'https://example.invalid', '--expected-dir', str(candidate)]) == 0
    assert json.loads(capsys.readouterr().out)['monthsVerified'] == 2


def test_new_publication_requires_and_verifies_exact_snapshot_fingerprint(candidate):
    latest_bytes = (candidate / 'latest.json').read_bytes()
    fingerprint = build_fingerprint(latest_bytes)
    (candidate / 'publication.json').write_text(
        json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(',', ':')),
        encoding='utf-8',
    )
    responses = served_candidate(candidate)
    with patch.object(production, 'get_json', side_effect=lambda base, path, key: responses[path]):
        result = production.verify('https://example.invalid', candidate)
    assert result['publicationFingerprintVerified'] is True


def test_production_requires_fingerprint_for_growth_coverage_v1(candidate):
    latest_path = candidate / 'latest.json'
    latest = json.loads(latest_path.read_bytes())
    latest['funnel'] = {'growthCoverageVersion': 'growth-coverage-v1'}
    latest_path.write_text(json.dumps(latest), encoding='utf-8')
    with pytest.raises(ValueError, match='publication_fingerprint_missing'):
        production.verify('https://example.invalid', candidate)


def test_production_detects_fingerprint_that_does_not_cover_served_latest(candidate):
    latest_bytes = (candidate / 'latest.json').read_bytes()
    (candidate / 'publication.json').write_text(
        json.dumps(build_fingerprint(latest_bytes), ensure_ascii=False, sort_keys=True, separators=(',', ':')),
        encoding='utf-8',
    )
    responses = served_candidate(candidate)
    actual, headers, _ = responses['/data/latest.json']
    changed = {**actual, 'marketDate': '2026-10-03'}
    responses['/data/latest.json'] = (changed, headers, json.dumps(changed).encode())
    with patch.object(production, 'get_json', side_effect=lambda base, path, key: responses[path]):
        with pytest.raises(ValueError, match='publication_fingerprint_latest_mismatch'):
            production.verify('https://example.invalid', candidate)
