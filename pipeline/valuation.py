"""Valuation methods used by the published research snapshot.

The three strategy cards retain the Zulu PEG as a cross-check metric.  The
growth strategy's primary valuation is the documented Chen Qiaohong video-style
total-return P/E.  These are deliberately separate methods and versions.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Any

PEG_ACCEPTABLE_MAX = 0.75
PEG_STRICT_MAX = 0.66
PEG_REASONABLE = 1.0

GROWTH_TOTAL_RETURN_FORMULA_VERSION = "growth-total-return-pe-v1"
GROWTH_FORECAST_HAIRCUT = 0.8
GROWTH_UNDERVALUED_MIN = 1.2
GROWTH_REASONABLE_MIN = 0.8
GROWTH_EXTREME_RATE_MAX = 1.0
GROWTH_EXTREME_PRICE_RATIO_MAX = 3.0
GROWTH_MIN_VALID_ANNUAL_YEARS = 4


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
    """Calculate the Zulu PEG cross-check and its price bands."""
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


def _annual_eps(rows: list[dict[str, Any]]) -> dict[int, float]:
    grouped: dict[int, dict[int, float]] = defaultdict(dict)
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            year = int(str(row.get("year")))
            quarter = int(str(row.get("quarter")))
            eps = float(row.get("eps"))
        except (TypeError, ValueError):
            continue
        if quarter not in {1, 2, 3, 4} or not math.isfinite(eps):
            continue
        grouped[year][quarter] = eps

    result: dict[int, float] = {}
    for year, quarters in grouped.items():
        if set(quarters) != {1, 2, 3, 4}:
            continue
        total = sum(quarters.values())
        if math.isfinite(total) and total > 0:
            result[year] = total
    return result


def _ttm_eps(rows: list[dict[str, Any]]) -> float | None:
    ordered: list[tuple[int, int, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            year = int(str(row.get("year")))
            quarter = int(str(row.get("quarter")))
            eps = float(row.get("eps"))
        except (TypeError, ValueError):
            continue
        if quarter in {1, 2, 3, 4} and math.isfinite(eps):
            ordered.append((year, quarter, eps))
    ordered.sort(key=lambda item: (item[0], item[1]))
    if len(ordered) < 4:
        return None
    value = sum(item[2] for item in ordered[-4:])
    return value if math.isfinite(value) and value > 0 else None


def derive_ttm_eps(rows: list[dict[str, Any]]) -> float | None:
    """Return the latest four reported quarters' EPS total."""
    return _ttm_eps(rows)


def derive_stable_eps_growth(
    rows: list[dict[str, Any]],
    *,
    min_valid_years: int = GROWTH_MIN_VALID_ANNUAL_YEARS,
) -> dict[str, Any]:
    """Derive multi-year EPS growth without substituting revenue growth."""
    annual = _annual_eps(rows)
    years = sorted(annual)[-5:]
    if len(years) < min_valid_years:
        return {
            "method": "no_stable_growth",
            "method_label": "完整年度 EPS 資料不足",
            "growth": None,
            "valid_years": len(years),
            "annual_eps": annual,
        }

    first_year, last_year = years[0], years[-1]
    first_eps, last_eps = annual[first_year], annual[last_year]
    span = last_year - first_year
    if first_eps > 0 and last_eps > 0 and span > 0:
        growth = (last_eps / first_eps) ** (1.0 / span) - 1.0
        if math.isfinite(growth):
            return {
                "method": "five_year_eps_cagr",
                "method_label": "多年度 EPS CAGR（可得完整年度）",
                "growth": growth,
                "valid_years": len(years),
                "growth_years": span,
                "annual_eps": annual,
            }

    rates = [
        annual[current] / annual[previous] - 1.0
        for previous, current in zip(years, years[1:])
        if annual[previous] > 0 and annual[current] > 0
    ]
    rates = [rate for rate in rates if math.isfinite(rate)]
    if rates:
        return {
            "method": "median_annual_eps_growth",
            "method_label": "有效年度 EPS 成長中位數",
            "growth": statistics.median(rates),
            "valid_years": len(years),
            "growth_years": len(rates),
            "annual_eps": annual,
        }
    return {
        "method": "no_stable_growth",
        "method_label": "有效年度 EPS 成長不足",
        "growth": None,
        "valid_years": len(years),
        "annual_eps": annual,
    }


def calculate_growth_total_return_valuation(
    *,
    current_price: float | int | None,
    current_pe: float | int | None,
    ttm_eps: float | int | None,
    earnings_growth: float | int | None,
    dividend_yield: float | int | None,
    growth_method: str = "five_year_eps_cagr",
    growth_method_label: str = "多年度 EPS CAGR（可得完整年度）",
) -> dict[str, Any]:
    """Calculate the documented video-style total-return P/E valuation."""
    price = _finite(current_price)
    pe = _finite(current_pe)
    eps = _finite(ttm_eps)
    growth = _finite(earnings_growth)
    dividend = _finite(dividend_yield)

    base: dict[str, Any] = {
        "method": "growth-total-return-pe",
        "formula_version": GROWTH_TOTAL_RETURN_FORMULA_VERSION,
        "status": "unavailable",
        "reason": "",
        "current_price": price,
        "current_pe": pe,
        "ttm_eps": eps,
        "earnings_growth": growth,
        "growth_method": growth_method,
        "growth_method_label": growth_method_label,
        "dividend_yield": dividend,
        "conservative_growth": None,
        "total_return_pct": None,
        "total_return_pe": None,
        "forward_eps": None,
        "fair_pe": None,
        "fair_price": None,
        "buy_zone_price": None,
        "undervalued": False,
        "reasonable": False,
        "extreme_extrapolation": False,
    }
    if price is None or price <= 0 or pe is None or pe <= 0 or eps is None or eps <= 0:
        base["reason"] = "缺少正確的現價、PE 或 TTM EPS"
        return base
    if growth is None or growth <= 0:
        base["reason"] = "缺少可驗證的正向多年度 EPS 成長"
        return base
    if dividend is None or dividend < 0:
        base["reason"] = "缺少已確認現金股利資料"
        return base

    conservative = growth * GROWTH_FORECAST_HAIRCUT
    total_return_pct = (conservative + dividend) * 100.0
    total_return_pe = total_return_pct / pe
    forward_eps = eps * (1.0 + conservative)
    fair_pe = total_return_pct
    fair_price = forward_eps * fair_pe
    buy_zone_price = forward_eps * (fair_pe / GROWTH_UNDERVALUED_MIN)
    finite_values = (conservative, total_return_pct, total_return_pe, forward_eps, fair_price, buy_zone_price)
    if not all(math.isfinite(value) and value > 0 for value in finite_values):
        base["reason"] = "估值結果非有限正數"
        return base

    extreme = growth > GROWTH_EXTREME_RATE_MAX or fair_price / price > GROWTH_EXTREME_PRICE_RATIO_MAX
    base.update(
        {
            "status": "extreme" if extreme else "available",
            "reason": "基期效應／極端外推，不發布主合理價" if extreme else "可用的影片版總報酬本益比",
            "conservative_growth": conservative,
            "total_return_pct": total_return_pct,
            "total_return_pe": total_return_pe,
            "forward_eps": forward_eps,
            "fair_pe": fair_pe,
            "fair_price": None if extreme else fair_price,
            "buy_zone_price": None if extreme else buy_zone_price,
            "undervalued": total_return_pe >= GROWTH_UNDERVALUED_MIN,
            "reasonable": GROWTH_REASONABLE_MIN <= total_return_pe < GROWTH_UNDERVALUED_MIN,
            "extreme_extrapolation": extreme,
            "raw_fair_price": fair_price,
        }
    )
    return base
