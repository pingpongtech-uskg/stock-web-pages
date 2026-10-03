import importlib
import json
from pathlib import Path

import pytest

from pipeline.test_institutional_probe import DATES, FEED, Response, transport


@pytest.fixture(autouse=True)
def actions_environment(monkeypatch):
    monkeypatch.setenv('GITHUB_ACTIONS', 'true')


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
    monkeypatch.setenv('FINMIND_TOKEN', 'secret-test-token')
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
    monkeypatch.setenv('FINMIND_TOKEN', 'secret-test-token')
    assert script.main(options) == 0
    result = json.loads((tmp_path / 'summary.json').read_text())
    assert result['outcome'] == 'unavailable' and result['errorCategory'] == 'official_source_invalid'
    assert not calls and 'secret-test-token' not in json.dumps(result)


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
        raise OSError('secret-test-token')
    monkeypatch.setattr(script, 'urlopen', unavailable)
    assert script.main(options) == 0
    result = json.loads((tmp_path / 'summary.json').read_text())
    assert result['errorCategory'] == 'official_source_unavailable' and result['actualAttempts'] == 0
    assert 'secret-test-token' not in json.dumps(result)


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
    monkeypatch.setenv('FINMIND_TOKEN', 'secret-test-token')
    assert script.main(args(tmp_path)) == 0
    assert not calls
    assert json.loads((tmp_path / 'summary.json').read_text())['errorCategory'] == 'official_source_unavailable'
