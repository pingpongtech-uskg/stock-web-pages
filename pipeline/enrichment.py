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
LOW_POSITION_Z_MAX = 0.0
LOW_BASE_Z_MAX = -1.0
MIN_QUALITY_PROXY_PASSES = 4


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


def proxy_status_reason(checks: Iterable[dict[str, Any]]) -> str:
    """Explain the aggregate proxy status using the failed/unknown rows."""

    rows = list(checks)
    failed = [f"{row.get('label', '欄位')} {row.get('value', '未知')}" for row in rows if row.get("status") == "fail"]
    unknown = [str(row.get("label", "欄位")) for row in rows if row.get("status") == "unknown"]
    if failed:
        return "未通過：" + "、".join(failed)
    if unknown:
        return "未知：" + "、".join(unknown)
    return f"{len(rows)} 項最新年度代理皆通過"


def proxy_pass_count(checks: Iterable[dict[str, Any]]) -> int:
    """Count explicit passes so a 4/5 proxy gate can be shown honestly."""

    return sum(1 for row in checks if row.get("status") == "pass")


def quality_proxy_pass_count(checks: Iterable[dict[str, Any]]) -> tuple[int, int, int]:
    """Return pass, fail, and unknown counts for the five proxy checks."""

    rows = list(checks)
    return (
        sum(row.get("status") == "pass" for row in rows),
        sum(row.get("status") == "fail" for row in rows),
        sum(row.get("status") == "unknown" for row in rows),
    )


def low_position_candidate(z: Any, slope: Any) -> bool:
    """Return whether a point belongs in the visible low-position ranking."""

    z_value = finite(z)
    slope_value = finite(slope)
    return bool(
        z_value is not None
        and slope_value is not None
        and z_value <= LOW_POSITION_Z_MAX
        and slope_value > 0
    )


def _status_text(status: str) -> str:
    return {"pass": "通過", "fail": "未通過", "unknown": "未知", "not_applicable": "不適用"}.get(status, status)


def _common_low_base_gates(
    *,
    z: Any,
    slope: Any,
    price_eligible: bool | None,
    z_maximum: float = LOW_BASE_Z_MAX,
) -> tuple[list[dict[str, Any]], str]:
    """Build the three common low-base gates.

    Institutional ranking is deliberately absent here.  It is a display sort
    and context signal; it must never remove a technically eligible stock.
    """

    z_value = finite(z)
    slope_value = finite(slope)
    price_status = "pass" if price_eligible is True else "unknown" if price_eligible is None else "fail"
    z_status = "pass" if z_value is not None and z_value <= z_maximum else "unknown" if z_value is None else "fail"
    slope_status = "pass" if slope_value is not None and slope_value > 0 else "unknown" if slope_value is None else "fail"
    gates = [
        {
            "key": "priceEligible",
            "label": "價格資料合格",
            "status": price_status,
            "value": "調整後價格回歸可用" if price_status == "pass" else "尚無合格回歸資料",
            "reason": "需要足量、覆蓋率合格的調整後價格；代理或缺值不升級為通過。",
        },
        {
            "key": "lowZ",
            "label": "四年 Z ≤ -1",
            "status": z_status,
            "value": "未知" if z_value is None else f"Z {z_value:+.2f}",
            "reason": "使用合格價格回歸的當期 Z；缺值保持 unknown。",
        },
        {
            "key": "positiveSlope",
            "label": "正向回歸 slope",
            "status": slope_status,
            "value": "未知" if slope_value is None else f"{slope_value:+.4f} / 日",
            "reason": "回歸斜率需大於 0；這是策略計算條件。",
        },
    ]
    return gates, "；".join(f"{gate['label']}：{_status_text(gate['status'])}（{gate['value']}）" for gate in gates)


def _overall_gate_status(gates: Iterable[dict[str, Any]]) -> str:
    statuses = [str(gate.get("status")) for gate in gates]
    if "fail" in statuses:
        return "fail"
    if "unknown" in statuses:
        return "unknown"
    return "pass"


def low_base_growth_gates(
    *,
    z: Any,
    slope: Any,
    price_eligible: bool | None,
    growth: Any,
    operating_profit_growth: Any = None,
    growth_minimum: float = 0.15,
    z_maximum: float = LOW_BASE_Z_MAX,
) -> dict[str, Any]:
    """Evaluate the independent low-base growth proxy route."""

    gates, _ = _common_low_base_gates(z=z, slope=slope, price_eligible=price_eligible, z_maximum=z_maximum)
    gates[1]["label"] = f"四年 Z ≤ {z_maximum:g}"
    growth_value = finite(growth)
    growth_status = growth_proxy_status(growth_value, minimum=growth_minimum)
    ttm_value = finite(operating_profit_growth)
    # TTM operating profit is an optional refinement.  Known deterioration
    # blocks the route; unavailable TTM data does not block the revenue route.
    ttm_status = "not_applicable" if ttm_value is None else "pass" if ttm_value >= 0 else "fail"
    gates.extend([
        {
            "key": "growthProxy",
            "label": "三月營收年增 ≥ 15%",
            "status": growth_status,
            "value": "未知" if growth_value is None else f"{growth_value * 100:+.1f}%",
            "reason": "三月合計營收年增代理；不能替代正式營業利益成長。",
        },
        {
            "key": "ttmOperatingProfitNonNegative",
            "label": "TTM 營業利益年增不負（可選）",
            "status": ttm_status,
            "value": "未提供" if ttm_value is None else f"{ttm_value * 100:+.1f}%",
            "reason": "若有可比 TTM 營業利益年增，負值會擋下成長代理；缺資料不作必要門檻。",
        },
    ])
    required = gates[:3] + [gates[3]]
    status = _overall_gate_status(required + [gates[4]] if ttm_status == "fail" else required)
    reason = "；".join(f"{gate['label']}：{_status_text(gate['status'])}（{gate['value']}）" for gate in gates)
    return {"status": status, "gates": gates, "reason": reason, "missing": [gate["label"] for gate in required if gate["status"] != "pass"]}


def low_base_quality_gates(
    *,
    z: Any,
    slope: Any,
    price_eligible: bool | None,
    quality_checks: Iterable[dict[str, Any]],
    minimum_quality_passes: int = MIN_QUALITY_PROXY_PASSES,
    z_maximum: float = LOW_BASE_Z_MAX,
) -> dict[str, Any]:
    """Evaluate the independent low-base quality proxy route.

    Latest net income and operating cash flow are required anchors.  The five
    checks still need at least four explicit passes; unknown anchors remain
    unknown instead of being treated as a failed or passed value.
    """

    common, _ = _common_low_base_gates(z=z, slope=slope, price_eligible=price_eligible, z_maximum=z_maximum)
    common[1]["label"] = f"四年 Z ≤ {z_maximum:g}"
    checks = list(quality_checks)
    pass_count, fail_count, unknown_count = quality_proxy_pass_count(checks)
    anchor_checks = checks[:2]
    anchor_statuses = [str(check.get("status")) for check in anchor_checks]
    anchor_status = "fail" if "fail" in anchor_statuses else "unknown" if len(anchor_checks) < 2 or "unknown" in anchor_statuses else "pass"
    quality_status = (
        "pass"
        if len(checks) >= 5 and pass_count >= minimum_quality_passes
        else "unknown"
        if len(checks) < 5 or pass_count + unknown_count >= minimum_quality_passes
        else "fail"
    )
    quality_gate = {
        "key": "qualityProxy",
        "label": "五項品質代理至少 4/5",
        "status": quality_status,
        "value": f"{pass_count}/{len(checks)} 通過",
        "reason": "最新年度五項代理需至少四項明確通過；unknown 不會補成通過。",
    }
    anchor_gate = {
        "key": "qualityAnchors",
        "label": "最新年度淨利與 CFO > 0",
        "status": anchor_status,
        "value": "兩項必要錨點通過" if anchor_status == "pass" else "必要錨點資料不足" if anchor_status == "unknown" else "至少一項錨點未通過",
        "reason": "淨利與營業現金流是低基期品質路徑必要錨點；缺資料保持 unknown。",
    }
    gates = common + [anchor_gate, quality_gate]
    status = _overall_gate_status(gates)
    reason = "；".join(f"{gate['label']}：{_status_text(gate['status'])}（{gate['value']}）" for gate in gates)
    return {
        "status": status,
        "gates": gates,
        "qualityPasses": pass_count,
        "qualityFails": fail_count,
        "qualityUnknowns": unknown_count,
        "reason": reason,
        "missing": [gate["label"] for gate in gates if gate["status"] != "pass"],
    }


def low_base_strategy_gates(
    *,
    trust_rank: int | None,
    z: Any,
    growth: Any,
    quality_checks: Iterable[dict[str, Any]],
    slope: Any = None,
    price_eligible: bool | None = True,
    growth_minimum: float = 0.15,
    max_trust_rank: int = 100,
    z_maximum: float = LOW_BASE_Z_MAX,
    minimum_quality_passes: int = MIN_QUALITY_PROXY_PASSES,
) -> dict[str, Any]:
    """Backward-compatible combined diagnostics for the two low-base routes.

    ``trust_rank`` is retained for older callers and shown as a sort context;
    it is intentionally not a hard gate for either route.
    """

    growth_result = low_base_growth_gates(
        z=z, slope=slope, price_eligible=price_eligible, growth=growth, growth_minimum=growth_minimum,
        z_maximum=z_maximum,
    )
    quality_result = low_base_quality_gates(
        z=z, slope=slope, price_eligible=price_eligible, quality_checks=quality_checks,
        minimum_quality_passes=minimum_quality_passes,
        z_maximum=z_maximum,
    )
    trust_status = "pass" if trust_rank is not None and trust_rank <= max_trust_rank else "unknown" if trust_rank is None else "fail"
    trust_gate = {
        "key": "institutionalRank",
        "label": "投信十日淨買超排序（只作排序）",
        "status": trust_status,
        "value": f"第 {trust_rank} 名" if trust_rank is not None else "未知",
        "reason": "目前追蹤範圍內的投信十日淨買超名次只用於排序與說明，不是低基期硬門檻。",
    }
    return {
        "status": "pass" if growth_result["status"] == "pass" or quality_result["status"] == "pass" else "unknown" if growth_result["status"] == "unknown" or quality_result["status"] == "unknown" else "fail",
        "gates": [trust_gate],
        "growth": growth_result,
        "quality": quality_result,
        "reason": f"投信排序：{trust_gate['value']}；成長路徑：{growth_result['status']}；品質路徑：{quality_result['status']}",
    }


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
            explanation="判定規則：單一最新年度淨利 > 0；不能替代最近三個完整年度 point-in-time 檢查。",
        ),
        proxy_check(
            "最近可得年度營業現金流（代理）",
            finite(metrics.get("latestOperatingCashFlow")),
            str(metrics.get("period") or "最近可得年度"),
            refs,
            predicate=lambda value: value > 0,
            value_format=",.0f",
            explanation="判定規則：單一最新年度營業現金流 > 0；不能替代三年 CFO 條件。",
        ),
        proxy_check(
            "最近可得年度營業利益率（代理）",
            finite(metrics.get("latestOperatingMargin")),
            str(metrics.get("period") or "最近可得年度"),
            refs,
            predicate=lambda value: value > 0,
            value_format=".1%",
            explanation="判定規則：最新年度營業利益率 > 0；此為目前可得營運品質線索。",
        ),
        proxy_check(
            "最新 ROE（代理）",
            finite(metrics.get("latestRoe")),
            str(metrics.get("period") or "最近可得年度"),
            refs,
            predicate=lambda value: value >= 0.12,
            value_format=".1%",
            explanation="判定規則：最新年度 ROE ≥ 12%；不代表三年中位數已通過。",
        ),
        proxy_check(
            "淨負債／EBITDA（代理）",
            finite(metrics.get("netDebtToEbitda")),
            str(metrics.get("period") or "最近可得年度"),
            refs,
            predicate=lambda value: value < 2,
            value_format=".2f",
            explanation="判定規則：最新淨負債／EBITDA < 2；缺少完整租賃負債時不作正式放行。",
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
