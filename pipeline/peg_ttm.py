"""Strict trailing-twelve-month reported EPS YoY PEG evidence."""
from __future__ import annotations

from datetime import date
from calendar import monthrange
import math
from typing import Any

from pipeline.financial_periods import (
    compatible_rows, normalized_date, normalized_period, number, quarterly_income,
)

FORMULA_VERSION = "peg-ttm-yoy-v1"
GROWTH_METHOD = "ttm_reported_eps_yoy"


def _period_end(key: tuple[int, int]) -> str:
    year, quarter = key
    month = quarter * 3
    return date(year, month, monthrange(year, month)[1]).isoformat()


def _review(reason: str, current: list[dict[str, Any]] = [], prior: list[dict[str, Any]] = [], *,
            as_of: str | None = None, current_eps: float | None = None,
            prior_eps: float | None = None, growth: float | None = None,
            available_quarter_count: int | None = None) -> dict[str, Any]:
    rows = [*prior, *current]
    refs = sorted({str(row.get(field)) for row in rows for field in ("source", "sourceUrl") if row.get(field)})
    return {
        "status": "not_applicable" if reason in {"nonpositive_growth", "nonpositive_eps", "nonpositive_current_eps", "nonpositive_prior_eps", "flat_growth", "declining_growth"} else "needs_review",
        "reasonCodes": [reason],
        "currentPeriod": (f"{normalized_period(current[0])[0]}Q{normalized_period(current[0])[1]}–{normalized_period(current[-1])[0]}Q{normalized_period(current[-1])[1]}" if current else None),
        "priorPeriod": (f"{normalized_period(prior[0])[0]}Q{normalized_period(prior[0])[1]}–{normalized_period(prior[-1])[0]}Q{normalized_period(prior[-1])[1]}" if prior else None),
        "sourceRefs": refs,
        "asOf": as_of,
        "currentTtmEps": current_eps,
        "priorTtmEps": prior_eps,
        "epsGrowthPct": growth * 100 if growth is not None else None,
        "latestEvidencePublishedAt": max((published for row in rows if (published := normalized_date(row.get("publishedAt")))), default=None),
        "availableQuarterCount": available_quarter_count,
    }


def calculate_ttm_peg(rows: list[dict[str, Any]], *, as_of: str | None, price: Any,
                      reported_pe: Any = None, pe_date: Any = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Build PEG only from two consecutive comparable four-quarter EPS totals."""
    cutoff = normalized_date(as_of)
    if not cutoff:
        return None, _review("missing_as_of")
    for row in rows:
        if not isinstance(row, dict) or not normalized_period(row):
            continue
        if any(row.get(field) not in (None, "") and normalized_date(row.get(field)) is None
               for field in ("availableAt", "publishedAt", "periodEnd")):
            return None, _review("invalid_evidence_date", [row], as_of=cutoff)
    duplicate_periods: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        if isinstance(row, dict) and (key := normalized_period(row)):
            duplicate_periods.setdefault(key, []).append(row)
    for duplicates in duplicate_periods.values():
        by_period_type: dict[str, set[float]] = {}
        for row in duplicates:
            value = number(row.get("eps"))
            if value is not None:
                by_period_type.setdefault(str(row.get("periodType") or "quarter"), set()).add(value)
        if any(len(values) > 1 for values in by_period_type.values()):
            return None, _review("conflicting_duplicate_quarter")
    normalized = quarterly_income(rows)
    periods = []
    for row in normalized:
        key = normalized_period(row)
        if key and _period_end(key) <= cutoff and not any(
            (normalized_date(row.get(field)) or "")[:10] > cutoff
            for field in ("availableAt", "publishedAt", "periodEnd") if row.get(field)
        ):
            periods.append(row)
    if periods and number(periods[-1].get("eps")) is None:
        latest = periods[-1]
        return None, _review("missing_latest_quarter_eps", [latest], as_of=cutoff)
    if len(periods) < 8:
        return None, _review("insufficient_quarters", as_of=cutoff, available_quarter_count=len(periods))
    window = periods[-8:]
    keys = [normalized_period(row) for row in window]
    indices = [year * 4 + quarter for year, quarter in keys if year is not None]
    if len(indices) != 8 or any(b != a + 1 for a, b in zip(indices, indices[1:])):
        return None, _review("nonconsecutive_quarters", window[4:], window[:4], as_of=cutoff)
    prior, current = window[:4], window[4:]
    if not compatible_rows(window, eps=True):
        return None, _review("incomparable_eps_basis", current, prior, as_of=cutoff)
    eps_kinds = [row.get("epsKind") for row in window]
    if any(kind not in (None, "") for kind in eps_kinds):
        if any(kind not in {"basic", "diluted"} for kind in eps_kinds) or len(set(eps_kinds)) != 1:
            return None, _review("incomparable_eps_basis", current, prior, as_of=cutoff)
    if any(number(row.get("eps")) is None for row in window):
        return None, _review("missing_quarter_eps", current, prior, as_of=cutoff)
    prior_eps = sum(number(row["eps"]) for row in prior)
    current_eps = sum(number(row["eps"]) for row in current)
    if not math.isfinite(prior_eps) or not math.isfinite(current_eps) or prior_eps <= 0 or current_eps <= 0:
        reason = "nonpositive_prior_eps" if prior_eps <= 0 else "nonpositive_current_eps"
        diagnostic_growth = current_eps / prior_eps - 1 if prior_eps > 0 else None
        return None, _review(reason, current, prior, as_of=cutoff, current_eps=current_eps, prior_eps=prior_eps, growth=diagnostic_growth)
    growth = current_eps / prior_eps - 1
    if not math.isfinite(growth):
        return None, _review("nonpositive_growth", current, prior, as_of=cutoff, current_eps=current_eps, prior_eps=prior_eps)
    if growth <= 0:
        reason = "flat_growth" if growth == 0 else "declining_growth"
        return None, _review(reason, current, prior, as_of=cutoff, current_eps=current_eps, prior_eps=prior_eps, growth=growth)
    p = number(price)
    pe = number(reported_pe)
    same_day_pe = normalized_date(pe_date) == cutoff
    if p is None or p <= 0:
        return None, _review("missing_same_day_price", current, prior, as_of=cutoff, current_eps=current_eps, prior_eps=prior_eps, growth=growth)
    pe_origin = "reported" if same_day_pe and pe is not None and pe > 0 else "derived"
    if pe is None or pe <= 0 or not same_day_pe:
        pe = p / current_eps if p is not None and p > 0 else None
    if pe is None or pe <= 0:
        return None, _review("missing_positive_pe", current, prior, as_of=cutoff, current_eps=current_eps, prior_eps=prior_eps, growth=growth)
    if same_day_pe and abs(p / pe - current_eps) > max(0.02, 0.05 * current_eps):
        return None, _review("basis_conflict", current, prior, as_of=cutoff, current_eps=current_eps, prior_eps=prior_eps, growth=growth)
    peg = pe / (growth * 100)
    if not math.isfinite(peg) or peg <= 0:
        return None, _review("invalid_peg", current, prior, as_of=cutoff, current_eps=current_eps, prior_eps=prior_eps, growth=growth)
    refs = sorted({str(row.get(field)) for row in window for field in ("source", "sourceUrl") if row.get(field)})
    valuation = {
        "method": "zulu-peg", "formula_version": FORMULA_VERSION,
        "growth_method": GROWTH_METHOD, "growth_method_label": "TTM EPS 年增率",
        "current_price": p, "current_pe": pe, "pe_origin": pe_origin,
        "pe_source_date": cutoff if pe_origin == "reported" else None,
        "current_eps": current_eps,
        "prior_ttm_eps": prior_eps, "eps_growth": growth, "eps_growth_pct": growth * 100,
        "forward_eps": current_eps * (1 + growth), "current_peg": peg,
        "reasonable_pe": growth * 100,
        "fair_price": current_eps * (1 + growth) * growth * 100,
        "value_price_075": current_eps * (1 + growth) * growth * 75,
        "value_price_066": current_eps * (1 + growth) * growth * 66,
        "peg_acceptable_max": 0.75, "peg_strict_max": 0.66,
        "below_075": peg < 0.75, "below_066": peg < 0.66,
        "current_period": f"{keys[4][0]}Q{keys[4][1]}–{keys[7][0]}Q{keys[7][1]}",
        "prior_period": f"{keys[0][0]}Q{keys[0][1]}–{keys[3][0]}Q{keys[3][1]}",
        "source_refs": refs,
    }
    review = _review("available", current, prior, as_of=cutoff, current_eps=current_eps, prior_eps=prior_eps, growth=growth)
    review["status"] = "available"
    review["reasonCodes"] = []
    return valuation, review
