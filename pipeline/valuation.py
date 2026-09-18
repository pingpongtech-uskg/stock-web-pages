"""Zulu / PEG valuation using the article's known-input method.

The Zulu Principle uses expected EPS growth as the denominator of PEG:

    PEG = forward P/E / expected EPS growth percentage

A PEG below 0.75 is an acceptable screen and below 0.66 is the stricter
value band. The benchmark reasonable price uses PEG 1.00; the two lower bands
are shown separately. Dividend yield is not mixed into this calculation.
"""

from __future__ import annotations

import math
from typing import Any

PEG_ACCEPTABLE_MAX = 0.75
PEG_STRICT_MAX = 0.66
PEG_REASONABLE = 1.0


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
    eps_growth: float | int | None,
    growth_method: str = "eps_growth",
    growth_method_label: str = "EPS 成長",
) -> dict[str, Any] | None:
    """Calculate PEG, reasonable price, and the 0.75 / 0.66 value bands.

    ``eps_growth`` is decimal form: 0.30 means 30% EPS growth. The article's
    quick estimate uses expected EPS after growth and assigns a PE equal to
    the growth percentage for the PEG=1.00 benchmark price.
    """
    price = _finite(current_price)
    pe = _finite(current_pe)
    growth = _finite(eps_growth)
    if (
        price is None
        or pe is None
        or growth is None
        or price <= 0
        or pe <= 0
        or growth <= 0
    ):
        return None

    growth_pct = growth * 100.0
    current_eps = price / pe
    forward_eps = current_eps * (1.0 + growth)
    current_peg = pe / growth_pct
    reasonable_pe = growth_pct * PEG_REASONABLE
    fair_price = forward_eps * reasonable_pe
    value_price_075 = forward_eps * growth_pct * PEG_ACCEPTABLE_MAX
    value_price_066 = forward_eps * growth_pct * PEG_STRICT_MAX
    values = (current_peg, forward_eps, fair_price, value_price_075, value_price_066)
    if not all(math.isfinite(value) and value > 0 for value in values):
        return None

    return {
        "method": "zulu-peg",
        "current_price": price,
        "current_pe": pe,
        "current_eps": current_eps,
        "eps_growth": growth,
        "eps_growth_pct": growth_pct,
        "forward_eps": forward_eps,
        "current_peg": current_peg,
        "reasonable_pe": reasonable_pe,
        "fair_price": fair_price,
        "value_price_075": value_price_075,
        "value_price_066": value_price_066,
        "peg_acceptable_max": PEG_ACCEPTABLE_MAX,
        "peg_strict_max": PEG_STRICT_MAX,
        "below_075": current_peg < PEG_ACCEPTABLE_MAX,
        "below_066": current_peg < PEG_STRICT_MAX,
        "growth_method": growth_method,
        "growth_method_label": growth_method_label,
        "formula_version": "zulu-peg-eps-growth-v2",
    }
