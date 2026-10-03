import importlib
import json
import io
import zipfile

import pytest

from pipeline.finmind_client import DATA_URL, USER_INFO_URL


DATES = ['2026-09-16', '2026-09-17', '2026-09-18', '2026-09-21',
         '2026-09-22', '2026-09-23', '2026-09-24', '2026-09-29',
         '2026-09-30', '2026-10-01', '2026-10-02']


def module():
    return importlib.import_module('pipeline.institutional_probe')


def official(code, buy, sell):
    return {'Date': '1151002', 'SecuritiesCompanyCode': code,
            'SecuritiesInvestmentTrustCompanies-TotalBuy': str(buy),
            'SecuritiesInvestmentTrustCompanies-TotalSell': str(sell),
            'SecuritiesInvestmentTrustCompanies-Difference': str(buy - sell)}


FEED = [official('2330', 10, 0), official('2317', 0, 10), official('1101', 0, 0),
        official('0050', 100, 0), official('2454', 20, 0)]


def history(code, buy, sell):
    return [{'date': day, 'stock_id': code, 'name': 'Investment_Trust',
             'buy': buy, 'sell': sell} for day in DATES]


class Response:
    headers = {}
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.payload).encode()
    def getcode(self):
        return 200


def transport(monkeypatch, replies=None, usage=None):
    import pipeline.finmind_client as client
    import pipeline.finmind_incremental as incremental
    monkeypatch.setattr(incremental, 'current_taipei_day', lambda: '2026-10-03')
    monkeypatch.setattr(client.FinMindClient, '_wait_for_rate', lambda self: None)
    calls = []
    def request(req, timeout):
        from urllib.parse import parse_qs, urlsplit
        calls.append(req.full_url)
        assert timeout == 20
        if req.full_url == USER_INFO_URL:
            return Response(usage or {'api_request_limit': 600, 'user_count': 0})
        assert req.full_url.startswith(DATA_URL)
        code = parse_qs(urlsplit(req.full_url).query)['data_id'][0]
        assert parse_qs(urlsplit(req.full_url).query)['start_date'] == [DATES[0]]
        payload = (replies or {}).get(code)
        if isinstance(payload, Exception):
            raise payload
        if payload is None:
            item = next(row for row in FEED if row['SecuritiesCompanyCode'] == code)
            payload = history(code, int(item['SecuritiesInvestmentTrustCompanies-TotalBuy']),
                              int(item['SecuritiesInvestmentTrustCompanies-TotalSell']))
        return Response({'status': 200, 'data': payload})
    monkeypatch.setattr(client.urllib.request, 'urlopen', request)
    return calls


def run(tmp_path, **kwargs):
    return module().run_institutional_probe(FEED, market_date=DATES[-1],
        expected_dates=DATES, cache_dir=tmp_path, budget_date='2026-10-03',
        token='dummy', **kwargs)


def test_select_deterministic_common_cases_without_mutating_input():
    original = json.dumps(FEED)
    cases = module().select_probe_cases(list(reversed(FEED)), DATES[-1])
    assert [(row['case'], row['code']) for row in cases] == [
        ('positive', '2330'), ('negative', '2317'), ('zero', '1101')]
    assert json.dumps(FEED) == original


@pytest.mark.parametrize('change', [
    {'Date': '1151001'}, {'SecuritiesInvestmentTrustCompanies-TotalBuy': None},
    {'SecuritiesInvestmentTrustCompanies-TotalBuy': '1.2'},
    {'SecuritiesInvestmentTrustCompanies-Difference': '99'}])
def test_invalid_official_feed_fails_before_checkpoint_or_http(tmp_path, monkeypatch, change):
    calls = transport(monkeypatch)
    feed = [{**FEED[0], **change}, *FEED[1:]]
    with pytest.raises(ValueError):
        module().run_institutional_probe(feed, market_date=DATES[-1], expected_dates=DATES,
            cache_dir=tmp_path, budget_date='2026-10-03', token='secret')
    assert not calls and not list(tmp_path.iterdir())


def test_three_complete_ranges_checkpoint_and_all_cache_hits_skip_quota(tmp_path, monkeypatch):
    calls = transport(monkeypatch)
    result = run(tmp_path)
    assert result['outcome'] == 'complete'
    assert result['actualAttempts'] == 4 and result['dataRequests'] == 3
    assert len(calls) == 4 and result['globalCompleteness'] is False
    assert result['quotaPolicy'] == 'rolling-hour-v1'
    assert result['rollingHourAttempts'] == 4 and result['projectHourlyCap'] == 300
    assert result['accountAllowanceRemaining'] == 476
    assert result['quotaObservedAt'] is not None
    assert not {'dailyAttempts', 'projectCeiling', 'accountWindowCeiling'} & result.keys()
    rows = json.loads((tmp_path / 'rows.json').read_text())
    assert len([key for key in rows if key.startswith('institutionalProbe:')]) == 3
    assert all(len(entry['rows']) == 11 and entry['unit'] == 'shares'
               for key, entry in rows.items() if key.startswith('institutionalProbe:'))
    zero = next(entry for key, entry in rows.items() if ':1101:' in key)
    assert all(row['buy'] == row['sell'] == row['net'] == 0 for row in zero['rows'])
    second = run(tmp_path)
    assert second['cacheHits'] == 3 and second['actualAttempts'] == 0
    assert len(calls) == 4
    assert 'dummy' not in json.dumps(result)


def test_missing_history_is_partial_never_filled_zero_and_cached_retry_uses_no_http(tmp_path, monkeypatch):
    calls = transport(monkeypatch, {'2330': history('2330', 10, 0)[1:]})
    first = run(tmp_path)
    case = next(row for row in first['cases'] if row['code'] == '2330')
    assert case['missingDates'] == [DATES[0]] and case['coverage'] == 10 / 11
    assert first['outcome'] == 'partial'
    retry_calls = transport(monkeypatch)
    second = run(tmp_path)
    assert second['outcome'] == 'partial' and second['cacheHits'] == 3
    assert second['dataRequests'] == 0 and second['actualAttempts'] == 0 and not retry_calls
    assert next(row for row in second['cases'] if row['code'] == '2330')['missingDates'] == [DATES[0]]


@pytest.mark.parametrize('mutation', ['duplicate', 'wrong_code', 'wrong_date', 'null', 'float', 'current_mismatch'])
def test_malformed_trust_rows_are_unavailable_not_validated_cache(tmp_path, monkeypatch, mutation):
    rows = history('2330', 10, 0)
    if mutation == 'duplicate':
        rows = [*rows, rows[0]]
    elif mutation == 'wrong_code':
        rows = [{**rows[0], 'stock_id': '2454'}, *rows[1:]]
    elif mutation == 'wrong_date':
        rows = [{**rows[0], 'date': '2026-10-03'}, *rows[1:]]
    elif mutation in {'null', 'float'}:
        rows = [{**rows[0], 'buy': None if mutation == 'null' else 0.5}, *rows[1:]]
    else:
        rows = [*rows[:-1], {**rows[-1], 'buy': 0}]
    transport(monkeypatch, {'2330': rows})
    result = run(tmp_path)
    case = next(row for row in result['cases'] if row['code'] == '2330')
    assert case['errorCategory'] == 'invalid_source_rows'
    assert result['outcome'] == 'partial'


def test_missing_token_causes_no_quota_and_preserves_financial_namespaces(tmp_path, monkeypatch):
    calls = transport(monkeypatch)
    (tmp_path / 'state.json').write_text(json.dumps({'version': 2, 'days': {}, 'queue': [{'code': '9999'}]}))
    (tmp_path / 'rows.json').write_text(json.dumps({'financial': {'2330': ['preserved']}}))
    result = module().run_institutional_probe(FEED, market_date=DATES[-1], expected_dates=DATES,
        cache_dir=tmp_path, budget_date='2026-10-03', token='')
    assert result['outcome'] == 'unavailable' and not result['tokenPresent'] and not calls
    assert json.loads((tmp_path / 'rows.json').read_text())['financial'] == {'2330': ['preserved']}
    assert json.loads((tmp_path / 'state.json').read_text())['queue'] == [{'code': '9999'}]


def test_unknown_quota_stops_before_data_and_exception_is_sanitized(tmp_path, monkeypatch):
    calls = transport(monkeypatch, usage={'bad': 'secret-test-token'})
    result = run(tmp_path)
    assert len(calls) == 1 and result['dataRequests'] == 0
    assert result['errorCategory'] == 'quota_unavailable'
    assert 'secret-test-token' not in json.dumps(result)


def test_unknown_legacy_budget_timing_blocks_all_http(tmp_path, monkeypatch):
    calls = transport(monkeypatch)
    (tmp_path / 'state.json').write_text(json.dumps({'version': 2, 'queue': [], 'days': {
        '2026-10-03': {'attempts': 299, 'ceiling': 300, 'quotaKnown': False}}}))
    result = run(tmp_path)
    assert not calls and result['actualAttempts'] == 0
    assert result['errorCategory'] == 'budget_exhausted'
    state = json.loads((tmp_path / 'state.json').read_text())
    assert state['rollingHour']['projectCap'] == 300


def test_transport_failure_no_retry_records_progress_without_message(tmp_path, monkeypatch):
    from urllib.error import URLError
    calls = transport(monkeypatch, {'2330': URLError('secret-test-token')})
    result = run(tmp_path)
    assert len(calls) == 4 and result['dataRequests'] == 3
    assert result['outcome'] == 'partial'
    assert 'secret-test-token' not in (tmp_path / 'state.json').read_text()


@pytest.mark.parametrize('dates,max_calls', [(DATES[:-1], 3), (DATES + [DATES[0]], 3), (DATES, 4)])
def test_invalid_contract_before_io(tmp_path, dates, max_calls):
    with pytest.raises(ValueError):
        module().run_institutional_probe(FEED, market_date=DATES[-1], expected_dates=dates,
            cache_dir=tmp_path, budget_date='2026-10-03', token='secret', max_data_requests=max_calls)
    assert not list(tmp_path.iterdir())


def test_probe_entries_restore_with_existing_financial_queue_and_rows(tmp_path, monkeypatch):
    from scripts.restore_finmind_checkpoint import recover_zip
    transport(monkeypatch)
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.mkdir(); target.mkdir()
    source.joinpath('state.json').write_text(json.dumps({'version': 2, 'days': {},
        'queue': [{'code': '9999', 'dataset': 'TaiwanStockFinancialStatements'}]}))
    source.joinpath('rows.json').write_text(json.dumps({'9999:financial': {'rows': [{'value': 1}]}}))
    run(source)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        for filename in ['state.json', 'rows.json']:
            archive.writestr(filename, source.joinpath(filename).read_bytes())
    assert recover_zip(target, payload.getvalue(), '2026-10-03')
    restored = json.loads(target.joinpath('rows.json').read_text())
    assert len([key for key in restored if key.startswith('institutionalProbe:')]) == 3
    assert restored['9999:financial']['rows'] == [{'value': 1}]
    state = json.loads(target.joinpath('state.json').read_text())
    assert state['queue'][0]['code'] == '9999' and state['rollingHour']['totalAttempts'] == 4


@pytest.mark.parametrize('mutation', ['raw', 'source', 'range', 'hash', 'normalized', 'timestamp', 'unit'])
def test_altered_cache_is_not_trusted_and_only_that_case_is_refetched(tmp_path, monkeypatch, mutation):
    transport(monkeypatch)
    run(tmp_path)
    path = tmp_path / 'rows.json'
    entries = json.loads(path.read_text())
    key = next(key for key in entries if ':2330:' in key)
    entry = entries[key]
    if mutation == 'raw':
        entries = {**entries, key: {**entry, 'rawRows': [{**entry['rawRows'][0], 'buy': 999}, *entry['rawRows'][1:]]}}
    elif mutation == 'source':
        entries = {**entries, key: {**entry, 'sourceUrl': 'https://untrusted.example/data'}}
    elif mutation == 'range':
        entries = {**entries, key: {**entry, 'sourceParams': {**entry['sourceParams'], 'start_date': '2026-09-17'}}}
    elif mutation == 'hash':
        entries = {**entries, key: {**entry, 'sha256': 'bad'}}
    elif mutation == 'normalized':
        changed = [{**entry['rows'][0], 'buy': 99}, *entry['rows'][1:]]
        entries = {**entries, key: {**entry, 'rows': changed, 'sha256': module()._hash(changed)}}
    else:
        field = 'fetchedAt' if mutation == 'timestamp' else 'unit'
        entries = {**entries, key: {**entry, field: 'unknown'}}
    path.write_text(json.dumps(entries))
    calls = transport(monkeypatch)
    result = run(tmp_path)
    assert result['cacheHits'] == 2 and result['dataRequests'] == 1 and len(calls) == 2


def test_midnight_budget_date_is_metadata_and_does_not_stop_valid_hour(tmp_path, monkeypatch):
    import pipeline.finmind_incremental as incremental
    calls = transport(monkeypatch)
    monkeypatch.setattr(incremental, 'current_taipei_day', lambda: '2026-10-04')
    result = run(tmp_path)
    assert len(calls) == 4 and result['outcome'] == 'complete'
    state = json.loads((tmp_path / 'state.json').read_text())
    assert state['rollingHour']['totalAttempts'] == 4


def test_verified_remaining_quota_zero_stops_before_data(tmp_path, monkeypatch):
    calls = transport(monkeypatch, usage={'api_request_limit': 300, 'user_count': 300})
    result = run(tmp_path)
    assert len(calls) == 1 and result['observedRemaining'] == 0 and result['dataRequests'] == 0
    assert result['errorCategory'] == 'budget_exhausted'


def test_operation_limit_does_not_reduce_shared_project_cap(tmp_path, monkeypatch):
    calls = transport(monkeypatch)
    result = run(tmp_path, max_data_requests=1)
    assert len(calls) == 2 and result['dataRequests'] == 1 and result['outcome'] == 'partial'
    state = json.loads((tmp_path / 'state.json').read_text())
    assert state['rollingHour']['projectCap'] == 300


def test_corrupt_budget_has_truthful_unavailable_metadata_and_no_http(tmp_path, monkeypatch):
    calls = transport(monkeypatch)
    (tmp_path / 'state.json').write_text('corrupt ledger')
    result = run(tmp_path)
    assert not calls and result['outcome'] == 'unavailable'
    assert result['quotaPolicy'] == 'rolling-hour-v1'
    assert result['rollingHourAttempts'] is None and result['projectHourlyCap'] == 300
    assert result['accountAllowanceRemaining'] is None and result['quotaObservedAt'] is None
    assert result['cases'] == [] and result['errorCategory'] == 'checkpoint_unavailable'
    assert result['actualAttempts'] == result['dataRequests'] == result['cacheHits'] == 0
    assert (tmp_path / 'state.json').read_text() == 'corrupt ledger'


@pytest.mark.parametrize('status', [0, None, 402, 429])
def test_source_status_zero_null_and_quota_errors_never_become_zero_rows(tmp_path, monkeypatch, status):
    import pipeline.finmind_client as client
    calls = transport(monkeypatch)
    original = client.urllib.request.urlopen
    def request(req, timeout):
        if 'data_id=2330' in req.full_url:
            calls.append(req.full_url)
            return Response({'status': status, 'data': []})
        return original(req, timeout)
    monkeypatch.setattr(client.urllib.request, 'urlopen', request)
    result = run(tmp_path)
    case = result['cases'][0]
    assert case['status'] == 'unavailable' and case['missingDates'] == DATES
    assert result['dataRequests'] == (1 if status in {402, 429} else 3)
    assert result['actualAttempts'] == len(calls)
    if status in {402, 429}:
        assert result['errorCategory'] == 'source_blocked'
    entries = json.loads((tmp_path / 'rows.json').read_text()) if (tmp_path / 'rows.json').exists() else {}
    assert not any(':2330:' in key for key in entries)


def test_empty_trust_response_remains_missing_and_can_be_reused(tmp_path, monkeypatch):
    transport(monkeypatch, {'2330': []})
    first = run(tmp_path)
    case = first['cases'][0]
    assert case['status'] == 'partial' and case['coverage'] == 0 and case['missingDates'] == DATES
    calls = transport(monkeypatch)
    second = run(tmp_path)
    assert not calls and second['cases'][0]['missingDates'] == DATES


def test_all_three_partial_histories_have_partial_outcome_and_cached_replay_no_http(tmp_path, monkeypatch):
    replies = {'2330': history('2330', 10, 0)[1:], '2317': history('2317', 0, 10)[1:],
               '1101': history('1101', 0, 0)[1:]}
    transport(monkeypatch, replies)
    first = run(tmp_path)
    assert first['outcome'] == 'partial'
    assert all(case['coverage'] == 10 / 11 and case['missingDates'] == [DATES[0]] for case in first['cases'])
    calls = transport(monkeypatch)
    second = run(tmp_path)
    assert second['outcome'] == 'partial' and second['cacheHits'] == 3
    assert second['actualAttempts'] == 0 and not calls
