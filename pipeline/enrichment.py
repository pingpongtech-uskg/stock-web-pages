"""Pure helpers for enriching a published stock snapshot.

The daily publisher can run with FinMind, yfinance, both, or neither.  This
module keeps the decisions about price basis, proxy checks, and candidate
states deterministic so that a source outage does not turn a useful observed
value into a fabricated formal pass.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Iterable

from pipeline.indicators import linear_regression


BAND_KEYS = ("-2", "-1", "0", "1", "2")
FOUR_YEAR_DAYS = 365 * 4
MIN_FOUR_YEAR_OBSERVATIONS = 700


def finite(value: Any) -> float | None:
    """Convert a number-like value without accepting NaN or infinity."""

    if value is None or value == "":
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def merge_adjusted_prices(
    price_points: list[dict[str, Any]],
    adjusted_rows: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge adjusted closes by date while preserving the official raw fields.

    Yahoo/yfinance rows are used for the research curve only.  The raw FinMind
    close, volume, and amount remain available for quote and execution context.
    """

    by_date: dict[str, dict[str, Any]] = {
        str(point.get("date")): dict(point)
        for point in price_points
        if point.get("date")
    }
    for row in adjusted_rows:
        day = str(row.get("date") or "")[:10]
        adjusted = finite(row.get("adjustedClose"))
        if not day or adjusted is None or adjusted <= 0:
            continue
        point = by_date.setdefault(
            day,
            {"date": day, "close": None, "volume": None, "amount": None},
        )
        point["adjustedClose"] = adjusted
    return [by_date[day] for day in sorted(by_date)]


def _day_span(points: list[dict[str, Any]]) -> int:
    days = []
    for point in points:
        try:
            days.append(date.fromisoformat(str(point.get("date"))[:10]))
        except (TypeError, ValueError):
            continue
    return (max(days) - min(days)).days if len(days) >= 2 else 0


def apply_regression(
    price_points: list[dict[str, Any]],
    *,
    prefer_adjusted: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Calculate the current four-year curve and annotate every point.

    ``adjusted`` means an adjusted close was actually supplied.  If it is not
    available, raw close is still calculated as a visible research proxy, but
    ``signalEligible`` remains false and the reason names the limitation.
    """

    adjusted_points = [
        point for point in price_points if finite(point.get("adjustedClose")) is not None
    ]
    raw_points = [point for point in price_points if finite(point.get("close")) is not None]
    use_adjusted = prefer_adjusted and bool(adjusted_points)
    basis = "adjusted" if use_adjusted else "raw_proxy" if raw_points else "unknown"
    selected = adjusted_points if use_adjusted else raw_points
    values = [
        finite(point.get("adjustedClose" if use_adjusted else "close"))
        for point in selected
    ]
    clean_values = [value for value in values if value is not None]
    result = linear_regression(clean_values)
    expected = len(raw_points) if raw_points else len(price_points)
    observations = len(clean_values)
    coverage = observations / expected * 100 if expected else None
    span_days = _day_span(selected)
    enough_history = span_days >= FOUR_YEAR_DAYS - 14
    eligible = bool(
        use_adjusted
        and result.get("reason") == "ok"
        and observations >= MIN_FOUR_YEAR_OBSERVATIONS
        and coverage is not None
        and coverage >= 95
        and enough_history
    )

    for point in price_points:
        point["mid"] = None
        point["bands"] = {key: None for key in BAND_KEYS}
    selected_ids = {id(point): index for index, point in enumerate(selected)}
    for point in selected:
        index = selected_ids[id(point)]
        intercept = result.get("intercept")
        slope = result.get("slope")
        sigma = result.get("sigma")
        if intercept is None or slope is None:
            continue
        mid = intercept + slope * index
        point["mid"] = mid
        point["bands"] = {
            key: None if sigma is None else mid + int(key) * sigma for key in BAND_KEYS
        }

    history_start = selected[0].get("date") if selected else None
    history_end = selected[-1].get("date") if selected else None
    if basis == "adjusted":
        label = "yfinance Adj Close（調整後收盤價）"
        reason = (
            "以 yfinance 明確要求 auto_adjust=False 後的 Adj Close 計算；"
            f"{observations:,} 筆有效觀察，覆蓋 {coverage:.1f}%。"
            if coverage is not None
            else "已取得 yfinance Adj Close，但觀察數不足。"
        )
    elif basis == "raw_proxy":
        label = "FinMind close（未調整 raw close proxy）"
        reason = (
            "已取得未調整收盤價，僅作行情與研究代理；"
            "公司行動／股利調整價尚未驗證，因此不產生正式四年訊號。"
        )
    else:
        label = "尚無可用價格"
        reason = "沒有足夠價格資料計算回歸。"
    regression = {
        "status": "pass" if basis == "adjusted" and result.get("reason") == "ok" else "unknown",
        "method": "lohas-linear-4y-research-v2",
        "label": label,
        "intercept": result.get("intercept"),
        "slope": result.get("slope"),
        "lastMid": result.get("last_mid"),
        "sigma": result.get("sigma"),
        "z": result.get("z"),
        "bands": {
            key: None
            if result.get("last_mid") is None or result.get("sigma") is None
            else result["last_mid"] + int(key) * result["sigma"]
            for key in BAND_KEYS
        },
        "coveragePct": coverage,
        "historyStart": history_start,
        "historyEnd": history_end,
        "signalEligible": eligible,
        "priceBasis": basis,
        "observations": observations,
        "expectedObservations": expected,
        "reason": reason,
    }
    return price_points, regression


def growth_proxy_status(
    revenue_growth: float | None,
    *,
    minimum: float = 0.15,
) -> str:
    """Return the transparent three-month revenue proxy status."""

    if revenue_growth is None or not math.isfinite(revenue_growth):
        return "unknown"
    return "pass" if revenue_growth >= minimum else "fail"


def formal_growth_status(
    revenue_growth: float | None,
    operating_profit_growth: float | None,
    *,
    minimum: float = 0.15,
) -> str:
    """Keep the quality-growth gate unknown until both financial legs exist."""

    if revenue_growth is None or operating_profit_growth is None:
        return "unknown"
    if revenue_growth < minimum or operating_profit_growth < minimum:
        return "fail"
    return "pass"


def proxy_check(
    label: str,
    value: float | None,
    period: str,
    source_refs: list[str],
    *,
    predicate: Any,
    value_format: str = ".1f",
    missing: str = "來源未回傳可比欄位",
    explanation: str,
) -> dict[str, Any]:
    """Build one RuleCheck-shaped dict for a latest-period proxy."""

    if value is None:
        return {
            "label": label,
            "status": "unknown",
            "value": "未知",
            "period": period,
            "explanation": missing,
            "sourceRefs": source_refs,
        }
    status = "pass" if predicate(value) else "fail"
    return {
        "label": label,
        "status": status,
        "value": format(value, value_format),
        "period": period,
        "explanation": explanation,
        "sourceRefs": source_refs,
    }


def proxy_status(checks: Iterable[dict[str, Any]]) -> str:
    statuses = [str(check.get("status")) for check in checks]
    if not statuses or all(status == "unknown" for status in statuses):
        return "unknown"
    if "fail" in statuses:
        return "fail"
    return "pass" if all(status == "pass" for status in statuses) else "unknown"


def quality_proxy_checks(
    metrics: dict[str, Any] | None,
    *,
    source_ref: str = "yfinance:Ticker.financials",
) -> list[dict[str, Any]]:
    """Create current-period quality evidence without calling it the formal rule."""

    metrics = metrics or {}
    refs = [source_ref]
    checks = [
        proxy_check(
            "最近可得年度淨利（代理）",
            finite(metrics.get("latestNetIncome")),
            str(metrics.get("period") or "最近可得年度"),
            refs,
            predicate=lambda value: value > 0,
            value_format=",.0f",
            explanation="單一最新年度淨利為正；不能替代最近三個完整年度 point-in-time 檢查。",
        ),
        proxy_check(
            "最近可得年度營業現金流（代理）",
            finite(metrics.get("latestOperatingCashFlow")),
            str(metrics.get("period") or "最近可得年度"),
            refs,
            predicate=lambda value: value > 0,
            value_format=",.0f",
            explanation="單一最新年度營業現金流為正；不能替代三年 CFO 條件。",
        ),
        proxy_check(
            "最近可得年度營業利益率（代理）",
            finite(metrics.get("latestOperatingMargin")),
            str(metrics.get("period") or "最近可得年度"),
            refs,
            predicate=lambda value: value > 0,
            value_format=".1%",
            explanation="營業利益率為正；此為目前可得營運品質線索。",
        ),
        proxy_check(
            "最新 ROE（代理）",
            finite(metrics.get("latestRoe")),
            str(metrics.get("period") or "最近可得年度"),
            refs,
            predicate=lambda value: value >= 0.12,
            value_format=".1%",
            explanation="最新年度 ROE 達研究門檻；不代表三年中位數已通過。",
        ),
        proxy_check(
            "淨負債／EBITDA（代理）",
            finite(metrics.get("netDebtToEbitda")),
            str(metrics.get("period") or "最近可得年度"),
            refs,
            predicate=lambda value: value < 2,
            value_format=".2f",
            explanation="最新可得資產負債資料的槓桿代理；缺少完整租賃負債時不作正式放行。",
        ),
    ]
    return checks


def derive_signal_state(
    *,
    formal_entry: bool,
    z: float | None,
    slope: float | None,
    has_route_evidence: bool,
    has_price: bool,
) -> str:
    """Apply the visible state machine with proxy low-position evidence."""

    if formal_entry:
        return "進場觀察"
    if z is not None and slope is not None and z <= 0 and slope > 0:
        return "低位觀察"
    if has_route_evidence or has_price:
        return "值得研究"
    return "資料不足"

