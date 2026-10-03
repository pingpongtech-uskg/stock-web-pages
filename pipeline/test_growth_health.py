from pipeline.growth_health import evaluate_growth_health
import pytest


def monthly_rows(current_values, prior_values):
    rows = []
    for month, value in zip(("2025-01", "2025-02", "2025-03"), current_values):
        rows.append({"month": month, "revenue": value})
    for month, value in zip(("2024-01", "2024-02", "2024-03"), prior_values):
        rows.append({"month": month, "revenue": value})
    return rows


def quarterly_rows(current, prior):
    return [
        {"year": 2024, "quarter": 1, **prior},
        {"year": 2025, "quarter": 1, **current},
    ]


def test_all_five_growth_health_checks_pass():
    result = evaluate_growth_health(
        monthly_rows([110, 120, 130], [100, 100, 100]),
        quarterly_rows(
            {"grossProfit": 110, "operatingProfit": 55, "pretaxProfit": 44, "netIncome": 33},
            {"grossProfit": 100, "operatingProfit": 50, "pretaxProfit": 40, "netIncome": 30},
        ),
    )
    assert result["passCount"] == 5
    assert result["status"] == "pass"
    assert all(check["status"] == "pass" for check in result["checks"])


def test_one_or_two_checks_pass_are_transparent_and_not_pass_status():
    result = evaluate_growth_health(
        monthly_rows([110, 120, 130], [100, 100, 100]),
        quarterly_rows(
            {"grossProfit": 90, "operatingProfit": 55, "pretaxProfit": 20, "netIncome": 10},
            {"grossProfit": 100, "operatingProfit": 50, "pretaxProfit": 40, "netIncome": 30},
        ),
    )
    assert result["passCount"] == 2
    assert result["status"] == "fail"


def test_missing_prior_quarter_stays_unknown():
    result = evaluate_growth_health(
        monthly_rows([110, 120, 130], [100, 100, 100]),
        [{"year": 2025, "quarter": 1, "grossProfit": 110, "operatingProfit": 55, "pretaxProfit": 44, "netIncome": 33}],
    )
    assert result["checks"][1]["status"] == "unknown"
    assert result["passCount"] == 1


def test_one_month_positive_does_not_satisfy_three_month_rule():
    result = evaluate_growth_health(
        monthly_rows([110, 90, 90], [100, 100, 100]),
        quarterly_rows(
            {"grossProfit": 110, "operatingProfit": 55, "pretaxProfit": 44, "netIncome": 33},
            {"grossProfit": 100, "operatingProfit": 50, "pretaxProfit": 40, "netIncome": 30},
        ),
    )
    assert result["checks"][0]["status"] == "fail"
    assert result["passCount"] == 4
    assert result["status"] == "fail"


def test_quarter_growth_normalizes_roc_and_rejects_negative_comparison_base():
    result = evaluate_growth_health([], [
        {"year": 2025, "quarter": 2, "grossProfit": 100, "netIncome": -100},
        {"year": 115, "quarter": 2, "grossProfit": 120, "netIncome": -120},
    ])
    assert result["checks"][1]["status"] == "pass"
    assert result["checks"][4]["status"] == "unknown"


def test_quarter_ytd_without_previous_ytd_stays_unknown():
    result = evaluate_growth_health([], [
        {"year": 2025, "quarter": 2, "grossProfit": 100, "periodType": "ytd"},
        {"year": 2026, "quarter": 2, "grossProfit": 200, "periodType": "ytd"},
    ])
    assert result["checks"][1]["status"] == "unknown"


def test_different_amount_units_are_not_like_for_like_growth():
    result = evaluate_growth_health([], [
        {"year": 2025, "quarter": 2, "grossProfit": 100, "amountUnit": "TWD"},
        {"year": 2026, "quarter": 2, "grossProfit": 120, "amountUnit": "TWD_thousands"},
    ])
    assert result["checks"][1]["status"] == "unknown"


@pytest.mark.parametrize('current_field,prior_field,index', [
    ('netIncome', 'parentNetIncome', 4), ('parentNetIncome', 'netIncome', 4),
    ('pretaxProfit', 'pretaxNetIncome', 3), ('pretaxNetIncome', 'pretaxProfit', 3)])
def test_yoy_never_compares_different_profit_fields(current_field, prior_field, index):
    result = evaluate_growth_health([], [
        {'year': 2025, 'quarter': 2, prior_field: 100},
        {'year': 2026, 'quarter': 2, current_field: 120},
    ])
    assert result['checks'][index]['status'] == 'unknown'
    assert result['checks'][index]['value'] is None


@pytest.mark.parametrize('field,index', [('parentNetIncome', 4), ('pretaxNetIncome', 3)])
def test_same_alias_on_both_sides_is_comparable(field, index):
    result = evaluate_growth_health([], [
        {'year': 2025, 'quarter': 2, field: 100}, {'year': 2026, 'quarter': 2, field: 120}])
    assert result['checks'][index]['status'] == 'pass'


def test_profit_amount_growth_does_not_use_margin_and_pretax_is_independent():
    result = evaluate_growth_health([], [
        {'year': 2025, 'quarter': 2, 'grossProfit': 100, 'grossMargin': 0.5, 'pretaxProfit': 100, 'netIncome': 100},
        {'year': 2026, 'quarter': 2, 'grossProfit': 120, 'grossMargin': 0.2, 'pretaxProfit': 90, 'netIncome': 120}])
    assert [result['checks'][i]['status'] for i in (1, 3, 4)] == ['pass', 'fail', 'pass']


def test_cutoff_selects_latest_eligible_quarter_and_preserves_comparison_period():
    result = evaluate_growth_health([], [
        {'year': 2025, 'quarter': 2, 'grossProfit': 100, 'source': 'official prior'},
        {'year': 2026, 'quarter': 2, 'grossProfit': 90, 'source': 'official current'},
        {'year': 2025, 'quarter': 3, 'grossProfit': 100},
        {'year': 2026, 'quarter': 3, 'grossProfit': 120, 'availableAt': '2026-11-15'},
    ], as_of='2026-10-02')
    check = result['checks'][1]
    assert check['status'] == 'fail' and check['value'] == pytest.approx(-0.1)
    assert check['period'] == '2026 Q2 vs 2025 Q2'
    assert check['sourceRefs'] == ['official current', 'official prior']


@pytest.mark.parametrize('field', ['availableAt', 'publishedAt', 'reportDate', 'periodEnd'])
def test_future_comparative_publication_is_unknown(field):
    result = evaluate_growth_health([], [
        {'year': 2025, 'quarter': 2, 'grossProfit': 100, field: '115/10/03'},
        {'year': 2026, 'quarter': 2, 'grossProfit': 120},
    ], as_of='2026-10-02')
    assert result['checks'][1]['status'] == 'unknown'


def test_incomplete_quarter_period_without_publication_date_is_not_eligible():
    result = evaluate_growth_health([], [
        {'year': 2025, 'quarter': 4, 'grossProfit': 100}, {'year': 2026, 'quarter': 4, 'grossProfit': 120},
    ], as_of='2026-10-02')
    assert result['checks'][1]['status'] == 'unknown'


def test_ytd_recovery_uses_eligible_predecessors_before_subtraction():
    rows = [
        {'year': y, 'quarter': q, 'periodType': 'ytd', 'grossProfit': value, 'amountUnit': 'TWD_thousands'}
        for y, q, value in [(2025, 1, 100), (2025, 2, 250), (2026, 1, 200), (2026, 2, 380)]]
    result = evaluate_growth_health([], rows, as_of='2026-10-02')
    assert result['checks'][1]['value'] == pytest.approx(180 / 150 - 1)
    assert result['checks'][1]['status'] == 'pass'
    future = [{**row, **({'availableAt': '2026-10-10'} if row['year'] == 2026 and row['quarter'] == 1 else {})} for row in rows]
    assert evaluate_growth_health([], future, as_of='2026-10-02')['checks'][1]['status'] == 'unknown'


def test_completed_q3_without_publication_evidence_waits_for_filing_deadline():
    rows = [
        {'year': 2025, 'quarter': 2, 'grossProfit': 100},
        {'year': 2026, 'quarter': 2, 'grossProfit': 90},
        {'year': 2025, 'quarter': 3, 'grossProfit': 100},
        {'year': 2026, 'quarter': 3, 'grossProfit': 120, 'periodEnd': '2026-09-30'}]
    check = evaluate_growth_health([], rows, as_of='2026-10-02')['checks'][1]
    assert check['status'] == 'fail'
    assert check['period'] == '2026 Q2 vs 2025 Q2'
    published = [*rows[:-1], {**rows[-1], 'publishedAt': '2026-10-01'}]
    assert evaluate_growth_health([], published, as_of='2026-10-02')['checks'][1]['status'] == 'pass'


def test_month_without_publication_evidence_waits_for_next_month_tenth():
    rows = [{'month': f'{year}-{month:02d}', 'revenue': value}
            for year, value in [(2025, 100), (2026, 120)] for month in (7, 8, 9)]
    assert evaluate_growth_health(rows, [], as_of='2026-10-02')['checks'][0]['status'] == 'unknown'
    assert evaluate_growth_health(rows, [], as_of='2026-10-10')['checks'][0]['status'] == 'pass'
    published = [*rows[:-1], {**rows[-1], 'availableAt': '2026-10-01'}]
    assert evaluate_growth_health(published, [], as_of='2026-10-02')['checks'][0]['status'] == 'pass'


def test_complete_old_revenue_becomes_unknown_only_when_new_month_is_due():
    rows = [{'month': f'{year}-{month:02d}', 'revenue': value}
            for year, value in [(2025, 100), (2026, 120)] for month in (6, 7, 8)]
    for day in ('2026-10-02', '2026-10-09'):
        assert evaluate_growth_health(rows, [], as_of=day)['checks'][0]['status'] == 'pass'
    check = evaluate_growth_health(rows, [], as_of='2026-10-10')['checks'][0]
    assert check['status'] == 'unknown' and check['value'] is None
    assert '2026-09' in check['explanation'] and '2026-06–2026-08' in check['period']


def test_missing_latest_month_does_not_change_four_confirmed_quarter_passes():
    from pipeline.growth_health import growth_health_qualifies
    rows = [{'month': f'{year}-{month:02d}', 'revenue': value}
            for year, value in [(2025, 100), (2026, 120)] for month in (6, 7, 8)]
    income = [{'year': year, 'quarter': 2, **{field: value for field in
               ('grossProfit', 'operatingProfit', 'pretaxProfit', 'netIncome')}}
              for year, value in [(2025, 100), (2026, 120)]]
    result = evaluate_growth_health(rows, income, as_of='2026-10-10')
    assert result['checks'][0]['status'] == 'unknown' and result['passCount'] == 4
    assert growth_health_qualifies(result)


@pytest.mark.parametrize('day,expected', [('2026-10-02', '2026-08'), ('2026-10-10', '2026-09'),
                                         ('2027-01-09', '2026-11'), ('2027-01-10', '2026-12')])
def test_required_revenue_month_observes_deadline_and_year_boundary(day, expected):
    from pipeline.growth_health import expected_revenue_month
    assert expected_revenue_month(day) == expected


def test_early_published_latest_revenue_is_required_without_using_future_evidence():
    from pipeline.growth_health import expected_revenue_month
    rows = [{'month': f'{year}-{month:02d}', 'revenue': value}
            for year, value in [(2025, 100), (2026, 120)] for month in (7, 8, 9)]
    known = [{**row, 'publishedAt': '2026-10-01'} if row['month'] == '2026-09' else row for row in rows]
    assert expected_revenue_month('2026-10-02', known) == '2026-09'
    assert evaluate_growth_health(known, [], as_of='2026-10-02')['checks'][0]['status'] == 'pass'
    future = [{**row, 'publishedAt': '2026-10-03'} if row['month'] == '2026-09' else row for row in rows]
    assert expected_revenue_month('2026-10-02', future) == '2026-08'
    assert evaluate_growth_health(future, [], as_of='2026-10-02')['checks'][0]['status'] == 'unknown'
