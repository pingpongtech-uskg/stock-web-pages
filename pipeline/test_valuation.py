import math

from pipeline.valuation import calculate_zulu_valuation


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
