import pytest

from pipeline.growth_health import evaluate_growth_health
from pipeline.health_inputs import merge_health_inputs, normalize_finmind_health_inputs


def test_normalize_finmind_history_supports_five_growth_checks():
    financial_inputs = {
        "incomeStatement": [
            {"date": "2025-03-31", "type": "GrossProfit", "value": 100},
            {"date": "2025-03-31", "type": "OperatingIncome", "value": 100},
            {"date": "2025-03-31", "type": "PreTaxIncome", "value": 100},
            {"date": "2025-03-31", "type": "IncomeAfterTaxes", "value": 100},
            {"date": "2026-03-31", "type": "GrossProfit", "value": 110},
            {"date": "2026-03-31", "type": "OperatingIncome", "value": 90},
            {"date": "2026-03-31", "type": "PreTaxIncome", "value": 80},
            {"date": "2026-03-31", "type": "IncomeAfterTaxes", "value": 70},
        ],
    }
    monthly = [
        {"revenue_year": 2025, "revenue_month": 1, "revenue": 100},
        {"revenue_year": 2025, "revenue_month": 2, "revenue": 110},
        {"revenue_year": 2025, "revenue_month": 3, "revenue": 120},
        {"revenue_year": 2026, "revenue_month": 1, "revenue": 101},
        {"revenue_year": 2026, "revenue_month": 2, "revenue": 121},
        {"revenue_year": 2026, "revenue_month": 3, "revenue": 150},
    ]

    inputs = normalize_finmind_health_inputs(financial_inputs, monthly)
    result = evaluate_growth_health(inputs["monthlyRevenueOfficial"], inputs["incomeQuarterly"])

    assert result["passCount"] == 2
    assert [check["status"] for check in result["checks"]] == ["pass", "pass", "fail", "fail", "fail"]


def test_merge_health_inputs_preserves_history_and_overlays_latest_rows():
    base = {
        "source": "FinMind",
        "incomeQuarterly": [{"year": 2025, "quarter": 1, "grossProfit": 100}],
        "monthlyRevenueOfficial": [{"month": "2025-03", "revenue": 100}],
    }
    overlay = {
        "source": "TWSE OpenAPI",
        "incomeQuarterly": [{"year": 2026, "quarter": 1, "grossProfit": 110}],
        "monthlyRevenueOfficial": [{"month": "2026-03", "revenue": 150}],
    }

    merged = merge_health_inputs(base, overlay)

    assert merged["source"] == "TWSE OpenAPI"
    assert [(row["year"], row["quarter"]) for row in merged["incomeQuarterly"]] == [(2025, 1), (2026, 1)]
    assert [row["month"] for row in merged["monthlyRevenueOfficial"]] == ["2025-03", "2026-03"]


def test_merge_normalizes_roc_periods_and_does_not_erase_valid_values():
    base = {"incomeQuarterly": [{"year": 2026, "quarter": 2, "eps": 3, "grossProfit": 10}],
            "monthlyRevenueOfficial": [{"month": "2026-08", "revenue": 100}]}
    overlay = {"incomeQuarterly": [{"year": "115", "quarter": "2", "eps": None, "grossProfit": 12}],
               "monthlyRevenueOfficial": [{"month": "11508", "revenue": None}]}
    result = merge_health_inputs(base, overlay)
    assert result["incomeQuarterly"] == [{"year": 2026, "quarter": 2, "eps": 3, "grossProfit": 12}]
    assert result["monthlyRevenueOfficial"] == [{"month": "2026-08", "revenue": 100}]
    assert base["incomeQuarterly"][0]["grossProfit"] == 10


def test_finmind_period_end_does_not_become_publication_date():
    result = normalize_finmind_health_inputs({"incomeStatement": [
        {"date": "2026-06-30", "type": "EPS", "value": 3},
    ]}, [])
    row = result["incomeQuarterly"][0]
    assert row["periodEnd"] == "2026-06-30"
    assert row.get("availableAt") is None
    assert row.get("publishedAt") is None
    assert row["periodType"] == "quarter"


def test_ytd_derivation_recovers_additive_amounts_without_fabricating_eps():
    from pipeline.financial_periods import quarterly_income
    rows = [
        {"year": 115, "quarter": 1, "periodType": "ytd", "grossProfit": 100, "eps": 2},
        {"year": 115, "quarter": 2, "periodType": "ytd", "grossProfit": 230, "eps": 5},
    ]
    result = quarterly_income(rows)
    assert result[1]["grossProfit"] == 130
    assert result[1].get("eps") is None
    assert result[1]["inputOrigin"] == "derived"
    rows = [{**row, "epsBasis": "common", "weightedAverageShares": 100} for row in rows]
    assert quarterly_income(rows)[1]["eps"] == 3


def test_direct_quarters_survive_ytd_overlay():
    result = merge_health_inputs({"incomeQuarterly": [{"year": 2026, "quarter": 2, "eps": 3, "grossProfit": 130}]},
                               {"incomeQuarterly": [{"year": 115, "quarter": 2, "periodType": "ytd", "eps": 5, "grossProfit": 230}]})
    assert result["incomeQuarterly"][0]["eps"] == 3
    assert result["incomeQuarterly"][0]["grossProfit"] == 130
    assert result["incomeYtd"][0]["eps"] == 5


def test_dividend_period_identifies_roc_quarters_halves_and_rejects_date_as_period():
    from pipeline.financial_periods import dividend_period
    assert dividend_period("114年第4季") == (2025, "Q4")
    assert dividend_period("114年上半年度") == (2025, "H1")
    assert dividend_period("114") == (2025, "annual")
    assert dividend_period("2026-06-01", 2025) is None


def test_monthly_prior_year_official_values_can_prove_three_month_rule():
    result = evaluate_growth_health([
        {"month": f"2026-{month:02d}", "revenue": 110, "priorYearRevenue": 100}
        for month in (6,7,8)
    ], [])
    assert result["checks"][0]["status"] == "pass"


def test_dividend_period_accepts_separate_year_and_canonical_period_label():
    from pipeline.financial_periods import dividend_period
    assert dividend_period("annual", 2025) == (2025, "annual")
    assert dividend_period("Q2", 114) == (2025, "Q2")


def test_merge_does_not_replace_valid_eps_with_non_finite_overlay():
    result = merge_health_inputs({"incomeQuarterly": [{"year": 2025, "quarter": 4, "eps": 3}]},
                               {"incomeQuarterly": [{"year": 2025, "quarter": 4, "eps": float("nan")}]})
    assert result["incomeQuarterly"][0]["eps"] == 3


def test_dividend_period_accepts_official_chinese_label_with_separate_year():
    from pipeline.financial_periods import dividend_period
    assert dividend_period("年度", 114) == (2025, "annual")
    assert dividend_period("第2季", 114) == (2025, "Q2")
    assert dividend_period("上半年度", 114) == (2025, "H1")


def test_ytd_without_predecessor_labels_quarter_origin_unavailable():
    from pipeline.financial_periods import quarterly_income
    row = quarterly_income([{"year": 2026, "quarter": 2, "periodType": "ytd", "eps": 5, "grossProfit": 200}])[0]
    assert row["inputOrigin"] == "unavailable"
    assert row["cumulativeValues"]["eps"] == 5
    assert row.get("eps") is None


@pytest.mark.parametrize("code,prior,current,expected", [
    ("2801", 4994544000, 6093217000, "pass"),
    ("2883", -3233297000, 16755995000, "unknown"),
    ("2884", 7965811000, 11397921000, "pass"),
    ("2887", 5489921000, 22776682000, "pass"),
    ("2890", 5505747000, 13531320000, "pass"),
    ("2891", 16203095000, 16850130000, "pass"),
    ("2892", 6740361000, 9554372000, "pass"),
])
def test_actual_bank_aftertax_alias_recovers_only_reported_same_quarter_amounts(code, prior, current, expected):
    # Published Oct2 raw FinMind rows: the bank spelling is singular, with the
    # same Chinese accounting label as the existing IncomeAfterTaxes mapping.
    raw = [{"date": day, "stock_id": code, "type": "IncomeAfterTax",
            "origin_name": "本期稅後淨利（淨損）", "value": value}
           for day, value in [("2025-06-30", prior), ("2026-06-30", current)]]
    financial = {"incomeStatement": raw}
    original = {"incomeStatement": [dict(row) for row in raw]}
    inputs = normalize_finmind_health_inputs(financial, [])
    assert [row["netIncome"] for row in inputs["incomeQuarterly"]] == [prior, current]
    assert all(row["amountUnit"] == "TWD" and row["periodType"] == "quarter"
               and row.get("availableAt") is None and row.get("publishedAt") is None
               and row.get("eps") is None and row.get("grossProfit") is None
               and row.get("operatingProfit") is None for row in inputs["incomeQuarterly"])
    result = evaluate_growth_health([], inputs["incomeQuarterly"], as_of="2026-10-02")
    check = result["checks"][4]
    assert check["status"] == expected and check["period"] == "2026 Q2 vs 2025 Q2"
    assert check["sourceRefs"] == ["FinMind:TaiwanStockFinancialStatements"]
    assert check["value"] == (pytest.approx(current / prior - 1) if prior > 0 else None)
    assert all(result["checks"][index]["status"] == "unknown" for index in (1, 2, 3))
    assert financial == original and raw[0]["type"] == "IncomeAfterTax"


def test_bank_aftertax_alias_respects_cutoff_and_does_not_alias_continuing_pretax():
    inputs = normalize_finmind_health_inputs({"incomeStatement": [
        {"date": "2025-06-30", "type": "IncomeAfterTax", "value": 100},
        {"date": "2026-06-30", "type": "IncomeAfterTax", "value": 120, "availableAt": "2026-10-03"},
        {"date": "2026-06-30", "type": "IncomeBeforeTaxFromContinuingOperations", "value": 150},
    ]}, [])
    latest = inputs["incomeQuarterly"][-1]
    assert latest["netIncome"] == 120 and latest["availableAt"] == "2026-10-03"
    assert latest.get("pretaxProfit") is None
    result = evaluate_growth_health([], inputs["incomeQuarterly"], as_of="2026-10-02")
    assert result["checks"][4]["status"] == "unknown" and result["checks"][4]["value"] is None


def test_bank_aftertax_alias_cannot_compare_different_amount_units():
    inputs = normalize_finmind_health_inputs({"incomeStatement": [
        {"date": "2026-06-30", "type": "IncomeAfterTax", "value": 120},
    ]}, [])
    merged = merge_health_inputs({"incomeQuarterly": [
        {"year": 2025, "quarter": 2, "netIncome": 100, "amountUnit": "TWD_thousands"}
    ]}, inputs)
    result = evaluate_growth_health([], merged["incomeQuarterly"], as_of="2026-10-02")
    assert result["checks"][4]["status"] == "unknown" and result["checks"][4]["value"] is None
