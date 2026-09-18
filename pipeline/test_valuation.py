import math

from pipeline.valuation import calculate_zulu_valuation


def test_zulu_valuation_uses_the_same_known_inputs_for_every_strategy():
    result = calculate_zulu_valuation(
        current_price=100,
        current_pe=10,
        dividend_yield_pct=5,
        revenue_growth=0.20,
    )

    assert result is not None
    assert result["method"] == "zulu"
    assert math.isclose(result["fair_price"], 243.6)
    assert math.isclose(result["growth_input"], 0.20)


def test_zulu_valuation_returns_none_when_growth_is_not_known():
    assert calculate_zulu_valuation(
        current_price=100,
        current_pe=10,
        dividend_yield_pct=5,
        revenue_growth=None,
    ) is None


def test_zulu_valuation_rejects_invalid_price_inputs():
    assert calculate_zulu_valuation(
        current_price=100,
        current_pe=0,
        dividend_yield_pct=5,
        revenue_growth=0.20,
    ) is None
