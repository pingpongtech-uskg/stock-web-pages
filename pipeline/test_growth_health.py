from pipeline.growth_health import evaluate_growth_health


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
