"""Keep producer and publication gate aligned when optional PEG is absent."""
import pytest

from pipeline.valuation import calculate_growth_total_return_valuation
from scripts.refresh_snapshot import _attach_valuation
from scripts.verify_snapshot import ranking_valuation_error


def growth_row():
    valuation = calculate_growth_total_return_valuation(
        current_price=100, current_pe=10, ttm_eps=10,
        earnings_growth=0.2, dividend_yield=0.02,
    )
    return _attach_valuation(
        [{"code": "2330"}], {"2330": {"growthValuation": valuation}},
        valuation_key="growthValuation", require_growth_total_return_pe=1.2,
    )[0]


def test_producer_growth_without_optional_peg_passes_publication_gate():
    row = growth_row()
    assert row["currentPeg"] is None
    assert row["fairPrice"] > 0
    assert ranking_valuation_error(row, "growth") is None


@pytest.mark.parametrize("field,value", [
    ("valuationMethod", "zulu-peg"), ("valuationFormulaVersion", "unknown"),
    ("growthValuationStatus", "unavailable"), ("extremeExtrapolation", True),
    ("currentPrice", None), ("currentPe", 0), ("currentEps", True),
    ("valuationGrowthInput", float("nan")), ("growthDividendYield", -0.01),
    ("growthTotalReturnPe", 1), ("growthConservativeGrowth", 0.1),
    ("growthForwardEps", None), ("growthFairPrice", 1),
    ("growthBuyZonePrice", 1), ("fairPrice", 1),
    ("valuePrice075", 75),
])
def test_growth_contract_rejects_incomplete_or_inconsistent_values(field, value):
    assert ranking_valuation_error({**growth_row(), field: value}, "growth")


def test_growth_values_cannot_bypass_peg_contract_on_other_strategies():
    assert ranking_valuation_error(growth_row(), "trust")


def test_optional_peg_does_not_hide_invalid_growth_formula():
    assert ranking_valuation_error(
        {**growth_row(), "currentPeg": 0.5, "growthFairPrice": 1}, "growth"
    )
