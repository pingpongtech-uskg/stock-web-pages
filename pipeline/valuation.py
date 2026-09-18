"""One consistent Zulu-style known-input valuation for all strategy tabs.

The Zulu Principle is an investment selection framework, not a separate fair
value equation. This project uses its narrow-universe/growth discipline and a
single transparent scenario: known revenue growth proxy, current PE, dividend
yield, and current price. Rows without every input are not published in the
stock lists.
"""

from __future__ import annotations

import math
from typing import Any


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def calculate_zulu_valuation(
    *,
    current_price: float | int | None,
    current_pe: float | int | None,
    dividend_yield_pct: float | int | None,
    revenue_growth: float | int | None,
    forecast_haircut: float = 0.80,
) -> dict[str, Any] | None:
    """Calculate the same Zulu-style scenario for every strategy.

    Inputs: revenue growth as decimal (0.20 = 20%), dividend yield as
    percentage points (5 = 5%), current price, and current PE.

    conservative growth = revenue growth × 0.8
    fair PE = (conservative growth + dividend yield) × 100
    forward EPS = current price / PE × (1 + conservative growth)
    fair price = forward EPS × fair PE
    """
    price = _finite(current_price)
    pe = _finite(current_pe)
    dividend = _finite(dividend_yield_pct)
    growth = _finite(revenue_growth)
    if (
        price is None
        or pe is None
        or dividend is None
        or growth is None
        or price <= 0
        or pe <= 0
        or dividend < 0
        or growth < 0
        or forecast_haircut < 0
    ):
        return None

    conservative_growth = growth * forecast_haircut
    dividend_decimal = dividend / 100.0
    fair_pe = (conservative_growth + dividend_decimal) * 100.0
    ttm_eps = price / pe
    forward_eps = ttm_eps * (1.0 + conservative_growth)
    fair_price = forward_eps * fair_pe
    if not math.isfinite(fair_price) or fair_price <= 0:
        return None
    return {
        "method": "zulu",
        "current_price": price,
        "fair_price": fair_price,
        "current_pe": pe,
        "growth_input": growth,
        "growth_input_kind": "revenue_proxy",
        "dividend_yield_pct": dividend,
        "conservative_growth": conservative_growth,
        "fair_pe": fair_pe,
        "forward_eps": forward_eps,
        "total_return_pe": fair_pe / pe,
        "formula_version": "zulu-known-growth-price-v1",
    }
