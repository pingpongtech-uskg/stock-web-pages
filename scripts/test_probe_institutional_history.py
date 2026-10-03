import importlib
import gzip
import hashlib
import io
import json
import subprocess
from http.client import HTTPException, HTTPResponse, IncompleteRead
from pathlib import Path

import pytest

from pipeline.test_institutional_probe import DATES, FEED, Response as FixtureResponse, transport


class Response(FixtureResponse):
    def read(self, size=None):
        payload = super().read()
        return payload if size is None else payload[:size]


@pytest.fixture(autouse=True)
def actions_environment(monkeypatch):
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')
    monkeypatch.setattr(module(), 'sleep', lambda seconds: None)


def module():
    return importlib.import_module('scripts.probe_institutional_history')


def calendar():
    return json.loads((Path(__file__).resolve().parents[1] / 'public/data/trading-calendar.json').read_text())


def args(tmp_path):
    path = tmp_path / 'calendar.json'
    path.write_text(json.dumps(calendar()))
    return ['--market-date', '2026-10-02', '--calendar', str(path),
            '--budget-date', '2026-10-03', '--cache-dir', str(tmp_path / 'cache'),
            '--summary', str(tmp_path / 'summary.json'), '--max-data-requests', '3']


def test_calendar_eleven_sessions_skip_known_holidays():
    assert module().expected_sessions(calendar(), '2026-10-02') == DATES


def test_cli_public_source_then_three_ranges_only_checkpoint_writes(tmp_path, monkeypatch):
    options = args(tmp_path)
    calls = transport(monkeypatch)
    script = module()
    public_calls = []
    def official(req, timeout):
        public_calls.append(req.full_url)
        assert req.full_url == script.OFFICIAL_URL and timeout == 20
        assert req.get_header('Authorization') is None
        return Response(FEED)
    monkeypatch.setattr(script, 'urlopen', official)
    monkeypatch.setenv('FINMIND_TOKEN', 'dummy')
    assert script.main(options) == 0
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert summary['outcome'] == 'complete' and not summary['publicationEligible']
    assert len(public_calls) == 1 and len(calls) == 4


@pytest.mark.parametrize('field,value', [('--market-date', '20261002'), ('--market-date', '2026-02-30'),
    ('--budget-date', '20261003'), ('--max-data-requests', '4')])
def test_bad_cli_before_network_and_writes(tmp_path, monkeypatch, field, value):
    options = args(tmp_path)
    options[options.index(field) + 1] = value
    script = module()
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: pytest.fail('HTTP before validation'))
    with pytest.raises(SystemExit):
        script.main(options)
    assert not (tmp_path / 'cache').exists() and not (tmp_path / 'summary.json').exists()


def test_wrong_official_date_no_finmind_calls_sanitized_summary(tmp_path, monkeypatch):
    options = args(tmp_path)
    calls = transport(monkeypatch)
    script = module()
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: Response([{**row, 'Date': '1151001'} for row in FEED]))
    monkeypatch.setenv('FINMIND_TOKEN', 'dummy')
    assert script.main(options) == 0
    result = json.loads((tmp_path / 'summary.json').read_text())
    assert result['outcome'] == 'unavailable' and result['errorCategory'] == 'official_source_invalid'
    assert not calls and 'dummy' not in json.dumps(result)


def test_invalid_calendar_before_source_request(tmp_path, monkeypatch):
    options = args(tmp_path)
    (tmp_path / 'calendar.json').write_text('{}')
    script = module()
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: pytest.fail('HTTP before calendar validation'))
    assert script.main(options) == 1
    assert not (tmp_path / 'cache').exists()


def test_official_transport_error_checkpoint_summary_no_exception_text(tmp_path, monkeypatch):
    options = args(tmp_path)
    script = module()
    def unavailable(*args, **kwargs):
        raise OSError('dummy')
    monkeypatch.setattr(script, 'urlopen', unavailable)
    assert script.main(options) == 0
    result = json.loads((tmp_path / 'summary.json').read_text())
    assert result['errorCategory'] == 'official_source_unavailable' and result['actualAttempts'] == 0
    assert 'dummy' not in json.dumps(result)


def test_output_in_public_forbidden_before_io(tmp_path, monkeypatch):
    options = args(tmp_path)
    options[options.index('--summary') + 1] = str(Path(__file__).resolve().parents[1] / 'public/data/probe.json')
    script = module()
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: pytest.fail('HTTP before output validation'))
    assert script.main(options) == 1


@pytest.mark.parametrize('flag,path', [('--summary', 'config/tracked_symbols.json'),
    ('--cache-dir', '.git'), ('--summary', 'package.json'), ('--cache-dir', 'scripts'),
    ('--summary', 'docs/probe.json')])
def test_all_product_paths_rejected_before_network(tmp_path, monkeypatch, flag, path):
    options = args(tmp_path)
    options[options.index(flag) + 1] = str(Path(__file__).resolve().parents[1] / path)
    script = module()
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: pytest.fail('HTTP before output validation'))
    assert script.main(options) == 1


def test_script_requires_actions_before_http(tmp_path, monkeypatch):
    script = module()
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: pytest.fail('Local HTTP forbidden'))
    assert script.main(args(tmp_path)) == 1


def test_official_non200_json_is_not_source_evidence(tmp_path, monkeypatch):
    calls = transport(monkeypatch)
    script = module()
    class Non200(Response):
        def getcode(self):
            return 201
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: Non200(FEED))
    monkeypatch.setenv('FINMIND_TOKEN', 'dummy')
    assert script.main(args(tmp_path)) == 0
    assert not calls
    assert json.loads((tmp_path / 'summary.json').read_text())['errorCategory'] == 'official_source_unavailable'


def test_incomplete_official_http_body_saves_sanitized_summary_before_finmind(tmp_path, monkeypatch):
    script = module()
    calls = []
    class BrokenBody(Response):
        def read(self, *args):
            raise IncompleteRead(b'dummy', 42)
    def official(request, timeout):
        calls.append(request.full_url)
        return BrokenBody(FEED)
    monkeypatch.setattr(script, 'urlopen', official)
    monkeypatch.setattr(script, 'run_institutional_probe', lambda *a, **k: pytest.fail('FinMind after invalid HTTP'))
    monkeypatch.setenv('FINMIND_TOKEN', 'dummy')
    assert script.main(args(tmp_path)) == 0
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert summary['errorCategory'] == 'official_source_unavailable'
    assert summary['actualAttempts'] == summary['dataRequests'] == 0
    assert summary['cases'] == [] and summary['outcome'] == 'unavailable'
    assert summary['publicationEligible'] is summary['globalCompleteness'] is False
    assert summary['tokenPresent'] is True
    assert 'dummy' not in json.dumps(summary)
    assert len(calls) == 2
    artifact_check = '''
const fs=require('fs');const {sourceValidateArtifact}=require('./scripts/n8n/source-probe-artifact.cjs');
const summary=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
const state={plan:{requestId:'probe:test',marketDate:summary.marketDate,probeHeadSha:'a'.repeat(40)},runId:'1',runAttempt:1};
const provenance={requestId:'probe:test',marketDate:summary.marketDate,sourceMode:'institutional_probe',sourceGitCommit:'a'.repeat(40),actionsRunId:'1',actionsRunAttempt:'1',repository:'pingpongtech-uskg/stock-web-pages'};
sourceValidateArtifact({'summary.json':summary,'provenance.json':provenance,byteHashes:{summary:'b'.repeat(64),provenance:'c'.repeat(64)}},state);
'''
    subprocess.run(['node', '-e', artifact_check, str(tmp_path / 'summary.json')], cwd=script.ROOT, check=True)


def test_bounded_read_recovers_one_truncated_transport_then_validates_full_json(tmp_path, monkeypatch):
    script = module()
    calls = transport(monkeypatch)
    reads = []
    class Body(Response):
        def read(self, size=None):
            reads.append(size)
            assert size == 2 * 1024 * 1024 + 1
            if len(reads) == 1:
                raise IncompleteRead(b'{"Date":', 1000)
            return super().read(size)
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: Body(FEED))
    monkeypatch.setenv('FINMIND_TOKEN', 'dummy')
    assert script.main(args(tmp_path)) == 0
    assert len(reads) == 2 and len(calls) == 4
    assert json.loads((tmp_path / 'summary.json').read_text())['outcome'] == 'complete'


@pytest.mark.parametrize('body', [b'x' * (2 * 1024 * 1024 + 1), b'[{"Date":"1151002"'])
def test_oversize_or_incomplete_json_never_retried_or_accepted(tmp_path, monkeypatch, body):
    script = module()
    calls = []
    class Body(Response):
        def read(self, size=None):
            assert size == 2 * 1024 * 1024 + 1
            return body
    def official(request, timeout):
        calls.append(request.full_url)
        return Body(FEED)
    monkeypatch.setattr(script, 'urlopen', official)
    monkeypatch.setattr(script, 'run_institutional_probe', lambda *a, **k: pytest.fail('Invalid JSON reaches FinMind'))
    assert script.main(args(tmp_path)) == 0
    assert len(calls) == 1
    assert json.loads((tmp_path / 'summary.json').read_text())['actualAttempts'] == 0


def test_real_http_response_wrong_content_length_accepts_only_complete_bounded_json(monkeypatch):
    script = module()
    body = json.dumps(FEED).encode()
    wire = b'HTTP/1.1 200 OK\r\nContent-Length: ' + str(len(body) + 1000).encode() + b'\r\n\r\n' + body
    class Socket:
        def makefile(self, *args):
            return io.BytesIO(wire)
    def response():
        result = HTTPResponse(Socket())
        result.begin()
        return result
    with pytest.raises(IncompleteRead):
        response().read()
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: response())
    raw, rows = script.fetch_official_json()
    assert raw == body and rows == FEED


@pytest.mark.parametrize('exception', [HTTPException('dummy'), 'http_status'])
def test_nontransport_http_failures_not_retried_and_remain_sanitized(tmp_path, monkeypatch, exception):
    from urllib.error import HTTPError
    script = module()
    calls = []
    def unavailable(request, timeout):
        calls.append(request.full_url)
        if exception == 'http_status':
            raise HTTPError(request.full_url, 503, 'dummy', {}, None)
        raise exception
    monkeypatch.setattr(script, 'urlopen', unavailable)
    monkeypatch.setattr(script, 'run_institutional_probe', lambda *a, **k: pytest.fail('FinMind invoked'))
    assert script.main(args(tmp_path)) == 0
    assert len(calls) == 1
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert summary['errorCategory'] == 'official_source_unavailable' and summary['actualAttempts'] == 0
    assert 'dummy' not in json.dumps(summary)


def captured_args(tmp_path, *, rows=FEED, raw=None, metadata_change=None, compressed=None):
    options = args(tmp_path)
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    body = json.dumps(rows).encode() if raw is None else raw
    metadata = {'schemaVersion': 'official-institutional-evidence-v1',
        'sourceUrl': module().OFFICIAL_URL, 'documentationUrl': 'https://www.tpex.org.tw/openapi/swagger.json',
        'requestMethod': 'GET', 'httpStatus': 200, 'contentType': 'application/json',
        'retrievedAt': '2026-10-03T01:12:54.281658+00:00', 'rawDate': '1151002',
        'marketDate': '2026-10-02', 'unit': 'shares', 'rowCount': len(rows),
        'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body), **(metadata_change or {})}
    (evidence / '2026-10-02.json.gz').write_bytes(gzip.compress(body, mtime=0) if compressed is None else compressed)
    (evidence / '2026-10-02.metadata.json').write_text(json.dumps(metadata))
    return [*options, '--official-evidence-dir', str(evidence)], body


def test_captured_source_replay_no_official_http_and_original_hash_summary(tmp_path, monkeypatch, capsys):
    calls = transport(monkeypatch)
    script = module()
    options, raw = captured_args(tmp_path)
    original_metadata = (tmp_path / 'evidence/2026-10-02.metadata.json').read_bytes()
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: pytest.fail('Captured mode must not use HTTP'))
    monkeypatch.setenv('FINMIND_TOKEN', 'dummy')
    assert script.main(options) == 0
    assert len(calls) == 4
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert summary['officialSha256'] == hashlib.sha256(raw).hexdigest()
    assert summary['officialRowCount'] == len(FEED) and summary['outcome'] == 'complete'
    assert (tmp_path / 'evidence/2026-10-02.metadata.json').read_bytes() == original_metadata
    assert 'official_evidence_mode=captured' in capsys.readouterr().out


@pytest.mark.parametrize('change', [
    {'sha256': 'a' * 64}, {'bytes': 42}, {'marketDate': '2026-10-01'}, {'rawDate': '1151001'},
    {'unit': 'lots'}, {'sourceUrl': 'https://untrusted.example/data'}, {'httpStatus': 201},
    {'retrievedAt': '2026-10-03T01:12:54'}, {'rowCount': 910}, {'rowCount': True},
    {'schemaVersion': 'unknown'}, {'unexpected': 'dummy'}])
def test_invalid_captured_metadata_no_network_no_finmind(tmp_path, monkeypatch, change):
    script = module()
    options, raw = captured_args(tmp_path, metadata_change=change)
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: pytest.fail('No HTTP fallback'))
    monkeypatch.setattr(script, 'run_institutional_probe', lambda *a, **k: pytest.fail('Unverified evidence reaches FinMind'))
    assert script.main(options) == 0
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert summary['actualAttempts'] == summary['dataRequests'] == 0
    assert summary['cases'] == [] and summary['errorCategory'] == 'official_source_invalid'


@pytest.mark.parametrize('variant', ['missing', 'corrupt', 'deflate_corrupt', 'decompressed_oversize', 'compressed_oversize',
                                     'malformed_json', 'wrong_date', 'duplicate_code', 'bad_shares'])
def test_captured_archive_rejection_before_finmind_without_http_fallback(tmp_path, monkeypatch, variant):
    script = module()
    raw = None; compressed = None; rows = FEED
    if variant == 'decompressed_oversize':
        raw = b' ' * (2 * 1024 * 1024 + 1)
    elif variant == 'compressed_oversize':
        compressed = b'x' * (2 * 1024 * 1024 + 1)
    elif variant == 'corrupt':
        compressed = b'not-gzip'
    elif variant == 'deflate_corrupt':
        compressed = b'\x1f\x8b\x08\x00' + b'\0' * 6 + b'\xff' * 20
    elif variant == 'malformed_json':
        raw = b'[{"Date":"1151002"'
    elif variant == 'wrong_date':
        rows = [{**row, 'Date': '1151001'} for row in FEED]
    elif variant == 'duplicate_code':
        rows = [*FEED, FEED[0]]
    elif variant == 'bad_shares':
        rows = [{**FEED[0], 'SecuritiesInvestmentTrustCompanies-TotalBuy': None}, *FEED[1:]]
    options, body = captured_args(tmp_path, rows=rows, raw=raw, compressed=compressed,
        metadata_change={'bytes': 1} if variant == 'decompressed_oversize' else None)
    if variant == 'missing':
        (tmp_path / 'evidence/2026-10-02.json.gz').unlink()
    monkeypatch.setattr(script, 'urlopen', lambda *a, **k: pytest.fail('No HTTP fallback'))
    monkeypatch.setattr(script, 'run_institutional_probe', lambda *a, **k: pytest.fail('Bad captured source reaches FinMind'))
    assert script.main(options) == 0
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert summary['actualAttempts'] == summary['dataRequests'] == 0
    assert summary['errorCategory'] in {'official_source_invalid', 'official_source_unavailable'}
