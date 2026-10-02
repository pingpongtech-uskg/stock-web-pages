"""Valuation evidence chains and durable queue fairness under free quota."""
import json
import urllib.parse
import urllib.error
import uuid

import pytest

from pipeline import finmind_incremental as retrieval


@pytest.fixture(autouse=True)
def fixture_clock_and_http(monkeypatch):
    monkeypatch.setattr(retrieval, 'current_taipei_day', lambda: '2026-10-02')
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    monkeypatch.setattr('urllib.request.urlopen', lambda *args, **kwargs: pytest.fail('live HTTP prohibited'))


def stock(code, *, full_eps=False, ttm=False, reported_pe=False, revenue=False):
    income = []
    if full_eps:
        income = [{'year': year, 'quarter': quarter, 'periodType': 'quarter', 'eps': 1.2 ** (year - 2022),
                   'source': 'FinMind fixture', 'amountUnit': 'TWD'}
                  for year in range(2022, 2027) for quarter in range(1, 5) if year < 2026 or quarter <= 2]
    elif ttm:
        income = [{'year': year, 'quarter': quarter, 'eps': 2, 'source': 'FinMind fixture'}
                  for year, quarter in [(2025, 3), (2025, 4), (2026, 1), (2026, 2)]]
    monthly = [{'month': f'{year}-{month:02d}', 'revenue': 120 if year == 2026 else 100,
                'source': 'TWSE fixture'} for year in [2025, 2026] for month in [6, 7, 8]] if revenue else []
    return {'code': code, 'asOf': '2026-10-02', 'lastPrice': 100,
            'priceSeries': [{'date': '2026-10-02', 'close': 100}], 'priceSource': 'TWSE fixture',
            'financialInputs': {}, 'healthInputs': {'incomeQuarterly': income, 'monthlyRevenueOfficial': monthly,
            'valuationCurrent': {'date': '2026-10-02', 'pe': 20, 'source': 'TWSE fixture'} if reported_pe else {}}}


def cold_universe():
    return [stock(str(1000 + index), full_eps=80 <= index < 89, ttm=89 <= index < 92,
                  reported_pe=index < 80, revenue=index < 12) for index in range(100)]


def release(tmp_path, details):
    output = tmp_path / 'public'
    directory = output / 'releases' / 'official' / 'stocks'
    directory.mkdir(parents=True)
    for detail in details:
        (directory / f"{detail['code']}.json").write_text(json.dumps(detail))
    (output / 'latest.json').write_text(json.dumps({'runId': 'official', 'stocks': [{'code': detail['code']} for detail in details]}))
    return output


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


def test_cold_308_job_shape_prioritizes_nine_closeable_dividend_chains_and_saves_twelve_per_calls():
    jobs = retrieval.plan_gaps(cold_universe(), {}, '2026-10-02')
    assert len(jobs) == 296  # Old 100 financial +20 PER +100 dividend +88 revenue, minus12 safe PE derivations.
    assert [(job['code'], job['dataset']) for job in jobs[:9]] == [
        (str(code), retrieval.DIVIDEND) for code in range(1080, 1089)]
    assert sum(job['dataset'] == retrieval.PER for job in jobs) == 8
    assert sum(job['dataset'] == retrieval.FINANCIAL for job in jobs) == 100


@pytest.mark.parametrize('change', ['adjusted_only', 'stale_close', 'nonconsecutive_eps', 'stock_action', 'future_eps'])
def test_pe_query_remains_when_price_or_eps_is_not_safely_derivable(change):
    detail = stock('2330', full_eps=True)
    if change == 'adjusted_only':
        detail['priceSeries'] = [{'date': '2026-10-02', 'adjustedClose': 100}]
    elif change == 'stale_close':
        detail['priceSeries'] = [{'date': '2026-10-01', 'close': 100}]
    elif change == 'nonconsecutive_eps':
        detail['healthInputs']['incomeQuarterly'] = detail['healthInputs']['incomeQuarterly'][:-2] + [
            {'year': 2026, 'quarter': 2, 'eps': 2, 'source': 'FinMind fixture'}]
    elif change == 'stock_action':
        detail['healthInputs']['dividends'] = [{'year': 2025, 'stockPerShare': 1}]
    else:
        detail['healthInputs']['incomeQuarterly'][-1]['availableAt'] = '2026-10-03'
    assert any(job['dataset'] == retrieval.PER for job in retrieval.plan_gaps([detail], {}, '2026-10-02'))


def test_tiny_free_allowance_closes_dividend_evidence_before_generic_financial_jobs(tmp_path, monkeypatch):
    output = release(tmp_path, cold_universe())
    calls = []
    def respond(request, **kwargs):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        calls.append(params)
        if not params:
            return Response({'api_request_limit': 20, 'user_count': 15})
        assert params['dataset'] == [retrieval.DIVIDEND]
        return Response({'status': 200, 'data': [{'year': '114', 'CashEarningsDistribution': 0,
                         'CashStatutorySurplus': 0, 'AnnouncementDate': '2026-03-01',
                         'CashExDividendTradingDate': '2026-07-01'}]})
    monkeypatch.setattr('urllib.request.urlopen', respond)
    result = retrieval.supplement_snapshot([detail['code'] for detail in cold_universe()], output,
        '2026-10-02', cache_dir=tmp_path / 'cache', budget_date='2026-10-02', token=str(uuid.uuid4()))
    assert result['requests'] == 4 and result['completed'] == 3
    assert [params['data_id'][0] for params in calls[1:]] == ['1080', '1081', '1082']
    for code in ['1080', '1081', '1082']:
        detail = json.loads((output / 'releases' / 'official' / 'stocks' / f'{code}.json').read_text())
        assert retrieval.complete_dividend(detail['healthInputs']['dividends'], 2025, '2026-10-02')
    checkpoint = json.loads((tmp_path / 'cache' / 'state.json').read_text())
    assert checkpoint['queue'] and checkpoint['days']['2026-10-02']['attempts'] == 4


def test_failed_first_symbol_moves_behind_pending_jobs_on_next_day(tmp_path, monkeypatch):
    output = release(tmp_path, [stock('1000'), stock('1001'), stock('1002')])
    day = ['2026-10-02']
    monkeypatch.setattr(retrieval, 'current_taipei_day', lambda: day[0])
    data_calls = []
    def respond(request, **kwargs):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        if not params:
            return Response({'api_request_limit': 100, 'user_count': 0})
        data_calls.append(params['data_id'][0])
        raise urllib.error.URLError('fixture outage')
    monkeypatch.setattr('urllib.request.urlopen', respond)
    kwargs = {'cache_dir': tmp_path / 'cache', 'max_requests': 4, 'token': str(uuid.uuid4())}
    first = retrieval.supplement_snapshot(['1000', '1001', '1002'], output, '2026-10-02', budget_date=day[0], **kwargs)
    assert data_calls == ['1000'] * 3 and first['requests'] == 4
    day[0] = '2026-10-03'
    second = retrieval.supplement_snapshot(['1000', '1001', '1002'], output, '2026-10-02', budget_date=day[0], **kwargs)
    assert data_calls[3:] == ['1001'] * 3
    assert second['requests'] == 4
    checkpoint = json.loads((tmp_path / 'cache' / 'state.json').read_text())
    assert checkpoint['days']['2026-10-02']['attempts'] == 4
    assert checkpoint['days']['2026-10-03']['attempts'] == 4


@pytest.mark.parametrize('row', [
    {'cashPerShare': -1, 'availableAt': '2026-01-01'},
    {'cashPerShare': 2, 'availableAt': ''},
    {'cashPerShare': 2, 'availableAt': '2026-01-invalid'},
    {'cashPerShare': 2, 'availableAt': '2026-10-03'},
])
def test_dividend_planner_does_not_accept_evidence_producer_rejects(row):
    evidence = {'year': 2025, 'period': 'annual', 'confirmed': True, **row}
    assert retrieval.complete_dividend([evidence], 2025, '2026-10-02') is False


def test_dividend_planner_accepts_approved_known_zero_with_canonical_period():
    assert retrieval.complete_dividend([{'year': '114', 'period': 'annual', 'confirmed': True,
        'cashPerShare': 0, 'approvedAt': '2026-03-01'}], 2025, '2026-10-02') is True


def test_resume_queue_keeps_failed_urgent_behind_older_pending_and_prunes_obsolete_jobs():
    def job(code, dataset, priority, period='2026'):
        return {'code': code, 'dataset': dataset, 'priority': priority, 'period': period,
                'start_date': '2025-01-01', 'end_date': '2026-10-02'}
    old_financial = job('1000', retrieval.FINANCIAL, '1')
    failed_dividend = {**job('1001', retrieval.DIVIDEND, '0'), 'attempted': 'true'}
    obsolete = job('1002', retrieval.PER, '2', '2026-10-01')
    fresh_dividend = job('1003', retrieval.DIVIDEND, '0')
    fresh_per = job('1002', retrieval.PER, '2', '2026-10-02')
    result = retrieval.resume_queue([old_financial, failed_dividend, fresh_dividend, fresh_per],
                                    [old_financial, obsolete, failed_dividend])
    assert [item['code'] for item in result] == ['1003', '1000', '1001', '1002']
    assert result[2]['attempted'] == 'true'
    assert all(item['period'] != '2026-10-01' for item in result)


def test_stock_distribution_reopens_financial_basis_gap_even_with_reported_pe_and_full_profit_history():
    detail = stock('2330', full_eps=True, reported_pe=True, revenue=True)
    detail['healthInputs']['incomeQuarterly'] = [{**row, 'grossProfit': 10, 'operatingProfit': 5,
        'pretaxProfit': 4, 'netIncome': 3} for row in detail['healthInputs']['incomeQuarterly']]
    detail['healthInputs']['dividends'] = [{'year': 2025, 'stockPerShare': 1}]
    jobs = retrieval.plan_gaps([detail], {}, '2026-10-02')
    assert any(job['dataset'] == retrieval.FINANCIAL for job in jobs)
    assert not any(job['priority'] == '0' for job in jobs)


@pytest.mark.parametrize('per_rows, deferred_count', [
    ([{'date': '2026-10-02', 'PER': 20}], 3),
    ([], 4),
    ([{'date': '2026-10-03', 'PER': 20}], 4),
    ([{'date': '2026-10-02', 'PER': 0}], 4),
    ([{'date': '2026-10-02', 'PER': 'NaN'}], 4),
])
def test_incomplete_sources_keep_bounded_calendar_retry_queue(tmp_path, monkeypatch, per_rows, deferred_count):
    output = release(tmp_path, [stock('2330')])
    day = ['2026-10-02']
    monkeypatch.setattr(retrieval, 'current_taipei_day', lambda: day[0])
    calls = []
    def respond(request, **kwargs):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        calls.append(params)
        if not params:
            return Response({'api_request_limit': 1000, 'user_count': 0})
        assert params['end_date'] == ['2026-10-02']  # Historical recovery preserves its original cutoff.
        dataset = params['dataset'][0]
        rows = {
            retrieval.FINANCIAL: [{'date': '2026-06-30', 'type': 'EPS', 'value': 3}],
            retrieval.PER: per_rows,
            retrieval.DIVIDEND: [{'year': '114年上半年', 'CashEarningsDistribution': 2,
                'CashStatutorySurplus': 0, 'AnnouncementDate': '2026-03-01', 'CashExDividendTradingDate': '2026-07-01'}],
            retrieval.REVENUE: [],
        }[dataset]
        return Response({'status': 200, 'data': rows})
    monkeypatch.setattr('urllib.request.urlopen', respond)
    kwargs = {'cache_dir': tmp_path / 'cache', 'token': str(uuid.uuid4())}
    first = retrieval.supplement_snapshot(['2330'], output, '2026-10-02', budget_date=day[0], **kwargs)
    assert first['requests'] == 5 and first['queued'] == deferred_count
    cache = json.loads((tmp_path / 'cache' / 'rows.json').read_text())
    incomplete = [retrieval.FINANCIAL, retrieval.DIVIDEND, retrieval.REVENUE] + ([retrieval.PER] if deferred_count == 4 else [])
    for dataset in incomplete:
        assert cache[f'2330:{dataset}']['nextCheckAt'] == '2026-10-09'
    assert all(job['notBefore'] == '2026-10-09' for job in json.loads((tmp_path / 'cache' / 'state.json').read_text())['queue'])
    for recovery_day in ['2026-10-02', '2026-10-08']:
        day[0] = recovery_day
        previous_calls = len(calls)
        deferred = retrieval.supplement_snapshot(['2330'], output, '2026-10-02', budget_date=day[0], **kwargs)
        assert deferred['queued'] == deferred_count and deferred['skipped'] == 'deferred'
        assert len(calls) == previous_calls
    day[0] = '2026-10-09'
    previous_calls = len(calls)
    recovered = retrieval.supplement_snapshot(['2330'], output, '2026-10-02', budget_date=day[0], **kwargs)
    assert len(calls) - previous_calls == deferred_count + 1  # One counted quota check plus due gaps.
    assert recovered['requests'] == deferred_count + 1 and recovered['queued'] == deferred_count
    ledger = json.loads((tmp_path / 'cache' / 'state.json').read_text())
    assert ledger['days']['2026-10-02']['attempts'] == 5
    assert ledger['days']['2026-10-09']['attempts'] == deferred_count + 1
