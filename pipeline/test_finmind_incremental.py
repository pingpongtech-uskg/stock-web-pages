import json
from pathlib import Path
import urllib.error
import uuid
from datetime import datetime

import pytest

from pipeline.finmind_client import BudgetExceeded, FinMindClient, FinMindError, SourceBlocked
from pipeline.finmind_incremental import DailyBudget, current_taipei_day, merge_raw_rows, plan_gaps, supplement_snapshot


@pytest.fixture(autouse=True)
def fixed_budget_clock(monkeypatch):
    monkeypatch.setattr('pipeline.finmind_incremental.current_taipei_day', lambda: '2026-10-02', raising=False)


@pytest.mark.parametrize('utc_time, expected', [('2020-01-01T15:59:59+00:00', '2020-01-01'),
                                              ('2020-01-01T16:00:00+00:00', '2020-01-02')])
def test_default_budget_clock_uses_taipei_midnight(monkeypatch, utc_time, expected):
    from pipeline import finmind_incremental
    instant = datetime.fromisoformat(utc_time)

    class FixtureDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(finmind_incremental, 'datetime', FixtureDateTime)
    # The imported binding retains the actual clock despite the request fixture.
    assert current_taipei_day() == expected


def test_midnight_preserves_same_rolling_ledger_and_queue(tmp_path, monkeypatch):
    day = ['2026-10-02']
    monkeypatch.setattr('pipeline.finmind_incremental.current_taipei_day', lambda: day[0])
    state = DailyBudget(tmp_path / 'state.json', day[0])
    jobs = [{'code': '2330', 'dataset': 'TaiwanStockFinancialStatements'}]
    state.queue(jobs)
    state.consume()
    day[0] = '2026-10-03'
    recovered = DailyBudget(state.path, day[0])
    recovered.consume()
    checkpoint = json.loads(state.path.read_text())
    assert checkpoint['rollingHour']['totalAttempts'] == 2
    assert recovered.rolling_used == 2
    assert checkpoint['queue'] == jobs


@pytest.mark.parametrize('phase', ['quota_retry', 'data_retry', 'rate_wait', 'after_quota'])
def test_crossing_midnight_does_not_reset_attempts_or_supplement_queue(tmp_path, monkeypatch, phase):
    day = ['2026-10-02']
    monkeypatch.setattr('pipeline.finmind_incremental.current_taipei_day', lambda: day[0], raising=False)
    output, _ = fixture_release(tmp_path)
    calls = []
    waits = []

    def respond(request, **kwargs):
        calls.append(request.full_url)
        if request.full_url.endswith('/v2/user_info'):
            if phase == 'quota_retry':
                raise urllib.error.URLError('fixture outage')
            if phase == 'after_quota':
                day[0] = '2026-10-03'
            return Response({'api_request_limit': 1000, 'user_count': 0})
        raise urllib.error.URLError('fixture outage')

    def rate_wait(self):
        waits.append(True)
        if phase == 'rate_wait' and len(waits) == 2:
            day[0] = '2026-10-03'

    monkeypatch.setattr('urllib.request.urlopen', respond)
    monkeypatch.setattr(FinMindClient, '_wait_for_rate', rate_wait)
    monkeypatch.setattr('time.sleep', lambda seconds: day.__setitem__(0, '2026-10-03'))
    result = supplement_snapshot(['2330'], output, '2026-10-02', cache_dir=tmp_path / 'cache',
                                 budget_date='2026-10-02', token=str(uuid.uuid4()), max_requests=4)
    expected = 3 if phase == 'quota_retry' else 4
    assert len(calls) == expected
    assert result['requests'] == expected
    assert result['skipped'] == ('FinMindError' if phase == 'quota_retry' else 'BudgetExceeded')
    assert result['queued'] > 0 and result['completed'] == 0
    checkpoint = json.loads((tmp_path / 'cache' / 'state.json').read_text())
    assert checkpoint['queue']
    assert checkpoint['rollingHour']['totalAttempts'] == expected
    assert len(checkpoint['rollingHour']['events']) == expected


def detail(code='2330'):
    return {'code': code, 'healthInputs': {}, 'financialInputs': {}, 'revenueMonthly': []}


def test_daily_budget_survives_recovery_and_never_gets_a_new_ceiling(tmp_path):
    first = DailyBudget(tmp_path / 'state.json', '2026-10-02', hard_cap=300)
    first.consume()
    first.configure(10, 0)
    for _ in range(7):
        first.consume(require_known=True)
    recovered = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    with pytest.raises(BudgetExceeded):
        recovered.consume(require_known=True)
    assert recovered.used == 8
    assert DailyBudget(tmp_path / 'state.json', '2026-10-03').used == 8


def test_check_and_retries_are_checkpointed_before_http(tmp_path, monkeypatch):
    seen = []
    state = DailyBudget(tmp_path / 'state.json', '2026-10-02', hard_cap=3)
    def fail(request, **kwargs):
        seen.append(json.loads(state.path.read_text())['rollingHour']['totalAttempts'])
        assert request.get_header('Authorization') == 'Bearer secret'
        raise urllib.error.URLError('offline')
    monkeypatch.setattr('urllib.request.urlopen', fail)
    monkeypatch.setattr('time.sleep', lambda value: None)
    client = FinMindClient('secret', daily_budget=state, min_interval=0)
    with pytest.raises(FinMindError):
        client.configure_account_budget()
    assert seen == [1, 2, 3]
    with pytest.raises(BudgetExceeded):
        FinMindClient('secret', daily_budget=state).configure_account_budget()


def test_unknown_account_quota_cannot_call_data(tmp_path, monkeypatch):
    state = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    client = FinMindClient('secret', daily_budget=state, min_interval=0)
    with pytest.raises(FinMindError):
        client.get('TaiwanStockFinancialStatements', data_id='2330')
    assert state.used == 0


def test_source_block_is_persistent_and_keeps_retry_after(tmp_path, monkeypatch):
    state = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    state.configure(100, 0)
    client = FinMindClient('secret', daily_budget=state, min_interval=0)
    client.budget = type('Budget', (), {'consume': lambda self: None})()
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError('url', 429, 'limit', {'Retry-After': '120'}, None)))
    with pytest.raises(SourceBlocked):
        client.get('TaiwanStockFinancialStatements', data_id='2330')
    recovered = DailyBudget(state.path, '2026-10-02')
    assert recovered.record['retryAfterSeconds'] == 120
    with pytest.raises(SourceBlocked):
        recovered.consume()
    assert state.used == 1


def test_corrupt_ledger_fails_closed(tmp_path):
    (tmp_path / 'state.json').write_text('broken')
    with pytest.raises(FinMindError):
        DailyBudget(tmp_path / 'state.json', '2026-10-02')


def test_plan_financial_first_without_balance_or_cashflow():
    queue = plan_gaps([detail('2330'), detail('2317')], {}, '2026-10-02')
    assert [job['code'] for job in queue[:2]] == ['2317', '2330']
    assert all(job['dataset'] == 'TaiwanStockFinancialStatements' for job in queue[:2])
    assert not any('Balance' in job['dataset'] or 'CashFlows' in job['dataset'] for job in queue)
    assert queue[0]['start_date'] == '2022-01-01'


def test_empty_optional_data_preserves_history_and_same_period_not_repolled():
    rows = [{'date': '2025-03-31', 'type': 'EPS', 'value': 2}]
    assert merge_raw_rows(rows, []) == rows
    cache = {'2330:TaiwanStockFinancialStatements': {'rows': rows, 'checkedPeriod': '2026-Q2', 'checkedAt': '2026-10-01'}}
    assert not any(job['dataset'] == 'TaiwanStockFinancialStatements' for job in plan_gaps([detail()], cache, '2026-10-02'))


def test_latest_period_due_refreshes_incrementally():
    cache = {'2330:TaiwanStockFinancialStatements': {'rows': [{'date': '2026-06-30', 'type': 'EPS', 'value': 2}], 'checkedPeriod': '2026-Q2', 'checkedAt': '2026-10-01'}}
    stock = {**detail(), 'healthInputs': {'incomeQuarterly': [{'year': year, 'quarter': quarter, 'eps': 2} for year in range(2022, 2026) for quarter in range(1, 5)]}}
    jobs = plan_gaps([stock], cache, '2026-11-15')
    job = next(job for job in jobs if job['dataset'] == 'TaiwanStockFinancialStatements')
    assert job['start_date'] == '2026-06-30'


def test_no_token_keeps_public_release_and_checkpoints_queue(tmp_path):
    output = tmp_path / 'public'
    stocks = output / 'releases' / 'release' / 'stocks'
    stocks.mkdir(parents=True)
    base = {**detail(), 'financialInputs': {'incomeStatement': [{'date': '2025-03-31', 'type': 'EPS', 'value': 2}]}}
    (stocks / '2330.json').write_text(json.dumps(base))
    (output / 'latest.json').write_text(json.dumps({'runId': 'release', 'stocks': [{'code': '2330'}]}))
    result = supplement_snapshot(['2330'], output, '2026-10-02', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token='')
    assert result['requests'] == 0
    assert result['skipped'] == 'missing_token'
    assert json.loads((stocks / '2330.json').read_text()) == base
    assert json.loads((tmp_path / 'cache' / 'state.json').read_text())['queue']

class Response:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.payload).encode()


def fixture_release(tmp_path, stocks=None):
    output = tmp_path / 'public'
    directory = output / 'releases' / 'release' / 'stocks'
    directory.mkdir(parents=True)
    stocks = stocks or [detail()]
    for stock in stocks:
        (directory / f"{stock['code']}.json").write_text(json.dumps(stock))
    (output / 'latest.json').write_text(json.dumps({'runId': 'release', 'stocks': [{'code': stock['code']} for stock in stocks]}))
    return output, directory


def test_successful_supplement_merges_and_resume_uses_cached_periods(tmp_path, monkeypatch):
    import urllib.parse
    output, directory = fixture_release(tmp_path, [detail('2330'), detail('2317')])
    calls = []
    def respond(request, **kwargs):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        calls.append(params)
        if not params:
            return Response({'api_request_limit': 1000, 'user_count': 0})
        dataset = params['dataset'][0]
        rows = {
            'TaiwanStockFinancialStatements': [{'date': '2025-03-31', 'type': 'EPS', 'value': 2}],
            'TaiwanStockPER': [{'date': '2026-10-01', 'PER': 20, 'PBR': 2, 'dividend_yield': 3}],
            'TaiwanStockDividend': [{'date': '2026-07-01', 'year': '114年', 'CashEarningsDistribution': 2,
                                     'CashStatutorySurplus': 0, 'StockEarningsDistribution': 0,
                                     'CashExDividendTradingDate': '2026-07-01', 'AnnouncementDate': '2026-06-01'}],
            'TaiwanStockMonthRevenue': [{'date': '2026-09-10', 'revenue_year': 2026, 'revenue_month': 8, 'revenue': 50}],
        }[dataset]
        return Response({'status': 200, 'data': rows})
    monkeypatch.setattr('urllib.request.urlopen', respond)
    monkeypatch.setattr('time.sleep', lambda value: None)
    result = supplement_snapshot(['2330', '2317'], output, '2026-10-02', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token='secret')
    assert result['updated'] == 2
    assert result['requests'] == 9
    # One EPS quarter, one revenue month, and stale PE per stock remain recoverable.
    assert result['queued'] == 6
    pending = json.loads((tmp_path / 'cache' / 'state.json').read_text())['queue']
    assert {job['dataset'] for job in pending} == {'TaiwanStockFinancialStatements', 'TaiwanStockMonthRevenue', 'TaiwanStockPER'}
    assert all(job['notBefore'] == '2026-10-09' for job in pending)
    stock = json.loads((directory / '2330.json').read_text())
    assert stock['healthInputs']['valuationCurrent']['pe'] == 20
    assert stock['healthInputs']['dividends'][0]['cashPerShare'] == 2
    assert stock['healthInputs']['incomeQuarterly'][0]['eps'] == 2
    assert stock['healthInputs']['monthlyRevenueOfficial'][0]['revenue'] == 50
    rerun = supplement_snapshot(['2330', '2317'], output, '2026-10-02', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token='secret')
    assert len(calls) == 9
    assert rerun['requests'] == 9
    assert not any('Balance' in str(call) or 'CashFlows' in str(call) for call in calls)


def test_partial_budget_leaves_whole_universe_and_resumable_queue(tmp_path, monkeypatch):
    output, directory = fixture_release(tmp_path, [detail('2330'), detail('2317')])
    monkeypatch.setattr('time.sleep', lambda value: None)
    monkeypatch.setattr('urllib.request.urlopen', lambda request, **k: Response({'api_request_limit': 4, 'user_count': 0}) if 'user_info' in request.full_url else Response({'status': 200, 'data': [{'date': '2025-03-31', 'type': 'EPS', 'value': 2}]}))
    result = supplement_snapshot(['2330', '2317'], output, '2026-10-02', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token='secret')
    assert result['requests'] == 3
    assert result['updated'] == 2
    assert result['skipped'] == 'BudgetExceeded'
    assert len(list(directory.glob('*.json'))) == 2
    assert result['queued'] == 8  # Six untried jobs plus two partial EPS histories deferred for recovery.
    recovered = supplement_snapshot(['2330', '2317'], output, '2026-10-02', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token='secret')
    assert recovered['requests'] == 3
    assert recovered['skipped'] == 'BudgetExceeded'


def test_unknown_quota_skips_without_destroying_old_history(tmp_path, monkeypatch):
    output, directory = fixture_release(tmp_path)
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: Response({'status': 200}))
    result = supplement_snapshot(['2330'], output, '2026-10-02', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token='secret')
    assert result['requests'] == 1
    assert result['skipped'] == 'FinMindError'
    assert json.loads((directory / '2330.json').read_text()) == detail()


def test_empty_response_cached_once_and_failed_dataset_keeps_queue(tmp_path, monkeypatch):
    output, _ = fixture_release(tmp_path)
    monkeypatch.setattr('time.sleep', lambda value: None)
    def respond(request, **kwargs):
        if 'user_info' in request.full_url:
            return Response({'api_request_limit': 100, 'user_count': 0})
        if 'TaiwanStockFinancialStatements' in request.full_url:
            return Response({'status': 200, 'data': []})
        return Response({'status': 400, 'data': []})
    monkeypatch.setattr('urllib.request.urlopen', respond)
    result = supplement_snapshot(['2330'], output, '2026-10-02', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token='secret')
    assert result['skipped'] == 'dataset_unavailable'
    assert result['queued'] == 4  # Three failed datasets plus the empty financial response.
    pending = json.loads((tmp_path / 'cache' / 'state.json').read_text())['queue']
    financial = next(job for job in pending if job['dataset'] == 'TaiwanStockFinancialStatements')
    assert financial['notBefore'] == '2026-10-09'
    assert result['requests'] == 5
    cache = json.loads((tmp_path / 'cache' / 'rows.json').read_text())
    assert cache['2330:TaiwanStockFinancialStatements']['checkedPeriod'] == '2026-Q2'


def test_runtime_cap_finishes_checkpoint_before_data_requests(tmp_path, monkeypatch):
    output, _ = fixture_release(tmp_path)
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: Response({'api_request_limit': 100, 'user_count': 0}))
    result = supplement_snapshot(['2330'], output, '2026-10-02', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token='secret', max_runtime_seconds=0)
    assert result['requests'] == 1
    assert result['skipped'] == 'runtime_limit'
    assert result['queued'] == 4


def test_bad_paths_and_cache_fail_before_network(tmp_path):
    with pytest.raises(FinMindError, match='Public snapshot missing'):
        supplement_snapshot(['2330'], tmp_path / 'public', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token='secret')
    with pytest.raises(ValueError):
        DailyBudget(tmp_path / 'bad.json', '2026-10-02', hard_cap=301)
    (tmp_path / 'bad.json').write_text(json.dumps({'days': []}))
    with pytest.raises(FinMindError):
        DailyBudget(tmp_path / 'bad.json', '2026-10-02')
    (tmp_path / 'bad.json').write_text(json.dumps({'days': {'2026-10-02': {'attempts': -1}}}))
    with pytest.raises(FinMindError):
        DailyBudget(tmp_path / 'bad.json', '2026-10-02')


def test_json_quota_response_stops_without_retrying(tmp_path, monkeypatch):
    state = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: Response({'status': 402}, {'Retry-After': '60'}))
    client = FinMindClient('secret', daily_budget=state, min_interval=0)
    with pytest.raises(SourceBlocked):
        client.configure_account_budget()
    assert state.used == 1
    assert state.record['blocked'] == 'API response status 402'


def test_retry_after_dates_and_invalid_headers():
    client = FinMindClient('secret')
    assert client._retry_after({'Retry-After': 'Wed, 21 Oct 2099 07:28:00 GMT'}) > 0
    assert client._retry_after({'Retry-After': 'invalid'}) is None
    assert client._retry_after({}) is None
    with pytest.raises(FinMindError):
        FinMindClient(' ')


def test_new_quarter_due_fetches_even_if_old_history_is_complete():
    rows = [{'year': year, 'quarter': quarter, 'eps': 2, 'grossProfit': 10,
             'operatingProfit': 5, 'pretaxProfit': 4, 'netIncome': 3}
            for year in range(2022, 2027) for quarter in range(1, 5)
            if year < 2026 or quarter <= 2]
    stock = {**detail(), 'healthInputs': {'incomeQuarterly': rows}}
    jobs = plan_gaps([stock], {}, '2026-11-15')
    assert any(job['dataset'] == 'TaiwanStockFinancialStatements' for job in jobs)


def test_one_bad_symbol_does_not_block_all_remaining_financial_gaps(tmp_path, monkeypatch):
    output, directory = fixture_release(tmp_path, [detail('2330'), detail('2317')])
    def respond(request, **kwargs):
        if 'user_info' in request.full_url:
            return Response({'api_request_limit': 100, 'user_count': 0})
        if 'data_id=2317' in request.full_url:
            return Response({'status': 400})
        return Response({'status': 200, 'data': [{'date': '2025-03-31', 'type': 'EPS', 'value': 2}]})
    monkeypatch.setattr('urllib.request.urlopen', respond)
    monkeypatch.setattr('time.sleep', lambda value: None)
    result = supplement_snapshot(['2330', '2317'], output, '2026-10-02', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token='secret')
    assert result['completed'] == 4
    assert result['queued'] == 8  # Four failed jobs plus four incomplete source responses.
    pending = json.loads((tmp_path / 'cache' / 'state.json').read_text())['queue']
    assert len([job for job in pending if job.get('notBefore') == '2026-10-09']) == 4
    assert len([job for job in pending if job['code'] == '2317']) == 4
    assert json.loads((directory / '2330.json').read_text())['financialInputs']['incomeStatement']


def test_stale_per_and_proposed_dividends_remain_targeted_gaps():
    stock = {**detail(), 'healthInputs': {'valuationCurrent': {'date': '2026-10-01', 'pe': 20},
             'dividends': [{'year': '2025', 'cashPerShare': 2, 'confirmed': False}]}}
    jobs = plan_gaps([stock], {}, '2026-10-02')
    assert any(job['dataset'] == 'TaiwanStockPER' for job in jobs)
    assert any(job['dataset'] == 'TaiwanStockDividend' for job in jobs)


def test_finmind_dividend_preserves_quarter_and_raw_stock_action_evidence():
    from pipeline.finmind_incremental import normalize_supplement
    raw = {'date': '2026-07-01', 'year': '114年第2季', 'CashEarningsDistribution': 2,
           'CashStatutorySurplus': 0, 'StockEarningsDistribution': 1,
           'CashExDividendTradingDate': '2026-07-01', 'AnnouncementDate': '2026-06-01'}
    result = normalize_supplement(detail(), {'2330:TaiwanStockDividend': {'rows': [raw]}}, '2026-10-02')
    assert result['financialInputs']['dividend'] == [raw]
    assert result['healthInputs']['dividends'][0]['period'] == 'Q2'
    assert result['healthInputs']['dividends'][0]['year'] == 2025


def test_long_retry_after_checkpoints_instead_of_outliving_workflow(tmp_path, monkeypatch):
    state = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: (_ for _ in ()).throw(urllib.error.HTTPError('url', 503, 'unavailable', {'Retry-After': '3600'}, None)))
    waits = []
    monkeypatch.setattr('time.sleep', waits.append)
    client = FinMindClient('secret', daily_budget=state, min_interval=0)
    with pytest.raises(SourceBlocked):
        client.configure_account_budget()
    assert waits == []
    assert state.used == 1
    assert state.record['retryAfterSeconds'] == 3600


def test_elapsed_retry_after_allows_only_quota_recheck_until_verified(tmp_path, monkeypatch):
    state = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    state.configure(100, 90)
    state.block('HTTP 429', 120)
    with pytest.raises(SourceBlocked):
        state.consume()
    resumed = state.record['retryNotBefore'] + 1
    monkeypatch.setattr('time.time', lambda: resumed)
    state.consume()
    with pytest.raises(SourceBlocked):
        state.consume(require_known=True)
    state.configure(100, 100, checks_started_at=0)
    with pytest.raises(SourceBlocked):
        state.consume(require_known=True)
    state.configure(100, 0, checks_started_at=state.used)
    state.consume(require_known=True)
    assert state.used == 2


def test_verified_quota_reset_restores_window_allowance_but_not_project300(tmp_path, monkeypatch):
    state = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    state.consume()
    state.configure(600, 590)
    for _ in range(7):
        state.consume(require_known=True)
    with pytest.raises(BudgetExceeded):
        state.consume(require_known=True)
    with pytest.raises(BudgetExceeded):
        state.consume()  # Exhausted observations cannot fund repeated checks.
    now = __import__('time').time()
    monkeypatch.setattr('time.time', lambda: now + 3601)
    state.consume()
    state.configure(600, 597, checks_started_at=8)
    state.consume(require_known=True)
    with pytest.raises(BudgetExceeded):
        state.consume(require_known=True)
    state.configure(600, 0, checks_started_at=8)
    for _ in range(298):
        state.consume(require_known=True)
    assert state.rolling_used == 300 and state.used == 308
    with pytest.raises(BudgetExceeded):
        state.consume()


def test_no_retry_time_402_stays_blocked_across_midnight_until_hourly_quota_check(tmp_path, monkeypatch):
    state = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    state.block('HTTP 402')
    with pytest.raises(SourceBlocked):
        state.consume()
    recovered = DailyBudget(state.path, '2026-10-03')
    with pytest.raises(SourceBlocked):
        recovered.consume()
    now = __import__('time').time()
    monkeypatch.setattr('time.time', lambda: now + 3601)
    recovered.consume()
    recovered.configure(600, 0)
    recovered.consume(require_known=True)
    assert recovered.used == 2


def test_incomplete_cached_history_requests_missing_old_years_again():
    cache = {'2330:TaiwanStockFinancialStatements': {'rows': [{'date': '2026-06-30', 'type': 'EPS', 'value': 2}],
             'checkedPeriod': '2026-Q2', 'checkedAt': '2026-10-01'}}
    job = next(job for job in plan_gaps([detail()], cache, '2026-11-15') if job['dataset'] == 'TaiwanStockFinancialStatements')
    assert job['start_date'] == '2022-01-01'


def test_historical_supplement_keeps_actual_retrieval_time(tmp_path, monkeypatch):
    from pipeline.finmind_incremental import normalize_supplement
    cached = {'2330:TaiwanStockFinancialStatements': {'rows': [{'date': '2024-03-31', 'type': 'EPS', 'value': 2}],
              'fetchedAt': '2026-10-02T08:00:00+00:00', 'checkedAt': '2026-10-02'}}
    stock = normalize_supplement(detail(), cached, '2025-12-31')
    assert stock['healthInputs']['fetchedAt'] == '2026-10-02T08:00:00+00:00'
    assert 'availableAt' not in stock['healthInputs']['incomeQuarterly'][0]


def test_complete_dividend_uses_canonical_period_labels():
    from pipeline.finmind_incremental import complete_dividend
    quarters = [{'year': 2025, 'period': f'Q{quarter}', 'cashPerShare': 2,
                 'availableAt': '2026-06-01', 'confirmed': True} for quarter in range(1, 5)]
    assert complete_dividend(quarters, 2025, '2026-10-02')
    assert not complete_dividend(quarters[:-1], 2025, '2026-10-02')
    assert not complete_dividend(quarters, 2024, '2026-10-02')
