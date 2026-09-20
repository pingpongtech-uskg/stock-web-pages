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
