"""Restored public evidence fills inputs, never a fresh market snapshot."""
import copy
import json
from pathlib import Path

import pytest
from scripts import refresh_snapshot as refresh


SOURCE = {'requestId': 'captured:20261001:v1', 'actionsRunId': '123456', 'sourceGitCommit': 'a' * 40}


def install(root, day='2026-10-01', code='2330', **changes):
    directory = root / day
    directory.mkdir(parents=True, exist_ok=True)
    metadata = {'marketDate': day, 'source': SOURCE, 'codes': [code]}
    (directory / 'restore-metadata.json').write_text(json.dumps(metadata))
    income = [{'date': f'{year}-{month:02d}-{last}', 'type': field, 'value': value}
              for year in range(2022, 2027) for month, last in [(3, '31'), (6, '30'), (9, '30'), (12, '31')]
              for field, value in [('EPS', year - 2020), ('GrossProfit', 100), ('OperatingIncome', 80), ('PreTaxIncome', 70), ('IncomeAfterTaxes', 60)]]
    evidence = {'code': code, 'asOf': day, 'lastPrice': 999, 'priceSeries': [{'date': day, 'close': 999}],
                'institutionNetShares10': 999, 'growthValuation': {'status': 'available'},
                'financialInputs': {'incomeStatement': income},
                'healthInputs': {'valuationCurrent': {'date': day, 'pe': 99},
                  'incomeQuarterly': [{'year': 2025, 'quarter': 2, 'grossProfit': 101, 'amountUnit': 'TWD', 'periodType': 'quarter'}],
                  'dividends': [{'year': 2025, 'period': 'annual', 'cashPerShare': 2, 'confirmed': True, 'approvedAt': '2026-06-01'}],
                  'monthlyRevenueOfficial': [{'month': '2026-08', 'revenue': 120}, {'month': '2026-09', 'revenue': 130, 'availableAt': '2026-10-10'}]},
                'revenueMonthly': [{'month': '2026-08', 'revenue': 120}, {'month': '2026-09', 'revenue': 130, 'availableAt': '2026-10-10'}]}
    evidence.update(changes)
    (directory / (code + '.json')).write_text(json.dumps(evidence))
    return directory, evidence


def test_restored_financial_history_fills_inputs_without_copying_cached_market_metrics(tmp_path):
    root = tmp_path / 'cache'
    install(root)
    baseline = {'code': '2330', 'asOf': '2026-10-02', 'lastPrice': 100,
                'priceSeries': [{'date': '2026-10-02', 'close': 100}], 'institutionNetShares10': 1,
                'financialInputs': {'incomeStatement': [{'date': '2025-06-30', 'type': 'EPS', 'value': 9}]},
                'healthInputs': {'incomeQuarterly': [{'year': 2025, 'quarter': 2, 'grossProfit': 150, 'periodType': 'quarter', 'amountUnit': 'TWD'}]}}
    original = copy.deepcopy(baseline)
    result = refresh.merge_restored_stock_inputs([baseline], root, as_of='2026-10-02')[0]
    assert baseline == original
    for key in ['asOf', 'lastPrice', 'priceSeries', 'institutionNetShares10']:
        assert result[key] == baseline[key]
    assert 'growthValuation' not in result
    assert not result['healthInputs'].get('valuationCurrent')
    quarter = next(row for row in result['healthInputs']['incomeQuarterly'] if (row['year'], row['quarter']) == (2025, 2))
    assert quarter['grossProfit'] == 150 and quarter['eps'] == 9
    assert len(result['financialInputs']['incomeStatement']) > 1
    assert result['healthInputs']['dividends'][0]['cashPerShare'] == 2
    assert [row['month'] for row in result['revenueMonthly']] == ['2026-08']
    assert not any(row['year'] == 2026 and row['quarter'] >= 3 for row in result['healthInputs']['incomeQuarterly'])
    from pipeline.valuation import derive_ttm_eps
    assert derive_ttm_eps(result['healthInputs']['incomeQuarterly'], as_of='2026-10-02') is not None


def test_restored_known_future_and_unknown_publication_periods_are_excluded(tmp_path):
    root = tmp_path / 'cache'
    install(root, financialInputs={'incomeStatement': [{'date': '2026-06-30', 'type': 'EPS', 'value': 9, 'availableAt': '2026-10-03'}]},
            healthInputs={'incomeQuarterly': [{'year': 2026, 'quarter': 2, 'eps': 9, 'availableAt': '2026-10-03'}, {'year': 2026, 'quarter': 3, 'eps': 99}],
                          'dividends': [{'year': 2025, 'period': 'annual', 'cashPerShare': 2, 'confirmed': True, 'approvedAt': '2026-06-01', 'availableAt': '2026-10-03'}]},
            revenueMonthly=[{'month': '2026-09', 'revenue': 99}])
    result = refresh.merge_restored_stock_inputs([{'code': '2330'}], root, as_of='2026-10-02')[0]
    assert result['financialInputs']['incomeStatement'] == []
    assert not result['healthInputs'].get('incomeQuarterly')
    assert not result['healthInputs'].get('dividends')
    assert result['revenueMonthly'] == []


def test_empty_or_future_only_restored_cache_preserves_baseline(tmp_path):
    baseline = [{'code': '2330', 'lastPrice': None}]
    assert refresh.merge_restored_stock_inputs(baseline, tmp_path / 'absent', as_of='2026-10-02') == baseline
    install(tmp_path / 'future', day='2026-10-03')
    assert refresh.merge_restored_stock_inputs(baseline, tmp_path / 'future', as_of='2026-10-02') == baseline


@pytest.mark.parametrize('bad', ['wrong_code', 'wrong_asof', 'bad_metadata', 'symlink'])
def test_restored_present_invalid_installation_fails_closed(tmp_path, bad):
    root = tmp_path / 'cache'
    directory, evidence = install(root)
    file = directory / '2330.json'
    if bad == 'wrong_code':
        file.write_text(json.dumps({**evidence, 'code': '1234'}))
    elif bad == 'wrong_asof':
        file.write_text(json.dumps({**evidence, 'asOf': '2026-10-02'}))
    elif bad == 'bad_metadata':
        (directory / 'restore-metadata.json').write_text('{}')
    else:
        file.rename(directory / 'outside.json'); file.symlink_to(directory / 'outside.json')
    with pytest.raises(ValueError):
        refresh.merge_restored_stock_inputs([{'code': '2330'}], root, as_of='2026-10-02')


def test_fresh_producer_receives_restored_financial_evidence_and_fresh_public_overlay(tmp_path, monkeypatch):
    root = tmp_path / 'cache'; install(root)
    data = tmp_path / 'public' / 'data'; data.mkdir(parents=True)
    baseline = {'code': '2330', 'market': 'TWSE', 'asOf': '2026-10-01', 'lastPrice': 80}
    (data / 'latest.json').write_text(json.dumps({'runId': 'baseline', 'stocks': [baseline]}))
    fresh = {'incomeQuarterly': [{'year': 2026, 'quarter': 2, 'eps': 3, 'availableAt': '2026-08-14'}]}
    monkeypatch.setattr(refresh, 'build_health_inputs', lambda codes: {'2330': fresh})
    received = []
    def inspect(detail, **kwargs):
        received.append((detail, kwargs))
        raise RuntimeError('stop after producer input boundary')
    monkeypatch.setattr(refresh, 'enrich_detail', inspect)
    with pytest.raises(RuntimeError, match='producer input boundary'):
        refresh.build_release(data, [], as_of='2026-10-02', offline=False, stock_cache_dir=root)
    detail, kwargs = received[0]
    assert kwargs['end'].isoformat() == '2026-10-02' and kwargs['public_inputs'] == fresh
    assert detail['asOf'] == '2026-10-01' and detail['lastPrice'] == 80
    assert detail['healthInputs']['incomeQuarterly'] and detail['financialInputs']['incomeStatement']
    assert not detail['priceSeries']


def test_cli_forwards_restored_stock_root_without_network(tmp_path, monkeypatch):
    import sys
    calls = []
    monkeypatch.setattr(sys, 'argv', ['refresh_snapshot', '--as-of', '2026-10-02', '--stock-cache-dir', str(tmp_path)])
    monkeypatch.setattr(refresh, 'build_release', lambda *args, **kwargs: calls.append(kwargs) or {'status': 'test'})
    assert refresh.main() == 0
    assert calls[0]['stock_cache_dir'] == tmp_path


def test_restored_future_dividend_period_does_not_enter_current_inputs(tmp_path):
    root = tmp_path / 'cache'
    install(root, healthInputs={'dividends': [{'year': 2027, 'period': 'annual', 'cashPerShare': 9, 'confirmed': True, 'approvedAt': '2026-06-01'}]}, financialInputs={}, revenueMonthly=[])
    result = refresh.merge_restored_stock_inputs([{'code': '2330'}], root, as_of='2026-10-02')[0]
    assert not result['healthInputs'].get('dividends')


@pytest.mark.parametrize('section', ['healthInputs', 'financialInputs', 'revenueMonthly'])
def test_restored_malformed_input_sections_fail_with_valueerror(tmp_path, section):
    root = tmp_path / 'cache'
    install(root, **{section: 'malformed'})
    with pytest.raises(ValueError):
        refresh.merge_restored_stock_inputs([{'code': '2330'}], root, as_of='2026-10-02')


def test_future_baseline_financial_overlay_cannot_erase_eligible_restored_quarter(tmp_path):
    root = tmp_path / 'cache'; install(root)
    baseline = {'code': '2330', 'financialInputs': {'incomeStatement': [{'date': '2025-06-30', 'type': 'EPS', 'value': 99, 'availableAt': '2026-10-03'}]},
                'healthInputs': {'incomeQuarterly': [{'year': 2025, 'quarter': 2, 'eps': 99, 'availableAt': '2026-10-03'}]}}
    result = refresh.merge_restored_stock_inputs([baseline], root, as_of='2026-10-02')[0]
    quarter = next(row for row in result['healthInputs']['incomeQuarterly'] if (row['year'], row['quarter']) == (2025, 2))
    assert quarter['eps'] == 5
    assert not quarter.get('availableAt')


def test_restored_source_provenance_survives_without_raw_finmind_rows(tmp_path):
    root = tmp_path / 'cache'
    install(root, financialInputs={}, revenueMonthly=[], healthInputs={'source': 'TWSE OpenAPI',
            'fetchedAt': '2026-10-01T01:00:00+00:00',
            'incomeQuarterly': [{'year': 2025, 'quarter': 2, 'eps': 2, 'periodType': 'quarter', 'amountUnit': 'TWD_thousands'}]})
    result = refresh.merge_restored_stock_inputs([{'code': '2330'}], root, as_of='2026-10-02')[0]
    assert result['healthInputs']['source'] == 'TWSE OpenAPI'
    assert result['healthInputs']['fetchedAt'] == '2026-10-01T01:00:00+00:00'


def test_restored_ytd_recovers_exact_standalone_quarter_but_does_not_make_ttm_complete(tmp_path):
    root = tmp_path / 'cache'
    cumulative = [{'year': year, 'quarter': quarter, 'grossProfit': value * scale,
                   'operatingProfit': value * scale, 'pretaxProfit': value * scale, 'netIncome': value * scale,
                   'periodType': 'ytd', 'statementScope': 'consolidated', 'amountUnit': 'TWD_thousands', 'source': 'TWSE OpenAPI'}
                  for year, scale in [(2025, 1), (2026, 2)] for quarter, value in [(1, 100), (2, 250)]]
    install(root, financialInputs={}, healthInputs={'incomeYtd': cumulative}, revenueMonthly=[])
    detail = refresh.merge_restored_stock_inputs([{'code': '2330'}], root, as_of='2026-10-02')[0]
    quarter = next(row for row in detail['healthInputs']['incomeQuarterly'] if (row['year'], row['quarter']) == (2026, 2))
    assert quarter['grossProfit'] == 300 and quarter['inputOrigin'] == 'derived'
    from pipeline.growth_health import evaluate_growth_health
    assert evaluate_growth_health([], detail['healthInputs']['incomeQuarterly'], as_of='2026-10-02')['passCount'] == 4
    from pipeline.valuation import derive_ttm_eps
    assert derive_ttm_eps(detail['healthInputs']['incomeQuarterly'], as_of='2026-10-02') is None


def test_restored_multiple_days_merge_inputs_only_and_are_idempotent(tmp_path):
    root = tmp_path / 'cache'
    install(root, day='2026-09-30', financialInputs={}, revenueMonthly=[], healthInputs={'dividends': [{'year': 2024, 'period': 'annual', 'cashPerShare': 1, 'confirmed': True, 'approvedAt': '2025-06-01'}]})
    install(root, day='2026-10-01', financialInputs={}, revenueMonthly=[], healthInputs={'dividends': [{'year': 2025, 'period': 'annual', 'cashPerShare': 2, 'confirmed': True, 'approvedAt': '2026-06-01'}]})
    baseline = [{'code': '2330', 'lastPrice': 100}]
    once = refresh.merge_restored_stock_inputs(baseline, root, as_of='2026-10-02')
    twice = refresh.merge_restored_stock_inputs(once, root, as_of='2026-10-02')
    assert once == twice
    assert [row['year'] for row in once[0]['healthInputs']['dividends']] == [2024, 2025]


def test_raw_cashflow_actual_seed_key_preserves_eligible_rows_and_baseline_priority(tmp_path):
    root = tmp_path / 'cache'
    install(root, financialInputs={'cashFlow': [{'date': '2025-06-30', 'type': 'CashFlowsFromOperatingActivities', 'value': 100},
                                               {'date': '2026-09-30', 'type': 'CashFlowsFromOperatingActivities', 'value': 999}]},
            healthInputs={}, revenueMonthly=[])
    baseline = [{'code': '2330', 'financialInputs': {'cashFlow': [{'date': '2025-06-30', 'type': 'CashFlowsFromOperatingActivities', 'value': 150}]}}]
    result = refresh.merge_restored_stock_inputs(baseline, root, as_of='2026-10-02')[0]
    assert result['financialInputs']['cashFlow'] == [{'date': '2025-06-30', 'type': 'CashFlowsFromOperatingActivities', 'value': 150}]
