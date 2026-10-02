"""Valuation methods used by the published research snapshot.

The growth strategy uses a documented total-return P/E reference method.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any
from datetime import date
from calendar import monthrange
from pipeline.financial_periods import normalized_period, quarterly_income, compatible_rows, normalized_date, gregorian_year, number, dividend_period

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


def _validated_eps_rows(rows: list[dict[str, Any]], as_of: str | None = None) -> list[dict[str, Any]]:
    cutoff = normalized_date(as_of) if as_of else None
    result = []
    for row in quarterly_income(rows):
        year, quarter = normalized_period(row)
        period_end = date(year, quarter * 3, monthrange(year, quarter * 3)[1]).isoformat()
        if cutoff and period_end > cutoff:
            continue
        if cutoff and any(str(row.get(field) or "")[:10] > cutoff for field in ("availableAt", "publishedAt", "periodEnd")):
            continue
        if _finite(row.get("eps")) is not None:
            result.append(row)
    return result


def _annual_eps(rows: list[dict[str, Any]], as_of: str | None = None) -> dict[int, float]:
    grouped: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)
    cutoff_year = int((normalized_date(as_of) or str(date.today()))[:4])
    for row in _validated_eps_rows(rows, as_of):
        year, quarter = normalized_period(row)
        if year < cutoff_year:
            grouped[year][quarter] = row
    result = {}
    for year, quarters in grouped.items():
        if set(quarters) == {1, 2, 3, 4} and compatible_rows(quarters.values(), eps=True):
            total = sum(float(row["eps"]) for row in quarters.values())
            if math.isfinite(total):
                result[year] = total
    return result


def derive_ttm_eps(rows: list[dict[str, Any]], *, as_of: str | None = None) -> float | None:
    """Return four unique consecutive quarters on a comparable EPS basis."""
    return _ttm_eps_evidence(rows, as_of=as_of)[0]


def _ttm_eps_evidence(rows: list[dict[str, Any]], *, as_of: str | None = None) -> tuple[float | None, str | None]:
    """Keep the unavailable reason aligned with the exact calculation guard."""
    normalized = quarterly_income(rows)
    window = normalized[-4:]
    if len(window) < 4:
        return None, "insufficient_quarters"
    if not compatible_rows(window, eps=True):
        return None, "incomparable_quarters"
    keys = [normalized_period(row) for row in window]
    indices = [year * 4 + quarter for year, quarter in keys]
    if any(current != previous + 1 for previous, current in zip(indices, indices[1:])):
        return None, "nonconsecutive_quarters"
    eligible = _validated_eps_rows(window, as_of)
    if len(eligible) != 4:
        return None, "missing_or_unavailable_quarter_eps"
    total = sum(float(row["eps"]) for row in eligible)
    return (total, None) if math.isfinite(total) and total > 0 else (None, "nonpositive_ttm_eps")


def derive_stable_eps_growth(
    rows: list[dict[str, Any]],
    *,
    min_valid_years: int = GROWTH_MIN_VALID_ANNUAL_YEARS,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Derive multi-year EPS growth without substituting revenue growth."""
    annual = _annual_eps(rows, as_of)
    years = sorted(annual)[-5:]
    comparable = compatible_rows([row for row in _validated_eps_rows(rows, as_of) if normalized_period(row)[0] in years], eps=True)
    if len(years) < min_valid_years or not comparable or any(annual[year] <= 0 for year in years):
        return {
            "method": "no_stable_growth",
            "method_label": "完整年度 EPS 資料不足" if len(years) < min_valid_years else "年度 EPS 口徑不一致" if not comparable else "完整年度 EPS 包含非正值",
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
                "method_label": f"EPS CAGR（{first_year}–{last_year}，{span} 年跨度）",
                "start_year": first_year,
                "end_year": last_year,
                "growth": growth,
                "valid_years": len(years),
                "growth_years": span,
                "annual_eps": annual,
            }

    return {
        "method": "no_stable_growth",
        "method_label": "有效年度 EPS 成長不足",
        "growth": None,
        "valid_years": len(years),
        "annual_eps": annual,
    }


def derive_growth_inputs(detail: dict[str, Any]) -> dict[str, Any]:
    """Share primary EPS/PE evidence between the producer and retrieval planner."""
    health = detail.get("healthInputs") or {}
    rows = quarterly_income(health.get("incomeQuarterly", []))
    cutoff = normalized_date(detail.get("asOf"))
    action_years = [gregorian_year(row.get("year")) for row in health.get("dividends", [])
                    if isinstance(row, dict) and (number(row.get("stockPerShare")) or 0) > 0]
    raw_dividends = (detail.get("financialInputs") or {}).get("dividend", [])
    action_years += [(dividend_period(row.get("year")) or (gregorian_year(str(row.get("date") or "")[:4]), ""))[0]
                     for row in raw_dividends if isinstance(row, dict) and any(
                         (number(row.get(key)) or 0) > 0
                         for key in ("StockEarningsDistribution", "StockStatutorySurplus"))]
    periods = [row["year"] for row in rows]
    if periods and any(year is not None and min(periods) <= year <= max(periods) for year in action_years):
        rows = [{**row, "epsComparable": False} if not row.get("epsBasis") else row for row in rows]
    growth = derive_stable_eps_growth(rows, as_of=cutoff)
    eps, eps_reason = _ttm_eps_evidence(rows, as_of=cutoff)
    price = _finite(detail.get("lastPrice")) if cutoff else None
    price_origin = "reported" if price is not None and price > 0 else "unavailable"
    quotes = [row for row in detail.get("priceSeries", []) if isinstance(row, dict)]
    if quotes:
        matching = [row for row in quotes if normalized_date(row.get("date")) == cutoff]
        closes = [number(row.get("close")) for row in matching]
        price = next((value for value in reversed(closes) if value is not None and value > 0), None)
        price_origin = "reported" if price is not None else "proxy" if any(number(row.get("adjustedClose")) is not None for row in matching) else "unavailable"
    valuation = health.get("valuationCurrent") or {}
    reported_pe = number(valuation.get("pe"))
    same_day_pe = normalized_date(valuation.get("date")) == cutoff
    pe = reported_pe if same_day_pe and reported_pe is not None and reported_pe > 0 else None
    pe_origin = "reported" if pe is not None else "unavailable"
    if pe is None and eps is not None and price is not None and price > 0:
        pe, pe_origin = price / eps, "derived"
    return {"rows": rows, "growth": growth, "ttm_eps": eps, "current_price": price,
            "current_pe": pe, "price_origin": price_origin, "pe_origin": pe_origin,
            "cutoff": cutoff, "reported_pe": reported_pe, "same_day_pe": same_day_pe,
            "ttm_eps_reason": eps_reason}


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
    """Calculate the documented total-return P/E valuation."""
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
            "reason": "基期效應／極端外推，不發布主合理價" if extreme else "可用的總報酬本益比（本站整理）",
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
