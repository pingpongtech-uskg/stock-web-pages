"""Transparent seven-category health checks.

The evaluator is deliberately data-contract first: a missing or incomparable
field stays ``unknown`` and is never converted to zero.  Once the normalized
annual, monthly and ownership inputs are available, the same functions can be
used by the publisher and by tests without changing the UI semantics.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable
from datetime import date


CATEGORY_DEFINITIONS: tuple[tuple[str, str, int, tuple[str, ...]], ...] = (
    ("quality", "績優股", 3, (
        "公司上市超過三年",
        "自由現金流報酬率較去年沒有下滑",
        "三年平均自由現金流報酬率位於最高前 20%",
        "過去三年營業利益加總大於 0",
        "股價淨值比＋本益比＋殖利率綜合排名前 50 名",
    )),
    ("growth", "成長股", 4, (
        "月營收 YOY 連續三個月大於 0",
        "近一季毛利年增率大於 0",
        "近一季營業利益年增率大於 0",
        "近一季稅前淨利年增率大於 0",
        "近一季稅後淨利年增率大於 0",
    )),
    ("chip", "籌碼股", 1, (
        "大股東持股比重連續三個月上升",
        "董監持股最新值較 12 個月前持平或上升",
        "總股東人數連續三個月下降",
    )),
    ("cheap", "便宜股", 5, (
        "本益比位於五年區間最低 20%",
        "本益比低於 50% 公司",
        "股價淨值比位於五年區間最低 20%",
        "股價淨值比低於 50% 公司",
        "近一年股息殖利率大於 6%",
        "近五年平均股息殖利率大於 6%",
    )),
    ("turnaround", "轉機股", 1, (
        "股價淨值比小於 3 倍",
        "F-score 在 8 分以上",
        "股價淨值比位於最低前 50 名",
    )),
    ("antiPitfall", "排除地雷股", 6, (
        "自由現金流近五年有三年大於 0",
        "自由現金流近五年平均大於 0",
        "營業現金流／淨利近五年有三年大於 100%",
        "營業現金流／淨利近五年平均大於 100%",
        "應收帳款週轉天數小於等於去年同期",
        "存貨週轉天數小於等於去年同期",
    )),
    ("dividend", "定存股", 5, (
        "近一年股息殖利率大於 6%",
        "近五年平均股息殖利率大於 6%",
        "連續五年都有發股息",
        "股息發放率五年內有三年大於 50%",
        "股息發放率五年平均大於 50%",
    )),
)

ACQUISITION_PLANS = {
    "quality": "取得 MOPS/TWSE/TPEx 五年年度損益、現金流與資產負債；以公告日對齊，計算 FCF 報酬率、三年營業利益與 ROE。估值排名由同日 PE/PB/殖利率重建。",
    "growth": "取得 MOPS/TWSE/TPEx 最近四季損益與 FinMind 月營收；將合併／單季口徑正規化後計算毛利、營業利益、稅前與稅後淨利 YOY。",
    "chip": "取得 TDCC 股權分散、MOPS 董監持股與大股東月資料；保存月份與公告日，逐月比較三個月或十二個月前。",
    "cheap": "取得 TWSE/TPEx 每日 PE、PB、殖利率與五年股利；缺少估值日欄位時以 EPS、每股淨值與現金股利同日重建百分位。",
    "turnaround": "取得同日 PB、資產負債與損益欄位；由現金流、負債、獲利能力計算 Piotroski F-score，再與同日 PB 排名合併。",
    "antiPitfall": "取得五年 CFO、CapEx、淨利、應收帳款、存貨與營收；計算 FCF、CFO/淨利及應收／存貨週轉天數並與去年同期比較。",
    "dividend": "取得公司股利公告與 TWSE/TPEx 股利資料；以除權息前價格、EPS 與現金股利重建五年殖利率及發放率序列。",
}


def _check(label: str, status: str, value: Any, period: str, explanation: str, refs: Iterable[str]) -> dict[str, Any]:
    return {
        "label": label,
        "status": status,
        "value": "未知" if value is None else str(value),
        "period": period,
        "explanation": explanation,
        "sourceRefs": list(refs),
    }


def unknown_check(label: str, *, period: str = "待建立資料期間", reason: str = "尚未完成公開資料欄位對照；不把缺資料視為未通過。", refs: Iterable[str] = ()) -> dict[str, Any]:
    return _check(label, "unknown", None, period, reason, refs)


def numeric_check(label: str, value: float | None, predicate: Callable[[float], bool], *, period: str, pass_text: str, fail_text: str, refs: Iterable[str] = ()) -> dict[str, Any]:
    if value is None:
        return unknown_check(label, period=period, refs=refs)
    return _check(label, "pass" if predicate(value) else "fail", value, period, pass_text if predicate(value) else fail_text, refs)


def evaluate_category(key: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    definition = next(item for item in CATEGORY_DEFINITIONS if item[0] == key)
    _, label, threshold, _ = definition
    statuses = [str(check.get("status")) for check in checks]
    passed = statuses.count("pass")
    failed = statuses.count("fail")
    unknown = statuses.count("unknown")
    total = len(checks)
    # A known failure can make the threshold mathematically impossible even
    # when another field is unavailable; otherwise unknown remains unknown.
    status = "fail" if failed > total - threshold else "unknown" if unknown else "pass" if passed >= threshold else "fail"
    return {"key": key, "label": label, "passCount": passed, "total": total, "threshold": threshold, "status": status, "checks": checks}


def empty_health_categories(*, reason: str = "尚未完成財報、估值、股權資料的正規化。", refs: Iterable[str] = ()) -> list[dict[str, Any]]:
    refs = list(refs)
    return [
        evaluate_category(
            key,
            [unknown_check(label, period="最近可得期間", reason=f"{reason} 取得計畫：{ACQUISITION_PLANS[key]}", refs=refs) for label in labels],
        )
        for key, _label, _threshold, labels in CATEGORY_DEFINITIONS
    ]


def health_totals(categories: Iterable[dict[str, Any]]) -> dict[str, int | str]:
    rows = list(categories)
    passed = sum(int(row.get("passCount") or 0) for row in rows)
    total = sum(int(row.get("total") or 0) for row in rows)
    status = "fail" if any(row.get("status") == "fail" for row in rows) else "unknown" if any(row.get("status") == "unknown" for row in rows) else "pass"
    return {"passCount": passed, "total": total, "status": status}


def evaluate_snapshot_health(detail: dict[str, Any], *, refs: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Fill checks that can be proven from the published snapshot today.

    This intentionally starts with monthly revenue because it is already in
    the tracked snapshot.  Additional normalized fields can be added here
    without changing category thresholds or the browser contract.
    """
    refs = list(refs)
    categories = empty_health_categories(refs=refs)
    by_key = {category["key"]: category for category in categories}
    revenue_rows = [row for row in detail.get("revenueMonthly", []) if isinstance(row, dict) and row.get("month") and row.get("revenue") is not None]
    revenue_by_month = {str(row["month"])[:7]: float(row["revenue"]) for row in revenue_rows}
    months = sorted(revenue_by_month)
    if len(months) >= 3:
        latest = months[-3:]
        pairs = [(month[:4], month[5:7]) for month in latest]
        prior = [f"{int(year) - 1:04d}-{month}" for year, month in pairs]
        values = [revenue_by_month.get(month) for month in latest]
        prior_values = [revenue_by_month.get(month) for month in prior]
        if all(value is not None and value > 0 for value in values + prior_values):
            growth_checks = by_key["growth"]["checks"]
            passed = all(current > previous for current, previous in zip(values, prior_values))
            growth_checks[0] = _check(
                "月營收 YOY 連續三個月大於 0",
                "pass" if passed else "fail",
                ", ".join(f"{current / previous - 1:+.1%}" for current, previous in zip(values, prior_values)),
                f"{latest[0]} 至 {latest[-1]}",
                "三個月逐月與去年同月比較。" if passed else "至少一個月未高於去年同月。",
                refs,
            )
            by_key["growth"] = evaluate_category("growth", growth_checks)

    inputs = detail.get("healthInputs") if isinstance(detail.get("healthInputs"), dict) else {}
    official_refs = list(dict.fromkeys([*refs, "TWSE OpenAPI"] if inputs else refs))
    valuation = inputs.get("valuationCurrent") if isinstance(inputs.get("valuationCurrent"), dict) else {}
    universe = inputs.get("valuationUniverse") if isinstance(inputs.get("valuationUniverse"), list) else []

    def n(value: Any) -> float | None:
        try:
            number = float(value)
            return number if number == number and abs(number) != float("inf") else None
        except (TypeError, ValueError):
            return None

    def percentile(field: str, value: float | None) -> tuple[float | None, int]:
        if value is None:
            return None, 0
        values = sorted(x for row in universe if isinstance(row, dict) for x in [n(row.get(field))] if x is not None and x >= 0)
        if not values:
            return None, 0
        rank = sum(x <= value for x in values)
        return rank / len(values) * 100, rank

    pe, pb, dividend_yield = n(valuation.get("pe")), n(valuation.get("pb")), n(valuation.get("dividendYield"))
    pe_pct, pe_rank = percentile("pe", pe)
    pb_pct, pb_rank = percentile("pb", pb)
    cheap_checks = by_key["cheap"]["checks"]
    if pe_pct is not None:
        cheap_checks[1] = _check("本益比低於 50% 公司", "pass" if pe_pct <= 50 else "fail", f"{pe:.2f}（市場百分位 {pe_pct:.1f}%）", "最新交易日", "當期本益比位於可取得市場資料的後 50% 以前；這是當期橫截面代理。" if pe_pct <= 50 else "當期本益比高於市場中位數；這是當期橫截面代理。", official_refs)
    if pb_pct is not None:
        cheap_checks[3] = _check("股價淨值比低於 50% 公司", "pass" if pb_pct <= 50 else "fail", f"{pb:.2f}（市場百分位 {pb_pct:.1f}%）", "最新交易日", "當期股價淨值比位於可取得市場資料的前 50% 低估區；這是當期橫截面代理。" if pb_pct <= 50 else "當期股價淨值比高於市場中位數；這是當期橫截面代理。", official_refs)
    if dividend_yield is not None:
        cheap_checks[4] = _check("近一年股息殖利率大於 6%", "pass" if dividend_yield > 6 else "fail", f"{dividend_yield:.2f}%", "最新交易日", "TWSE 當期殖利率高於 6%。" if dividend_yield > 6 else "TWSE 當期殖利率未高於 6%。", official_refs)
        by_key["dividend"]["checks"][0] = cheap_checks[4].copy()
    if pb is not None:
        by_key["turnaround"]["checks"][0] = _check("股價淨值比小於 3 倍", "pass" if pb < 3 else "fail", f"{pb:.2f} 倍", "最新交易日", "當期 PB 小於 3 倍。" if pb < 3 else "當期 PB 不小於 3 倍。", official_refs)
        if pb_rank:
            by_key["turnaround"]["checks"][2] = _check("股價淨值比位於最低前 50 名", "pass" if pb_rank <= 50 else "fail", f"第 {pb_rank} 名／{len([r for r in universe if isinstance(r, dict) and n(r.get('pb')) is not None])} 檔", "最新交易日", "當期 PB 排名進入市場最低 50 名；這是橫截面代理。" if pb_rank <= 50 else "當期 PB 未進入市場最低 50 名；這是橫截面代理。", official_refs)

    # Official quarterly endpoint may contain several periods.  Only compare
    # like-for-like year/quarter rows; a single latest row remains unknown.
    income = [row for row in inputs.get("incomeQuarterly", []) if isinstance(row, dict)]
    latest = income[-1] if income else None
    if latest:
        year = str(latest.get("year") or "")
        quarter = str(latest.get("quarter") or "")
        prior = next((row for row in reversed(income[:-1]) if str(row.get("year")) == str(int(year) - 1) and str(row.get("quarter")) == quarter), None) if year.isdigit() else None
        metric_labels = [("grossProfit", "近一季毛利年增率大於 0"), ("operatingProfit", "近一季營業利益年增率大於 0"), ("pretaxProfit", "近一季稅前淨利年增率大於 0"), ("netIncome", "近一季稅後淨利年增率大於 0")]
        if prior:
            growth_checks = by_key["growth"]["checks"]
            for index, (field, label) in enumerate(metric_labels, start=1):
                current, previous = n(latest.get(field)), n(prior.get(field))
                rate = None if current is None or previous in (None, 0) else current / previous - 1
                growth_checks[index] = _check(label, "pass" if rate is not None and rate > 0 else "fail" if rate is not None else "unknown", f"{rate:+.1%}" if rate is not None else None, f"{year} Q{quarter} vs {int(year)-1} Q{quarter}", "年增率大於 0。" if rate is not None and rate > 0 else "年增率未大於 0。" if rate is not None else "同口徑數值不足。", official_refs)
            by_key["growth"] = evaluate_category("growth", growth_checks)
    return [by_key[key] for key, _label, _threshold, _labels in CATEGORY_DEFINITIONS]
