"""CLI and publication-boundary checks; all HTTP uses synthetic fixture responses."""
from __future__ import annotations

import copy
import json
import runpy
import sys
import urllib.parse
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest

from scripts import fetch_finmind as cli

TOKEN = str(uuid.uuid4())  # Generated fixture authentication; never sent to live HTTP.


class Response:
    headers = {}
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return json.dumps(self.body).encode()


def invoke(monkeypatch, *args):
    monkeypatch.setattr(sys, 'argv', ['fetch_finmind.py', *map(str, args)])
    return cli.main()


def baseline(tmp_path, codes=('2330', '2317')):
    output = tmp_path / 'data'
    directory = output / 'releases' / 'official' / 'stocks'
    directory.mkdir(parents=True)
    details = {}
    for code in codes:
        detail = {'code': code, 'asOf': '2026-10-02', 'lastPrice': 100, 'healthInputs': {},
                  'financialInputs': {'incomeStatement': [{'date': '2022-03-31', 'type': 'EPS', 'value': 1}]}}
        path = directory / f'{code}.json'
        path.write_text(json.dumps(detail))
        details[code] = path.read_bytes()
    latest = {'runId': 'official', 'marketDate': '2026-10-02', 'stocks': [{'code': code} for code in codes], 'rankings': {}}
    (output / 'latest.json').write_text(json.dumps(latest))
    return output, details


@pytest.fixture(autouse=True)
def forbid_live_http(monkeypatch):
    class FixtureDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 2, 18, 0, tzinfo=cli.TAIPEI).astimezone(tz)

    monkeypatch.setattr(cli, 'datetime', FixtureDateTime)
    monkeypatch.setattr('pipeline.finmind_incremental.current_taipei_day', lambda: '2026-10-02', raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail('CLI test attempted live HTTP')
    monkeypatch.setattr('urllib.request.urlopen', forbidden)
    monkeypatch.setattr('time.sleep', lambda duration: None)


@pytest.mark.parametrize('flags', [[], ['--supplement']])
def test_free_cli_requires_existing_public_baseline(tmp_path, monkeypatch, capsys, flags):
    monkeypatch.setenv('FINMIND_TOKEN', TOKEN)
    assert invoke(monkeypatch, *flags, '--codes', '2330', '--output', tmp_path / 'missing',
                  '--cache-dir', tmp_path / 'cache', '--budget-date', '2026-10-02') == 1
    assert 'Public snapshot missing' in capsys.readouterr().err
    assert not (tmp_path / 'missing' / 'latest.json').exists()


def test_missing_token_keeps_complete_public_universe_and_financial_history(tmp_path, monkeypatch, capsys):
    output, originals = baseline(tmp_path)
    monkeypatch.delenv('FINMIND_TOKEN', raising=False)
    previous_latest = (output / 'latest.json').read_bytes()
    assert invoke(monkeypatch, '--supplement', '--codes', '2330,2317', '--output', output,
                  '--cache-dir', tmp_path / 'cache', '--budget-date', '2026-10-02', '--as-of', '2026-10-02') == 0
    result = json.loads(capsys.readouterr().out)
    assert result['skipped'] == 'missing_token'
    assert result['requests'] == 0
    assert (output / 'latest.json').read_bytes() == previous_latest
    assert all((output / 'releases' / 'official' / 'stocks' / f'{code}.json').read_bytes() == raw for code, raw in originals.items())
    assert json.loads((tmp_path / 'cache' / 'state.json').read_bytes())['queue']


def test_unknown_source_quota_stops_before_any_data_get(tmp_path, monkeypatch, capsys):
    output, originals = baseline(tmp_path)
    monkeypatch.setenv('FINMIND_TOKEN', TOKEN)
    requests = []
    def unknown(request, **kwargs):
        requests.append(request.full_url)
        assert request.get_header('Authorization') == f'Bearer {TOKEN}'
        return Response({'status': 200})
    monkeypatch.setattr('urllib.request.urlopen', unknown)
    assert invoke(monkeypatch, '--codes', '2330,2317', '--output', output, '--cache-dir', tmp_path / 'cache', '--budget-date', '2026-10-02') == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert len(requests) == 1 and requests[0].endswith('/v2/user_info')
    assert result['requests'] == 1 and result['skipped'] == 'FinMindError'
    assert TOKEN not in captured.out + captured.err
    assert all((output / 'releases' / 'official' / 'stocks' / f'{code}.json').read_bytes() == raw for code, raw in originals.items())


def test_real_cli_uses_actual_quota_preserves_same_day_budget_and_only_fills_gaps(tmp_path, monkeypatch, capsys):
    output, _ = baseline(tmp_path)
    monkeypatch.setenv('FINMIND_TOKEN', TOKEN)
    requests = []
    def respond(request, **kwargs):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        requests.append(params)
        assert request.get_header('Authorization') == f'Bearer {TOKEN}'
        if not params:
            return Response({'status': 200, 'api_request_limit': 20, 'user_count': 15})
        assert params['end_date'] == ['2026-10-02']
        assert params['data_id'][0] in {'2330', '2317'}
        if params['dataset'] == ['TaiwanStockFinancialStatements']:
            assert params['start_date'] == ['2022-01-01']
            return Response({'status': 200, 'data': [{'date': '2026-06-30', 'type': 'EPS', 'value': 3}]})
        return Response({'status': 200, 'data': []})
    monkeypatch.setattr('urllib.request.urlopen', respond)
    args = ['--supplement', '--codes', '2330,2317', '--output', output, '--cache-dir', tmp_path / 'cache',
            '--budget-date', '2026-10-02', '--as-of', '2026-10-02', '--max-requests', '300', '--max-runtime-seconds', '1500']
    assert invoke(monkeypatch, *args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first['requests'] == 4 and first['allowed_attempts'] == 4
    assert first['skipped'] == 'BudgetExceeded'
    assert [item.get('dataset', [None])[0] for item in requests[:3]] == [None, 'TaiwanStockFinancialStatements', 'TaiwanStockFinancialStatements']
    assert not any(item.get('dataset', [''])[0] in {'TaiwanStockInfo', 'TaiwanStockPrice', 'TaiwanStockBalanceSheet', 'TaiwanStockCashFlowsStatement'} for item in requests)
    for code in ['2330', '2317']:
        detail = json.loads((output / 'releases' / 'official' / 'stocks' / f'{code}.json').read_bytes())
        assert {row['date'] for row in detail['financialInputs']['incomeStatement']} == {'2022-03-31', '2026-06-30'}
    assert invoke(monkeypatch, *args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second['requests'] == 4  # Exhausted active observation permits no extra HTTP.
    assert len(requests) == 4
    assert json.loads((output / 'latest.json').read_bytes())['runId'] == 'official'


def test_cli_forwards_one_explicit_durable_contract_and_deduplicates_codes(tmp_path, monkeypatch, capsys):
    from pipeline import finmind_incremental
    seen = []
    def boundary(codes, output, as_of, **kwargs):
        seen.append((codes, output, as_of, kwargs))
        return {'requests': 0, 'queued': 1}
    monkeypatch.setattr(finmind_incremental, 'supplement_snapshot', boundary)
    assert invoke(monkeypatch, '--supplement', '--codes', ' 2330,2317,2330 ', '--output', tmp_path / 'data',
                  '--cache-dir', tmp_path / 'cache', '--budget-date', '2026-10-02', '--as-of', '2026-10-01',
                  '--max-requests', '12', '--max-runtime-seconds', '25') == 0
    assert seen == [(['2330', '2317'], tmp_path / 'data', '2026-10-01',
                     {'cache_dir': tmp_path / 'cache', 'budget_date': '2026-10-02', 'max_requests': 12, 'max_runtime_seconds': 25})]
    assert json.loads(capsys.readouterr().out)['queued'] == 1


@pytest.mark.parametrize('args', [
    ['--codes', '../outside', '--seed-only'],
    ['--codes', '2330', '--seed-only', '--as-of', 'yesterday'],
    ['--codes', '2330', '--seed-only', '--budget-date', '20261002'],
    ['--codes', '2330', '--supplement', '--seed-only'],
    ['--codes', ''],
    ['--codes', '2330', '--budget-date', '2026-10-03'],
    ['--codes', '2330', '--budget-date', '2026-10-01'],
    ['--codes', '2330', '--as-of', '2026-10-03'],
    ['--codes', '2330', '--max-requests', '0'],
    ['--codes', '2330', '--max-requests', '301'],
    ['--codes', '2330', '--max-runtime-seconds', '0'],
    ['--codes', '2330', '--max-runtime-seconds', '-1'],
    ['--codes', '2330', '--max-runtime-seconds', 'invalid'],
])
def test_cli_rejects_invalid_input_before_files_or_http(tmp_path, monkeypatch, args):
    with pytest.raises(SystemExit) as raised:
        invoke(monkeypatch, *args, '--output', tmp_path / 'data', '--cache-dir', tmp_path / 'cache')
    assert raised.value.code == 2
    assert not (tmp_path / 'data').exists()
    assert not (tmp_path / 'cache').exists()


def test_seed_accepts_explicit_historical_date_without_creating_budget(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    assert invoke(monkeypatch, '--seed-only', '--codes', '2330', '--as-of', '2025-10-02',
                  '--budget-date', '2025-10-02', '--output', tmp_path / 'data', '--cache-dir', tmp_path / 'cache') == 0
    assert json.loads(capsys.readouterr().out)['market_date'] == '2025-10-02'
    assert not (tmp_path / 'cache').exists()


def test_seed_cli_creates_unknown_baseline_without_spending_free_quota(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('FINMIND_TOKEN', TOKEN)
    config = tmp_path / 'config'; config.mkdir()
    (config / 'tracked_symbols.json').write_text(json.dumps({'symbols': ['2330'], 'metadata': {'2330': {'name': '台積電', 'market': 'TWSE', 'sector': '半導體'}}, 'universe': {'sourceUrl': 'https://openapi.twse.com.tw'}}))
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    assert invoke(monkeypatch, '--seed-only', '--codes', '2330', '--as-of', '2026-10-02', '--output', tmp_path / 'data') == 0
    result = json.loads(capsys.readouterr().out)
    latest = json.loads((tmp_path / 'data' / 'latest.json').read_bytes())
    detail = json.loads((tmp_path / 'data' / 'releases' / result['run_id'] / 'stocks' / '2330.json').read_bytes())
    assert result['requests'] == 0 and latest['freshness'] == 'degraded'
    assert latest['marketDate'] == '2026-10-02'
    assert latest['rankings'] == {'trust': [], 'growth': [], 'lowPosition': []}
    assert detail['name'] == '台積電' and detail['lastPrice'] is None
    assert detail['regression']['signalEligible'] is False
    assert detail['qualityStatus'] == 'unknown'
    assert TOKEN not in json.dumps(latest) + json.dumps(detail)


def test_script_entrypoint_executes_seed_and_handles_missing_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['fetch_finmind.py', '--seed-only', '--codes', '2330', '--output', str(tmp_path / 'data'), '--as-of', '2026-10-02'])
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(Path(cli.__file__)), run_name='__main__')
    assert raised.value.code == 0
    assert json.loads(capsys.readouterr().out)['requests'] == 0


def test_legacy_build_callable_uses_supplement_not_per_stock_six_dataset_loop(tmp_path, monkeypatch):
    from pipeline import finmind_incremental
    calls = []
    monkeypatch.setattr(finmind_incremental, 'supplement_snapshot', lambda *args, **kwargs: calls.append((args, kwargs)) or {'requests': 0})
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    assert cli.build_snapshot(['2330'], tmp_path / 'data', '2026-10-02') == {'requests': 0}
    assert len(calls) == 1
    assert calls[0][1]['cache_dir'] == tmp_path / '.cache' / 'finmind'
    date.fromisoformat(calls[0][1]['budget_date'])


def test_observed_raw_data_stays_proxy_and_financial_quality_unknown():
    metadata = cli.info_map([
        {'stock_id': '2330', 'stock_name': '舊名稱', 'date': '2025-01-01', 'type': 'twse'},
        {'stock_id': '2330', 'stock_name': '台積電', 'date': '2026-01-01', 'type': 'listed', 'industry_category': '半導體'},
        {'stock_id': '2330', 'stock_name': '更舊名稱', 'date': '2024-01-01', 'type': 'twse'},
        {'stock_id': '3293', 'stock_name': '鈊象', 'date': '2026-01-01', 'type': 'otc'},
        {'stock_id': '9999', 'stock_name': '未知市場', 'type': 'unexpected'}, {'stock_id': ''},
    ])
    raw_prices = [{'date': f'2026-09-{day:02}', 'close': 100 + day + (5 if day == 16 else 0),
                   'Trading_Volume': 1000, 'Trading_money': '30,000,000'} for day in range(1, 21)]
    prices = cli.price_points([*raw_prices, {'date': 'bad', 'close': 20}, {'date': '2026-09-21', 'close': 0},
                               {'date': '2026-09-22', 'close': 'NaN'}])
    assert len(prices) == 20 and prices[-1]['close'] == 120
    assert metadata['2330']['name'] == '台積電'
    assert metadata['3293']['market'] == 'TPEx' and metadata['9999']['market'] == 'unknown'
    institutional = [{'date': point['date'], 'name': 'Investment_Trust', 'buy': 100, 'sell': 10} for point in prices[-10:]]
    institutional += [{'date': prices[-1]['date'], 'name': 'Foreign_Investor', 'buy': 999999, 'sell': 0},
                      {'date': 'bad', 'name': 'Investment_Trust', 'buy': 9, 'sell': 0}]
    daily, trust = cli.institution_window(prices, institutional)
    assert trust['net_shares_10'] == 900 and trust['participation_10'] == 0.09
    monthly = [{'revenue_year': year, 'revenue_month': month, 'revenue': value, 'create_time': '2026-10-10'}
               for year, values in [(2025, [100, 100, 100]), (2026, [110, 120, 130])]
               for month, value in zip([7, 8, 9], values)]
    revenues, growth = cli.revenue_window([*monthly, {'revenue_year': 2026, 'revenue_month': 13, 'revenue': 1}])
    assert growth == pytest.approx(0.2)
    assert revenues[-1]['availableAt'] == '2026-10-10'
    raw_financial = {'incomeStatement': [{'date': '2026-06-30', 'type': 'EPS', 'value': 3}]}
    stock = cli.make_stock('2330', metadata['2330'], prices, daily, trust, revenues, growth,
                           ['optional_data_unavailable'], raw_financial)
    assert stock['lastPrice'] == 120 and stock['changePct'] == pytest.approx(1 / 119)
    assert stock['liquidityStatus'] == 'pass'
    assert stock['institutionNetShares10'] == 900
    assert stock['regression']['signalEligible'] is False
    assert stock['regression']['status'] == 'unknown'
    assert stock['qualityStatus'] == 'unknown'
    assert stock['healthInputs']['incomeQuarterly'][0]['eps'] == 3
    assert all(check['status'] == 'unknown' for check in stock['qualityChecks'])
    assert '部分資料集請求未完成' in stock['risks']
    assert len(stock['priceSeries'][-1]['bands']) == 5


def test_partial_market_inputs_do_not_promote_formal_candidates():
    prices = cli.price_points([{'date': '2026-10-01', 'close': 100, 'Trading_Volume': 1000},
                               {'date': '2026-10-02', 'close': 105, 'Trading_Volume': 1000}])
    daily, trust = cli.institution_window(prices, [])
    assert trust['status'] == 'unknown' and all(row['netShares'] is None for row in daily)
    stock = cli.make_stock('2330', {}, prices, daily,
                           {'status': 'pass', 'net_shares_10': 900, 'participation_10': 0.09}, [], None, [])
    assert stock['liquidityStatus'] == 'unknown'
    assert stock['regression']['signalEligible'] is False
    assert cli.ranking_row(stock, 'trust')['status'] == 'unknown'
    assert cli.ranking_row(stock, 'growth')['value'] is None
    assert cli.ranking_row(stock, 'lowPosition')['status'] == 'unknown'
    assert cli.rank([cli.ranking_row(stock, 'growth')], reverse=True) == []


def test_revenue_comparison_requires_matching_prior_three_months():
    rows = [{'revenue_year': 2026, 'revenue_month': month, 'revenue': 100} for month in [7, 8, 9]]
    assert cli.revenue_window(rows[:2])[1] is None
    assert cli.revenue_window(rows)[1] is None
    assert cli.as_float('') is None and cli.as_float('bad') is None
    assert cli.as_int(None) is None
    assert cli.parse_day('invalid') is None
    assert cli.subtract_years(date(2024, 2, 29), 1) == date(2023, 2, 28)
    assert cli.subtract_years(date(2026, 10, 2), 4) == date(2022, 10, 2)


def test_ranking_ties_are_stable_and_missing_measurements_are_excluded():
    stock = {'code': '2330', 'name': '台積電', 'sector': '半導體', 'participation10': 0.02,
             'entryReasons': ['published ten-day evidence'], 'liquidityStatus': 'pass', 'revenueGrowth3m': 0.1, 'zScore': -1}
    trust = cli.ranking_row(stock, 'trust')
    assert trust['value'] == 2 and trust['status'] == 'pass'
    growth = cli.ranking_row(stock, 'growth')
    assert growth['value'] == 10 and growth['status'] == 'unknown'
    rows = [{**growth, 'code': '2330'}, {**growth, 'code': '2317'}, {**growth, 'code': '9999', 'value': None}]
    assert [row['code'] for row in cli.rank(copy.deepcopy(rows), reverse=True)] == ['2317', '2330']
    assert [row['rank'] for row in cli.rank(copy.deepcopy(rows), reverse=False)] == [1, 2]


@pytest.mark.parametrize('content', [None, 'broken', '{}', '[]', '{"symbols":{}}', '{"symbols":["2330","2330"," 2317 ",""]}'])
def test_unavailable_or_invalid_universe_config_is_not_invented(tmp_path, monkeypatch, content):
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    if content is not None:
        (tmp_path / 'config').mkdir()
        (tmp_path / 'config' / 'tracked_symbols.json').write_text(content)
    expected = ['2330', '2317'] if content and '2317' in content else []
    assert cli.load_tracked_codes() == expected


def test_seed_missing_config_retains_explicit_codes_without_claiming_market_data(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'ROOT', tmp_path)
    output = tmp_path / 'data'
    result = cli.seed_snapshot(['2330', '2317'], output, '2026-10-02')
    latest = json.loads((output / 'latest.json').read_bytes())
    assert result['stocks'] == 2 and latest['coverage']['priceCompleteCount'] == 0
    assert all(row['lastPrice'] is None for row in latest['stocks'])
