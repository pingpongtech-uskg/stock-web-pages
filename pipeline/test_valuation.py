import math

from pipeline.valuation import (
    calculate_growth_total_return_valuation,
    calculate_zulu_valuation,
    derive_stable_eps_growth,
)


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
