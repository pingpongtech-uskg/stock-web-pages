"""Normalize and merge public financial inputs used by growth-health gates."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable


_INCOME_FIELDS = {
    "Revenue": "revenue",
    "GrossProfit": "grossProfit",
    "OperatingIncome": "operatingProfit",
    "PreTaxIncome": "pretaxProfit",
    "IncomeAfterTaxes": "netIncome",
    "EquityAttributableToOwnersOfParent": "parentNetIncome",
    "EPS": "eps",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _period(day: Any) -> tuple[int, int, str] | None:
    text = str(day or "")[:10]
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed.year, (parsed.month - 1) // 3 + 1, text


def _month_key(row: dict[str, Any]) -> tuple[str, float] | None:
    month = str(row.get("month") or "")[:7]
    revenue = row.get("revenue")
    normalized_revenue = _number(revenue)
    if len(month) == 7 and month[4] == "-" and normalized_revenue is not None:
        return month, normalized_revenue
    raw_year = row.get("revenue_year")
    raw_month = row.get("revenue_month")
    if raw_year is None or raw_month is None:
        return None
    try:
        year = int(raw_year)
        number = int(raw_month)
    except (TypeError, ValueError):
        return None
    value = normalized_revenue
    if value is None or number not in range(1, 13):
        return None
    return f"{year:04d}-{number:02d}", value


def normalize_finmind_health_inputs(
    financial_inputs: dict[str, Any] | None,
    monthly_rows: Iterable[dict[str, Any]] | None,
    *,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Convert raw FinMind rows into the five-check evaluator contract."""
    financial_inputs = financial_inputs or {}
    grouped: dict[tuple[int, int], dict[str, Any]] = {}
    for row in financial_inputs.get("incomeStatement", []) or []:
        if not isinstance(row, dict):
            continue
        period = _period(row.get("date"))
        field = _INCOME_FIELDS.get(str(row.get("type") or ""))
        value = _number(row.get("value"))
        if period is None or field is None or value is None:
            continue
        year, quarter, available_at = period
        item = grouped.setdefault((year, quarter), {"year": year, "quarter": quarter, "availableAt": available_at})
        item[field] = value
        item["availableAt"] = max(str(item.get("availableAt") or ""), available_at)

    income = [grouped[key] for key in sorted(grouped)]
    monthly: dict[str, dict[str, Any]] = {}
    for row in monthly_rows or []:
        if not isinstance(row, dict):
            continue
        parsed = _month_key(row)
        if parsed is None:
            continue
        month, revenue = parsed
        monthly[month] = {
            "month": month,
            "revenue": revenue,
            "availableAt": row.get("availableAt") or row.get("create_time") or row.get("date"),
        }

    return {
        "source": "FinMind public datasets",
        "fetchedAt": fetched_at,
        "incomeQuarterly": income,
        "monthlyRevenueOfficial": [monthly[key] for key in sorted(monthly)],
    }


def _merge_rows(
    base: Iterable[dict[str, Any]] | None,
    overlay: Iterable[dict[str, Any]] | None,
    key_fields: tuple[str, ...],
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in [*(base or []), *(overlay or [])]:
        if not isinstance(row, dict):
            continue
        key = tuple(str(row.get(field) or "") for field in key_fields)
        if all(key):
            merged[key] = {**merged.get(key, {}), **row}
    return [merged[key] for key in sorted(merged)]


def merge_health_inputs(
    base: dict[str, Any] | None,
    overlay: dict[str, Any] | None,
) -> dict[str, Any]:
    """Preserve historical rows while overlaying newer official snapshots."""
    base = base if isinstance(base, dict) else {}
    overlay = overlay if isinstance(overlay, dict) else {}
    merged = {**base, **overlay}
    for key, fields in (
        ("incomeQuarterly", ("year", "quarter")),
        ("balanceQuarterly", ("year", "quarter")),
        ("monthlyRevenueOfficial", ("month",)),
        ("dividends", ("year", "period")),
    ):
        rows = _merge_rows(base.get(key), overlay.get(key), fields)
        if rows:
            merged[key] = rows
    for key in ("valuationUniverse",):
        if not overlay.get(key) and base.get(key):
            merged[key] = base[key]
    return merged
