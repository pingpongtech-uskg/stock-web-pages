"""Pure, evidence-first growth health checks.

The five checks intentionally require like-for-like history.  A positive latest
value without its comparable prior period is ``unknown`` rather than a pass.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
import math
from typing import Any, Iterable
from pipeline.financial_periods import normalized_date, normalized_period, quarterly_income, compatible_rows

CHECK_LABELS = (
    "月營收 YOY 連續三個月大於 0",
    "近一季毛利年增率大於 0",
    "近一季營業利益年增率大於 0",
    "近一季稅前淨利年增率大於 0",
    "近一季稅後淨利年增率大於 0",
)


def growth_health_qualifies(category: object) -> bool:
    """Require four distinct confirmed passes from the actual five checks."""
    if not isinstance(category, dict):
        return False
    checks = category.get("checks")
    if not isinstance(checks, list) or len(checks) != len(CHECK_LABELS) or any(not isinstance(check, dict) for check in checks):
        return False
    if any(not isinstance(check.get("label"), str) or check.get("status") not in ("pass", "fail", "unknown") for check in checks):
        return False
    return {check["label"] for check in checks} == set(CHECK_LABELS) and sum(check["status"] == "pass" for check in checks) >= 4


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _month_key(value: Any) -> str | None:
    text = (normalized_date(value) or "")[:7]
    try:
        year, month = (int(part) for part in text.split("-"))
    except (TypeError, ValueError):
        return None
    if year < 1 or month not in range(1, 13):
        return None
    return f"{year:04d}-{month:02d}"


def _previous_year_month(month: str) -> str:
    year, number = (int(part) for part in month.split("-"))
    return f"{year - 1:04d}-{number:02d}"


def _months_are_consecutive(months: list[str]) -> bool:
    parsed = [date(int(month[:4]), int(month[5:7]), 1) for month in months]
    return all(
        (parsed[index].year * 12 + parsed[index].month)
        == (parsed[index - 1].year * 12 + parsed[index - 1].month + 1)
        for index in range(1, len(parsed))
    )


def _period(row: dict[str, Any]) -> tuple[int, int] | None:
    return normalized_period(row)


def _eligible_rows(rows: Iterable[dict[str, Any]], as_of: str | None, *, monthly: bool = False) -> list[dict[str, Any]]:
    """Filter before YTD subtraction; period end alone is not publication proof.

    Without explicit publication evidence use ordinary quarterly filing cutoffs
    (the same policy as financial_period) or the following month's revenue tenth.
    These are eligibility cutoffs, never fabricated publishedAt values.
    """
    rows = [row for row in rows if isinstance(row, dict)]
    if as_of is None:
        return rows
    cutoff = normalized_date(as_of)
    if cutoff is None or len(cutoff) != 10:
        return []
    eligible = []
    for row in rows:
        month = _month_key(row.get("month")) if monthly else None
        period = _period(row) if not monthly else None
        if monthly and month:
            year, number = int(month[:4]), int(month[5:])
            deadline = date(year + (number == 12), number % 12 + 1, 10)
        elif period:
            year, quarter = period
            number = quarter * 3
            filing_month, filing_day = {1: (5, 15), 2: (8, 15), 3: (11, 15), 4: (3, 31)}[quarter]
            deadline = date(year + (quarter == 4), filing_month, filing_day)
        else:
            continue
        period_end = date(year, number, monthrange(year, number)[1]).isoformat()
        explicit = [normalized_date(row[field]) for field in ("availableAt", "publishedAt", "reportDate", "periodEnd") if row.get(field) not in (None, "")]
        if period_end > cutoff or any(day is None or len(day) != 10 or day > cutoff for day in explicit):
            continue
        published = any(row.get(field) not in (None, "") for field in ("availableAt", "publishedAt", "reportDate"))
        if published or deadline.isoformat() <= cutoff:
            eligible.append(row)
    return eligible


def _sources(rows: Iterable[dict[str, Any] | None]) -> list[str]:
    refs = []
    for row in rows:
        if row:
            refs.extend(str(ref) for ref in row.get("sourceRefs", []) if ref)
            if row.get("source"):
                refs.append(str(row["source"]))
    return list(dict.fromkeys(refs))


def _check(label: str, status: str, value: Any, explanation: str, *, period: str = "待建立資料期間", refs: Iterable[str] = ()) -> dict[str, Any]:
    return {"label": label, "status": status, "value": value, "explanation": explanation, "period": period, "sourceRefs": list(refs)}


def _summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [check["status"] for check in checks]
    passed = statuses.count("pass")
    return {
        "checks": checks,
        "passCount": passed,
        "total": len(checks),
        "status": "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass",
    }


def _monthly_check(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    by_month: dict[str, float] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        month = _month_key(row.get("month"))
        revenue = _number(row.get("revenue"))
        if month is not None and revenue is not None:
            by_month[month] = revenue
            evidence[month] = row
            prior = _number(row.get("priorYearRevenue"))
            if prior is not None:
                by_month.setdefault(_previous_year_month(month), prior)
                evidence.setdefault(_previous_year_month(month), row)
    months = sorted(by_month)[-3:]
    if len(months) != 3 or not _months_are_consecutive(months):
        return _check(CHECK_LABELS[0], "unknown", None, "最近三個月資料不足或月份不連續，無法完成三個月同月比較。")
    prior_months = [_previous_year_month(month) for month in months]
    period = f"{months[0]}–{months[-1]} vs {prior_months[0]}–{prior_months[-1]}"
    refs = _sources(evidence.get(month) for month in [*months, *prior_months])
    prior = [by_month.get(month) for month in prior_months]
    current = [by_month[month] for month in months]
    if any(value is None for value in prior):
        return _check(CHECK_LABELS[0], "unknown", None, "缺少至少一個去年同月營收，不能把單月正值視為通過。", period=period, refs=refs)
    rates = [now / before - 1 for now, before in zip(current, prior) if before is not None and before > 0]
    if len(rates) != 3:
        return _check(CHECK_LABELS[0], "unknown", None, "去年同月營收為零或非正值，無法計算完整 YOY。", period=period, refs=refs)
    passed = all(rate > 0 for rate in rates)
    return _check(CHECK_LABELS[0], "pass" if passed else "fail", rates, "三個月逐月同去年同月比較皆為正。" if passed else "三個月中至少一個月 YOY 未大於零。", period=period, refs=refs)


def _quarter_checks(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    periods: dict[tuple[int, int], dict[str, Any]] = {}
    for row in quarterly_income(rows):
        if isinstance(row, dict) and (key := _period(row)) is not None:
            periods[key] = row
    latest_period = max(periods, default=None)
    labels_fields = (
        (CHECK_LABELS[1], ("grossProfit",)),
        (CHECK_LABELS[2], ("operatingProfit",)),
        (CHECK_LABELS[3], ("pretaxProfit", "pretaxNetIncome")),
        (CHECK_LABELS[4], ("netIncome", "parentNetIncome")),
    )
    if latest_period is None:
        return [_check(label, "unknown", None, "缺少最近一季財報。") for label, _fields in labels_fields]
    latest = periods[latest_period]
    prior = periods.get((latest_period[0] - 1, latest_period[1]))
    period = f"{latest_period[0]} Q{latest_period[1]} vs {latest_period[0] - 1} Q{latest_period[1]}"
    refs = _sources([latest, prior])
    checks = []
    for label, fields in labels_fields:
        pair = next(((_number(latest.get(field)), _number(prior.get(field))) for field in fields
                     if prior and _number(latest.get(field)) is not None and _number(prior.get(field)) is not None), (None, None))
        current, previous = pair
        if current is None or previous is None or previous <= 0 or not compatible_rows([latest, prior]):
            checks.append(_check(label, "unknown", None, "缺少截至評估日可取得的同季、同欄位且正基期數值，或比較口徑不一致；最新單期正值不構成通過。", period=period, refs=refs))
            continue
        rate = current / previous - 1
        checks.append(_check(label, "pass" if rate > 0 else "fail", rate, "同口徑最近一季 YOY 大於零。" if rate > 0 else "同口徑最近一季 YOY 未大於零。", period=period, refs=refs))
    return checks


def evaluate_growth_health(monthly_revenue: Iterable[dict[str, Any]], quarterly_income: Iterable[dict[str, Any]], *, as_of: str | None = None) -> dict[str, Any]:
    """Evaluate the five growth-health checks with explicit unknown states."""
    income = [row for row in quarterly_income if isinstance(row, dict)]
    raw_ytd_periods = {_period(row) for row in income if row.get("periodType") == "ytd"}
    # Rebuild cached differences from eligible raw evidence, never from a future
    # predecessor that was already subtracted during an earlier normalization.
    income = [row for row in income if not (row.get("derivationMethod") and _period(row) in raw_ytd_periods)]
    return _summary([_monthly_check(_eligible_rows(monthly_revenue, as_of, monthly=True)),
                     *_quarter_checks(_eligible_rows(income, as_of))])
