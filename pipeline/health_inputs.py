"""Normalize and merge public financial inputs used by growth-health gates."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable
from pipeline.financial_periods import gregorian_year, normalized_date, normalize_row, quarterly_income, dividend_period


_INCOME_FIELDS = {
    "Revenue": "revenue",
    "GrossProfit": "grossProfit",
    "OperatingIncome": "operatingProfit",
    "PreTaxIncome": "pretaxProfit",
    "IncomeAfterTaxes": "netIncome",
    "IncomeAfterTax": "netIncome",  # FinMind bank/financial-holding spelling.
    # FinMind EquityAttributableToOwnersOfParent is comprehensive income, not net income.
    "NetIncomeAttributableToOwnersOfParent": "parentNetIncome",
    "EPS": "eps",
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _period(day: Any) -> tuple[int, int, str] | None:
    text = normalized_date(day) or ""
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed.year, (parsed.month - 1) // 3 + 1, text


def _month_key(row: dict[str, Any]) -> tuple[str, float] | None:
    month = (normalized_date(row.get("month")) or "")[:7]
    revenue = row.get("revenue")
    normalized_revenue = _number(revenue)
    if len(month) == 7 and month[4] == "-" and normalized_revenue is not None:
        return month, normalized_revenue
    raw_year = row.get("revenue_year")
    raw_month = row.get("revenue_month")
    if raw_year is None or raw_month is None:
        return None
    try:
        year = gregorian_year(raw_year)
        if year is None:
            return None
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
        year, quarter, period_end = period
        item = grouped.setdefault((year, quarter), {"year": year, "quarter": quarter, "periodEnd": period_end, "periodType": "quarter", "source": "FinMind:TaiwanStockFinancialStatements", "inputOrigin": "reported", "amountUnit": "TWD"})
        item[field] = value
        if row.get("publishedAt") or row.get("availableAt"):
            item["availableAt"] = normalized_date(row.get("publishedAt") or row.get("availableAt"))

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
        normalized = normalize_row(row)
        key = tuple(str(normalized.get(field) or "") for field in key_fields)
        if key_fields == ("year", "period"):
            period = dividend_period(normalized.get("period") or normalized.get("year"), normalized.get("year"))
            if period is not None:
                normalized["period"] = period[1]
                key = (str(period[0]), normalized["period"])
        if all(key):
            merged[key] = {**merged.get(key, {}), **{field: value for field, value in normalized.items() if value not in (None, "")}}
    return [merged[key] for key in sorted(merged)]


def merge_health_inputs(
    base: dict[str, Any] | None,
    overlay: dict[str, Any] | None,
) -> dict[str, Any]:
    """Preserve historical rows while overlaying newer official snapshots."""
    base = base if isinstance(base, dict) else {}
    overlay = overlay if isinstance(overlay, dict) else {}
    merged = {**base, **{key: value for key, value in overlay.items() if value not in (None, [], {})}}
    for key, fields in (
        ("incomeQuarterly", ("year", "quarter")),
        ("balanceQuarterly", ("year", "quarter")),
        ("monthlyRevenueOfficial", ("month",)),
        ("dividends", ("year", "period")),
    ):
        if key == "incomeQuarterly":
            income = [*(base.get(key) or []), *(overlay.get(key) or []), *(base.get("incomeYtd") or []), *(overlay.get("incomeYtd") or [])]
            cumulative = [row for row in income if isinstance(row, dict) and row.get("periodType") == "ytd"]
            if cumulative:
                merged["incomeYtd"] = _merge_rows([], cumulative, fields)
            rows = quarterly_income(income)
        else:
            rows = _merge_rows(base.get(key), overlay.get(key), fields)
        if rows:
            merged[key] = rows
    for key in ("valuationUniverse",):
        if not overlay.get(key) and base.get(key):
            merged[key] = base[key]
    return merged
