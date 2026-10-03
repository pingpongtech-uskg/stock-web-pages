import pytest

from pipeline.health_checks import CATEGORY_DEFINITIONS, empty_health_categories, evaluate_category, evaluate_snapshot_health, health_totals


def test_thresholds_match_seven_category_contract():
    assert [(key, total, threshold) for key, _label, threshold, labels in CATEGORY_DEFINITIONS for total in [len(labels)]] == [
        ("quality", 5, 3), ("growth", 5, 4), ("chip", 3, 1), ("cheap", 6, 5),
        ("turnaround", 3, 1), ("antiPitfall", 6, 6), ("dividend", 5, 5),
    ]


def test_unknown_is_not_counted_as_pass():
    checks = [{"status": "pass"}, {"status": "unknown"}, {"status": "unknown"}, {"status": "unknown"}, {"status": "unknown"}]
    result = evaluate_category("growth", checks)
    assert result["passCount"] == 1
    assert result["status"] == "unknown"
    assert health_totals([result])["status"] == "unknown"


def test_four_of_five_growth_checks_meets_threshold_but_unknown_does_not():
    four_pass = [{"status": "pass"}] * 4 + [{"status": "fail"}]
    assert evaluate_category("growth", four_pass)["passCount"] == 4
    assert evaluate_category("growth", four_pass)["status"] == "pass"

    one_unknown = [{"status": "pass"}] * 4 + [{"status": "unknown"}]
    assert evaluate_category("growth", one_unknown)["passCount"] == 4
    assert evaluate_category("growth", one_unknown)["status"] == "unknown"


def test_known_failure_can_fail_without_all_fields():
    checks = [{"status": "fail"}, {"status": "fail"}, {"status": "unknown"}, {"status": "unknown"}, {"status": "unknown"}]
    assert evaluate_category("growth", checks)["status"] == "fail"


def test_monthly_revenue_rule_is_evaluated_from_snapshot():
    rows = []
    for year, values in [(2024, [10, 11, 12]), (2025, [12, 13, 14])]:
        for month, value in enumerate(values, 1):
            rows.append({"month": f"{year}-{month:02d}", "revenue": value})
    categories = evaluate_snapshot_health({"revenueMonthly": rows}, refs=["fixture"])
    growth = next(category for category in categories if category["key"] == "growth")
    assert growth["checks"][0]["status"] == "pass"
    assert growth["passCount"] == 1


def test_official_valuation_proxies_are_explicit():
    categories = evaluate_snapshot_health({
        "revenueMonthly": [],
        "healthInputs": {
            "valuationCurrent": {"pe": 10, "pb": 1.2, "dividendYield": 7.0},
            "valuationUniverse": [{"pe": 8, "pb": 1}, {"pe": 12, "pb": 2}],
        },
    })
    cheap = next(item for item in categories if item["key"] == "cheap")
    assert cheap["checks"][1]["status"] == "pass"
    assert "橫截面代理" in cheap["checks"][1]["explanation"]
    assert next(item for item in categories if item["key"] == "turnaround")["checks"][0]["status"] == "pass"


def test_quarterly_growth_without_prior_period_stays_unknown():
    categories = evaluate_snapshot_health({
        "healthInputs": {
            "incomeQuarterly": [{"year": 2026, "quarter": 1, "grossProfit": 10, "operatingProfit": 5, "pretaxProfit": 4, "netIncome": 3}],
        },
    })
    growth = next(item for item in categories if item["key"] == "growth")
    assert all(check["status"] == "unknown" for check in growth["checks"][1:])


def growth_category(detail):
    return next(category for category in evaluate_snapshot_health(detail) if category['key'] == 'growth')


def test_snapshot_asof_rejects_future_q3_and_uses_actual_declining_q2():
    result = growth_category({'asOf': '2026-10-02', 'healthInputs': {'incomeQuarterly': [
        {'year': 2025, 'quarter': 2, 'grossProfit': 100}, {'year': 2026, 'quarter': 2, 'grossProfit': 90},
        {'year': 2025, 'quarter': 3, 'grossProfit': 100},
        {'year': 2026, 'quarter': 3, 'grossProfit': 120, 'availableAt': '2026-11-15'}]}})
    assert result['checks'][1]['status'] == 'fail'
    assert result['checks'][1]['period'] == '2026 Q2 vs 2025 Q2'


def test_snapshot_future_month_not_yet_known_does_not_pass_three_months():
    rows = [{'month': f'{year}-{month:02d}', 'revenue': value}
            for year, value in [(2025, 100), (2026, 120)] for month in (7, 8, 9)]
    rows[-1] = {**rows[-1], 'availableAt': '2026-10-10'}
    result = growth_category({'asOf': '2026-10-02', 'healthInputs': {'monthlyRevenueOfficial': rows}})
    assert result['checks'][0]['status'] == 'unknown'


def test_snapshot_monthly_cutoff_uses_three_eligible_months_and_one_negative_fails():
    rows = [{'month': f'2025-{month:02d}', 'revenue': 100} for month in (6, 7, 8, 9)] + [
        {'month': '2026-06', 'revenue': 110}, {'month': '2026-07', 'revenue': 90},
        {'month': '2026-08', 'revenue': 110}, {'month': '2026-09', 'revenue': 120, 'availableAt': '2026-10-10'}]
    result = growth_category({'asOf': '2026-10-02', 'revenueMonthly': rows})
    assert result['checks'][0]['status'] == 'fail'
    assert result['checks'][0]['period'] == '2026-06–2026-08 vs 2025-06–2025-08'


def test_snapshot_does_not_reuse_cached_ytd_derivation_from_unavailable_predecessor():
    from pipeline.health_inputs import merge_health_inputs
    rows = [{'year': y, 'quarter': q, 'periodType': 'ytd', 'grossProfit': value, 'amountUnit': 'TWD_thousands',
             **({'availableAt': '2026-10-10'} if y == 2026 and q == 1 else {})}
            for y, q, value in [(2025, 1, 100), (2025, 2, 250), (2026, 1, 200), (2026, 2, 380)]]
    inputs = merge_health_inputs({}, {'incomeQuarterly': rows})
    assert inputs['incomeQuarterly'][-1]['grossProfit'] == 180
    result = growth_category({'asOf': '2026-10-02', 'healthInputs': inputs})
    assert result['checks'][1]['status'] == 'unknown'


def categories_by_key(detail):
    return {category['key']: category for category in evaluate_snapshot_health(detail)}


@pytest.mark.parametrize('detail', [{}, {'healthInputs': {}}, {'healthInputs': {'valuationCurrent': {'pb': 1.2}}}])
def test_absent_financial_history_stays_unknown_even_when_unrelated_pb_is_present(detail):
    categories = categories_by_key(detail)
    for key in ('quality', 'growth', 'chip', 'cheap', 'antiPitfall', 'dividend'):
        assert all(check['status'] == 'unknown' for check in categories[key]['checks'])
        assert categories[key]['status'] == 'unknown'
    assert health_totals(categories.values())['status'] == 'unknown'


def test_missing_turnover_comparisons_remain_unknown_with_positive_cashflow_proxy():
    categories = categories_by_key({'qualityProxyMetrics': {'latestOperatingCashFlow': 200, 'latestNetIncome': 100},
                                    'healthInputs': {'valuationCurrent': {'pb': 1.2}}})
    anti = categories['antiPitfall']
    assert [check['status'] for check in anti['checks']] == ['pass'] * 4 + ['unknown'] * 2
    assert anti['status'] == 'unknown'


def test_sparse_price_and_dividend_history_do_not_prove_threshold_failure():
    categories = categories_by_key({'priceSeries': [{'date': '2026-10-01', 'close': 100}],
                                    'healthInputs': {'dividends': [{'year': 2025, 'period': 'annual', 'cashPerShare': 2}]}})
    assert categories['quality']['checks'][0]['status'] == 'unknown'
    assert categories['dividend']['checks'][2]['status'] == 'unknown'


@pytest.mark.parametrize('statuses,expected', [(['pass'], 'unknown'), (['fail'], 'unknown'),
                                            (['pass', 'pass', 'pass', 'unknown', 'unknown'], 'unknown'),
                                            (['pass', 'pass', 'pass', 'fail', 'fail'], 'fail'),
                                            (['pass', 'pass', 'pass', 'pass', 'unknown'], 'pass')])
def test_fscore_proxy_requires_actual_evidence_before_declaring_failure(statuses, expected):
    categories = categories_by_key({'qualityProxyChecks': [{'label': str(i), 'status': status} for i, status in enumerate(statuses)]})
    assert categories['turnaround']['checks'][1]['status'] == expected


def test_known_negative_cashflow_and_low_yield_still_fail_without_other_history():
    categories = categories_by_key({'qualityProxyMetrics': {'latestOperatingCashFlow': -10, 'latestNetIncome': 100},
                                    'healthInputs': {'valuationCurrent': {'dividendYield': 2}}})
    assert categories['antiPitfall']['checks'][0]['status'] == 'fail'
    assert categories['antiPitfall']['checks'][4]['status'] == 'unknown'
    assert categories['antiPitfall']['status'] == 'fail'
    assert categories['dividend']['checks'][0]['status'] == 'fail'
    assert categories['dividend']['checks'][2]['status'] == 'unknown'
    assert categories['dividend']['status'] == 'fail'
    assert health_totals(categories.values())['status'] == 'fail'


def test_four_growth_passes_stay_qualified_with_other_categories_unknown():
    from pipeline.growth_health import growth_health_qualifies
    detail = {'asOf': '2026-10-02', 'qualityStatus': 'unknown', 'healthInputs': {'incomeQuarterly': [
        {'year': year, 'quarter': 2, **{field: amount for field in ('grossProfit', 'operatingProfit', 'pretaxProfit', 'netIncome')}}
        for year, amount in [(2025, 100), (2026, 120)]]}}
    categories = categories_by_key(detail)
    assert growth_health_qualifies(categories['growth']) is True
    assert categories['growth']['passCount'] == 4
    assert categories['antiPitfall']['status'] == 'unknown'
    assert health_totals(categories.values())['status'] == 'unknown'
    assert detail['qualityStatus'] == 'unknown'


def annual_dividend_rows(years):
    return [{'year': year, 'period': 'annual', 'cashPerShare': 2, 'confirmed': True,
             'availableAt': f'{year + 1}-06-01'} for year in years]


@pytest.mark.parametrize('years', [[2025] * 5, [2018, 2020, 2022, 2024, 2025]])
def test_five_dividend_rows_do_not_prove_five_consecutive_years(years):
    categories = categories_by_key({'asOf': '2026-10-02', 'healthInputs': {'dividends': annual_dividend_rows(years)}})
    assert categories['dividend']['checks'][2]['status'] == 'unknown'


def test_five_consecutive_completed_confirmed_dividend_years_pass():
    categories = categories_by_key({'asOf': '2026-10-02', 'healthInputs': {'dividends': annual_dividend_rows(range(2021, 2026))}})
    check = categories['dividend']['checks'][2]
    assert check['status'] == 'pass'
    assert check['period'] == '2021–2025'


@pytest.mark.parametrize('change', [{'availableAt': '2026-10-03'}, {'confirmed': False}, {'availableAt': None}])
def test_dividend_year_without_available_confirmation_does_not_complete_history(change):
    rows = annual_dividend_rows(range(2021, 2026))
    rows[-1] = {**rows[-1], **change}
    categories = categories_by_key({'asOf': '2026-10-02', 'healthInputs': {'dividends': rows}})
    assert categories['dividend']['checks'][2]['status'] == 'unknown'


def test_verified_complete_annual_zero_dividend_is_known_failure():
    rows = annual_dividend_rows(range(2021, 2026))
    rows[-1] = {**rows[-1], 'cashPerShare': 0}
    categories = categories_by_key({'asOf': '2026-10-02', 'healthInputs': {'dividends': rows}})
    assert categories['dividend']['checks'][2]['status'] == 'fail'


def test_one_flow_observation_does_not_prove_three_month_proxy_failure():
    categories = categories_by_key({'institutionalDaily': [{'netShares': 100}]})
    assert all(check['status'] == 'unknown' for check in categories['chip']['checks'])


def test_confirmed_dividend_history_without_assessment_date_stays_unknown():
    categories = categories_by_key({'healthInputs': {'dividends': annual_dividend_rows(range(2021, 2026))}})
    assert categories['dividend']['checks'][2]['status'] == 'unknown'


@pytest.mark.parametrize('field', ['availableAt', 'publishedAt'])
def test_earlier_dividend_approval_does_not_mask_future_publication(field):
    rows = annual_dividend_rows(range(2021, 2026))
    rows[-1] = {**rows[-1], 'approvedAt': '2026-06-01', field: '2026-10-03'}
    categories = categories_by_key({'asOf': '2026-10-02', 'healthInputs': {'dividends': rows}})
    assert categories['dividend']['checks'][2]['status'] == 'unknown'


@pytest.mark.parametrize('cfo,status', [(-10, 'fail'), (200, 'pass')])
def test_metrics_only_cashflow_evidence_is_evaluated(cfo, status):
    categories = categories_by_key({'asOf': '2026-10-02',
                                    'qualityProxyMetrics': {'latestOperatingCashFlow': cfo, 'latestNetIncome': 100}})
    assert categories['antiPitfall']['checks'][0]['status'] == status
    assert categories['antiPitfall']['checks'][2]['status'] == status
    assert categories['antiPitfall']['checks'][4]['status'] == 'unknown'


def test_empty_metrics_do_not_create_known_failure():
    categories = categories_by_key({'asOf': '2026-10-02', 'qualityProxyMetrics': {}})
    assert all(check['status'] == 'unknown' for category in categories.values() for check in category['checks'])
