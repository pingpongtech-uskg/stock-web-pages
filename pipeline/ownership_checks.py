"""Pure evaluators for reference-only ownership/chip indicators."""

from __future__ import annotations

from datetime import date
import math
from typing import Any, Iterable

FORMULA_VERSION = "chip-reference-v1"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _month(value: Any) -> str | None:
    text = str(value or "")[:7].replace("/", "-")
    try:
        date.fromisoformat(f"{text}-01")
    except ValueError:
        return None
    return text


def _consecutive(months: list[str]) -> bool:
    parsed = [date.fromisoformat(f"{month}-01") for month in months]
    return all((current.year * 12 + current.month) == (previous.year * 12 + previous.month + 1) for previous, current in zip(parsed, parsed[1:]))


def _source_refs(rows: Iterable[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for row in rows:
        values = row.get("sourceRefs") if isinstance(row, dict) else None
        if isinstance(values, str):
            values = [values]
        for value in values or []:
            if value and value not in refs:
                refs.append(str(value))
    return refs


def _check(status: str, *, value: Any = "—", period: str | None = "—", raw_values: Any = None, explanation: str = "") -> dict[str, Any]:
    result = {"status": status, "value": value, "period": period, "rawValues": raw_values, "sourceRefs": []}
    if explanation:
        result["explanation"] = explanation
    return result


def _trend(rows: list[dict[str, Any]], field: str, *, increasing: bool, label: str) -> dict[str, Any]:
    valid: dict[str, tuple[float, dict[str, Any]]] = {}
    periods: set[str] = set()
    for row in rows:
        month = _month(row.get("period"))
        if month:
            periods.add(month)
        value = _number(row.get(field))
        if month and value is not None:
            valid[month] = (value, row)
    months = sorted(periods)[-3:]
    if len(months) != 3 or not _consecutive(months) or any(month not in valid for month in months):
        return _check("unknown", explanation=f"{label}缺少三個有效且連續月份。")
    values = [valid[month][0] for month in months]
    passed = all((left < right if increasing else left > right) for left, right in zip(values, values[1:]))
    return _check("pass" if passed else "fail", value=" → ".join(_format(value) for value in values), period=f"{months[0]}..{months[-1]}", raw_values=values, explanation=f"{label}嚴格連續趨勢。" if passed else f"{label}未符合嚴格連續趨勢。")


def _format(value: float | None) -> str:
    return f"{value:g}" if value is not None else "?"


def _director_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_month: dict[str, dict[str, Any]] = {}
    invalid_months: set[str] = set()
    for row in rows:
        month = _month(row.get("period"))
        value = _number(row.get("directorSupervisorPct"))
        denominator = _number(row.get("directorDenominator"))
        if month and (value is None or denominator is None or denominator <= 0):
            invalid_months.add(month)
        if month and value is not None and denominator is not None and denominator > 0:
            by_month[month] = row
    if not by_month:
        return _check("unknown", explanation="缺少董監持股有效月份或分母。")
    latest_month = max(by_month)
    if latest_month in invalid_months:
        return _check("unknown", explanation="最新董監持股資料無效或缺少分母。")
    latest_date = date.fromisoformat(f"{latest_month}-01")
    prior_month = f"{latest_date.year - 1:04d}-{latest_date.month:02d}"
    latest, prior = by_month.get(latest_month), by_month.get(prior_month)
    if prior is None:
        return _check("unknown", explanation="缺少恰好十二個月前的董監持股。")
    if _number(latest.get("directorDenominator")) != _number(prior.get("directorDenominator")):
        return _check("unknown", period=f"{latest_month} vs {prior_month}", explanation="最新與十二個月前分母不一致。")
    latest_value = _number(latest.get("directorSupervisorPct"))
    prior_value = _number(prior.get("directorSupervisorPct"))
    passed = latest_value is not None and prior_value is not None and latest_value >= prior_value
    return _check("pass" if passed else "fail", value=f"{_format(latest_value)}% vs {_format(prior_value)}%", period=f"{latest_month} vs {prior_month}", raw_values={"latest": latest_value, "prior12m": prior_value}, explanation="董監持股持平或上升。" if passed else "董監持股低於十二個月前。")


def evaluate_chip_reference(
    ownership_rows: Iterable[dict[str, Any]], *, data_freshness: str = "current",
    institutional_daily: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate the three frozen indicators; institutional flow is intentionally ignored."""
    rows = [row for row in ownership_rows if isinstance(row, dict)]
    large = _trend(rows, "largeHolderPct", increasing=True, label="大股東持股比重")
    director = _director_check(rows)
    shareholders = _trend(rows, "shareholderCount", increasing=False, label="總股東人數")
    refs = _source_refs(rows)
    for check in (large, director, shareholders):
        check["sourceRefs"] = refs
    statuses = [large["status"], director["status"], shareholders["status"]]
    return {
        "schemaVersion": FORMULA_VERSION,
        "status": "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass",
        "displayOnly": True,
        "formulaVersion": FORMULA_VERSION,
        "dataFreshness": data_freshness if data_freshness in {"current", "stale", "unavailable"} else "unknown",
        "largeHolderTrend": large,
        "directorSupervisor12m": director,
        "shareholderCountTrend": shareholders,
        "sourceRefs": refs,
        "availableAt": max((str(row.get("publishedAt") or row.get("asOf") or "") for row in rows), default=None),
    }


# Alternate name for callers using the indicator's domain terminology.
evaluate_ownership_chip_reference = evaluate_chip_reference
