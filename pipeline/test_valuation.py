import math
import pytest

from pipeline.valuation import (
    calculate_growth_total_return_valuation,
    calculate_zulu_valuation,
    derive_stable_eps_growth,
)


@pytest.mark.parametrize("case,expected_origin", [
    ("derived", "derived"), ("reported", "reported"), ("stale_pe", "derived"),
    ("adjusted_only", "unavailable"), ("wrong_price_date", "unavailable"),
    ("gap", "unavailable"), ("stock_dividend", "unavailable"),
    ("stock_surplus_only", "unavailable"),
    ("stock_surplus_roc_year", "unavailable"),
    ("incomparable", "unavailable"),
])
def test_shared_growth_inputs_preserve_same_day_and_eps_comparability(case, expected_origin):
    from pipeline.valuation import derive_growth_inputs
    income = [{"year": y, "quarter": q, "eps": 1.2 ** (y - 2022)}
              for y in (2022, 2023, 2024, 2025) for q in (1, 2, 3, 4)]
    detail = {"asOf": "2026-10-01", "lastPrice": 100,
              "priceSeries": [{"date": "2026-10-01", "close": 100, "adjustedClose": 100}],
              "healthInputs": {"incomeQuarterly": income}}
    if case in {"reported", "stale_pe"}:
        detail["healthInputs"]["valuationCurrent"] = {"date": "2026-10-01" if case == "reported" else "2026-09-30", "pe": 10}
    elif case == "adjusted_only":
        detail["priceSeries"][0].pop("close")
    elif case == "wrong_price_date":
        detail["priceSeries"][0]["date"] = "2026-09-30"
    elif case == "gap":
        income.remove(next(row for row in income if row["year"] == 2025 and row["quarter"] == 3))
    elif case == "stock_dividend":
        detail["healthInputs"]["dividends"] = [{"year": 2025, "stockPerShare": 1}]
    elif case in {"stock_surplus_only", "stock_surplus_roc_year"}:
        detail["financialInputs"] = {"dividend": [{"year": "114年" if case == "stock_surplus_roc_year" else "114", "StockStatutorySurplus": 1,
            "AnnouncementDate": "2026-04-01", "StockExDividendTradingDate": "2026-07-01"}]}
    elif case == "incomparable":
        income[-1]["epsComparable"] = False
    before = __import__("copy").deepcopy(detail)
    result = derive_growth_inputs(detail)
    assert result["pe_origin"] == expected_origin
    assert result["cutoff"] == "2026-10-01"
    assert detail == before
    if expected_origin == "derived":
        assert result["current_pe"] == 100 / result["ttm_eps"]
    elif expected_origin == "reported":
        assert result["current_pe"] == 10
    else:
        assert result["current_pe"] is None
    if case == "adjusted_only":
        assert result["current_price"] is None and result["price_origin"] == "proxy"
    if case in {"gap", "stock_dividend", "stock_surplus_only", "stock_surplus_roc_year"}:
        assert result["ttm_eps"] is None
    if case == "gap":
        assert result["ttm_eps_reason"] == "nonconsecutive_quarters"
    elif case in {"stock_dividend", "stock_surplus_only", "stock_surplus_roc_year", "incomparable"}:
        assert result["ttm_eps_reason"] == "incomparable_quarters"


def test_zulu_valuation_uses_eps_growth_and_exposes_066_075_bands():
    result = calculate_zulu_valuation(
        current_price=100,
        current_pe=10,
        eps_growth=0.30,
    )

    assert result is not None
    assert result["method"] == "zulu-peg"
    assert math.isclose(result["current_peg"], 10 / 30)
    assert math.isclose(result["reasonable_pe"], 30)
    assert math.isclose(result["fair_price"], 390)
    assert math.isclose(result["value_price_075"], 292.5)
    assert math.isclose(result["value_price_066"], 257.4)
    assert result["below_075"] is True
    assert result["below_066"] is True


def test_zulu_valuation_rejects_growth_without_eps_input():
    assert calculate_zulu_valuation(
        current_price=100,
        current_pe=10,
        eps_growth=None,
    ) is None


def test_zulu_valuation_rejects_invalid_inputs():
    assert calculate_zulu_valuation(
        current_price=100,
        current_pe=0,
        eps_growth=0.30,
    ) is None
    assert calculate_zulu_valuation(
        current_price=100,
        current_pe=10,
        eps_growth=-0.10,
    ) is None


def test_revenue_only_growth_is_explicit_proxy_valuation():
    result = calculate_zulu_valuation(
        current_price=100,
        current_pe=10,
        eps_growth=0.30,
        growth_method="ltm_revenue_proxy",
        growth_method_label="LTM 營收成長代理",
    )

    assert result is not None
    assert result["method"] == "zulu-peg"
    assert result["growth_method"] == "ltm_revenue_proxy"
    assert result["growth_method_label"] == "LTM 營收成長代理"
    assert math.isclose(result["current_peg"], 10 / 30)


def test_teacher_total_return_pe_uses_conservative_growth_and_dividend():
    result = calculate_growth_total_return_valuation(
        current_price=100,
        current_pe=13,
        ttm_eps=100 / 13,
        earnings_growth=0.20,
        dividend_yield=0.05,
    )

    assert result["status"] == "available"
    assert result["formula_version"] == "growth-total-return-pe-v1"
    assert math.isclose(result["conservative_growth"], 0.16)
    assert math.isclose(result["total_return_pct"], 21.0)
    assert math.isclose(result["total_return_pe"], 21 / 13)
    assert math.isclose(result["fair_pe"], 21.0)
    assert math.isclose(result["fair_price"], result["forward_eps"] * 21.0)
    assert math.isclose(result["buy_zone_price"], result["forward_eps"] * (21.0 / 1.2))
    assert result["undervalued"] is True


def test_stable_eps_growth_uses_multi_year_cagr_not_single_ltm_jump():
    rows = []
    annual_eps = {2022: 4.0, 2023: 5.0, 2024: 6.0, 2025: 8.0}
    for year, total in annual_eps.items():
        for quarter in (1, 2, 3, 4):
            rows.append({"year": year, "quarter": quarter, "eps": total / 4})
    rows.extend([
        {"year": "115", "quarter": 1, "eps": 5.0},
        {"year": "115", "quarter": 2, "eps": 5.0},
    ])

    result = derive_stable_eps_growth(rows)

    assert result["method"] == "five_year_eps_cagr"
    assert result["valid_years"] == 4
    assert math.isclose(result["growth"], (8 / 4) ** (1 / 3) - 1)


def test_teacher_total_return_pe_fails_closed_for_missing_dividend_and_extreme_growth():
    missing_dividend = calculate_growth_total_return_valuation(
        current_price=100, current_pe=10, ttm_eps=10, earnings_growth=0.30, dividend_yield=None,
    )
    extreme = calculate_growth_total_return_valuation(
        current_price=100, current_pe=10, ttm_eps=10, earnings_growth=1.50, dividend_yield=0.05,
    )

    assert missing_dividend["status"] == "unavailable"
    assert missing_dividend["fair_price"] is None
    assert extreme["status"] == "extreme"
    assert extreme["fair_price"] is None
    assert "極端" in extreme["reason"]


def test_ttm_requires_unique_consecutive_quarters_and_normalizes_roc():
    from pipeline.valuation import derive_ttm_eps
    assert derive_ttm_eps([
        {"year": 2025, "quarter": 3, "eps": 1},
        {"year": 2025, "quarter": 4, "eps": 2},
        {"year": 115, "quarter": 1, "eps": 3},
        {"year": 2026, "quarter": 2, "eps": 4},
        {"year": 115, "quarter": 2, "eps": 4},
    ]) == 10
    assert derive_ttm_eps([{"year": 2025, "quarter": q, "eps": 1} for q in (1, 2, 4)] +
                          [{"year": 2026, "quarter": 1, "eps": 1}]) is None


def test_ttm_does_not_treat_ytd_or_incompatible_share_basis_as_quarter_eps():
    from pipeline.valuation import derive_ttm_eps
    assert derive_ttm_eps([{"year": 2025, "quarter": q, "eps": q, "periodType": "ytd"}
                           for q in (1, 2, 3, 4)]) is None
    assert derive_ttm_eps([{"year": 2025, "quarter": q, "eps": 1, "epsBasis": str(q)}
                           for q in (1, 2, 3, 4)]) is None


def test_cagr_uses_only_completed_years_and_labels_actual_span():
    rows = [{"year": year, "quarter": q, "eps": (year - 2020) / 4}
            for year in (2021, 2022, 2023, 2024, 2025, 2026) for q in (1, 2, 3, 4)]
    result = derive_stable_eps_growth(rows, as_of="2026-10-01")
    assert result["annual_eps"].get(2026) is None
    assert result["start_year"] == 2021
    assert result["end_year"] == 2025
    assert "2021" in result["method_label"] and "2025" in result["method_label"]


def test_ttm_does_not_skip_newer_missing_eps_quarter():
    from pipeline.valuation import derive_ttm_eps
    rows = [{"year": 2025, "quarter": q, "eps": 1} for q in (1,2,3,4)]
    rows.append({"year": 2026, "quarter": 1, "eps": None})
    assert derive_ttm_eps(rows) is None


def test_comparison_and_cutoff_reject_future_publication_and_changed_basis():
    from pipeline.valuation import derive_ttm_eps
    rows = [{"year": 2025, "quarter": q, "eps": 1} for q in (1,2,3,4)]
    rows[-1] = {**rows[-1], "publishedAt": "2026-02-01"}
    assert derive_ttm_eps(rows, as_of="2026-01-01") is None


def test_ttm_rejects_unfinished_quarter_even_when_period_end_missing():
    from pipeline.valuation import derive_ttm_eps
    rows = [{"year": 2026, "quarter": quarter, "eps": 1} for quarter in (1,2,3,4)]
    assert derive_ttm_eps(rows, as_of="2026-10-01") is None


def test_cagr_does_not_drop_intervening_completed_loss_year():
    rows = [{"year": year, "quarter": quarter, "eps": value / 4}
            for year, value in ((2021, 1), (2022, -1), (2023, 3), (2024, 4), (2025, 5))
            for quarter in (1,2,3,4)]
    result = derive_stable_eps_growth(rows, as_of="2026-10-01")
    assert result["growth"] is None
    assert result["annual_eps"][2022] == -1
