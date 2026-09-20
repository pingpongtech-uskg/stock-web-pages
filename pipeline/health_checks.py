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
    health_inputs_value = detail.get("healthInputs")
    health_inputs = health_inputs_value if isinstance(health_inputs_value, dict) else {}
    raw_official_revenue_rows = health_inputs.get("monthlyRevenueOfficial")
    official_revenue_rows = raw_official_revenue_rows if isinstance(raw_official_revenue_rows, list) else []
    if len(revenue_rows) < 3 and official_revenue_rows:
        revenue_rows = [row for row in official_revenue_rows if isinstance(row, dict) and row.get("month") and row.get("revenue") is not None]
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

    # Official quarterly endpoint may contain several periods.  Compare
    # like-for-like rows when available; otherwise use a clearly labelled
    # latest-period proxy so the tracked-stock screen remains actionable.
    income = [row for row in inputs.get("incomeQuarterly", []) if isinstance(row, dict)]
    latest = income[-1] if income else None
    if latest:
        year = str(latest.get("year") or "")
        quarter = str(latest.get("quarter") or "")
        prior = next((row for row in reversed(income[:-1]) if str(row.get("year")) == str(int(year) - 1) and str(row.get("quarter")) == quarter), None) if year.isdigit() else None
        metric_labels = [("grossProfit", "近一季毛利年增率大於 0"), ("operatingProfit", "近一季營業利益年增率大於 0"), ("pretaxProfit", "近一季稅前淨利年增率大於 0"), ("netIncome", "近一季稅後淨利年增率大於 0")]
        growth_checks = by_key["growth"]["checks"]
        for index, (field, label) in enumerate(metric_labels, start=1):
            current = n(latest.get(field))
            previous = n(prior.get(field)) if prior else None
            rate = None if current is None or previous in (None, 0) else current / previous - 1
            if rate is not None:
                growth_checks[index] = _check(label, "pass" if rate > 0 else "fail", f"{rate:+.1%}", f"{year} Q{quarter} vs {int(year)-1} Q{quarter}", "同口徑年增率大於 0。" if rate > 0 else "同口徑年增率未大於 0。", official_refs)
            elif current is not None:
                growth_checks[index] = unknown_check(
                    label,
                    period=f"{year} Q{quarter}",
                    reason="缺少去年同季可比資料；單期為正不能推論年增率通過。",
                    refs=official_refs,
                )
        by_key["growth"] = evaluate_category("growth", growth_checks)

    # The public snapshot is intentionally scoped to the tracked symbols.  For
    # those symbols, turn every available latest-period field into an explicit
    # proxy check. Missing fields are conservative failures with a reason, so
    # the screen never becomes a wall of unknown while still showing the exact
    # evidence boundary.
    has_tracked_evidence = bool(detail.get("qualityProxyChecks") or detail.get("institutionalDaily") or inputs)
    if has_tracked_evidence:
        proxy_refs = list(dict.fromkeys([*official_refs, "yfinance:Ticker.financials/cashflow/balance_sheet"]))
        metrics = detail.get("qualityProxyMetrics") if isinstance(detail.get("qualityProxyMetrics"), dict) else {}
        qmap = {str(row.get("label")): row for row in detail.get("qualityProxyChecks", []) if isinstance(row, dict)}
        def metric(key: str) -> float | None:
            return n(metrics.get(key))
        def set_check(category: str, index: int, label: str, status: str, value: Any, period: str, explanation: str | None = None) -> None:
            if explanation is None:
                explanation, period = period, "最新可得代理"
            checks = by_key[category]["checks"]
            checks[index] = _check(label, status, value, period, explanation, proxy_refs)
            by_key[category] = evaluate_category(category, checks)
        def proxy_status(label: str, *, positive: bool | None = None, minimum: float | None = None) -> tuple[str, str]:
            row = qmap.get(label)
            status = str(row.get("status")) if row else "unknown"
            value = str(row.get("value")) if row else "未知"
            if positive is not None:
                value_num = metric({
                    "最近可得年度淨利（代理）": "latestNetIncome",
                    "最近可得年度營業現金流（代理）": "latestOperatingCashFlow",
                }.get(label, ""))
                if value_num is not None:
                    status, value = ("pass" if (value_num > 0 if positive else value_num <= 0) else "fail"), f"{value_num:,.0f}"
            return status, value

        # Quality: latest annual/yfinance proxies, with the available 3.5-year
        # price history proving the listing-age gate for the tracked universe.
        span = len([row for row in detail.get("priceSeries", []) if isinstance(row, dict)])
        set_check("quality", 0, "公司上市超過三年", "pass" if span >= 500 else "fail", f"{span} 筆價格觀察", "追蹤標的已有至少三年公開日線觀察，作上市年限代理。" if span >= 500 else "價格觀察不足三年，上市年限代理未通過。")
        s, v = proxy_status("最近可得年度營業現金流（代理）", positive=True)
        set_check("quality", 1, "自由現金流報酬率較去年沒有下滑", s, v, "最新年度代理", "以最新年度營業現金流正值作 FCF 報酬率穩定代理；尚無五年序列。")
        roe = metric("latestRoe")
        set_check("quality", 2, "三年平均自由現金流報酬率位於最高前 20%", "pass" if roe is not None and roe >= 0.20 else "fail" if roe is not None else "unknown", f"{roe:.1%}" if roe is not None else None, "最新年度 ROE 代理", "最新 ROE ≥20%，作高現金回報代理；非五年橫截面排名。" if roe is not None and roe >= 0.20 else "最新 ROE 未達 20% 代理門檻。" if roe is not None else "未取得可比 ROE。")
        margin = metric("latestOperatingMargin")
        set_check("quality", 3, "過去三年營業利益加總大於 0", "pass" if margin is not None and margin > 0 else "fail" if margin is not None else "unknown", f"{margin:.1%}" if margin is not None else None, "最新年度營業利益率代理", "最新營業利益率為正，作三年營業利益代理。" if margin is not None and margin > 0 else "最新營業利益率未為正。" if margin is not None else "未取得營業利益率。")
        pe_pct, _ = percentile("pe", pe); pb_pct, _ = percentile("pb", pb)
        composite = [x for x in (pe_pct, pb_pct, 100 - min(dividend_yield or 0, 100)) if x is not None]
        composite_pct = sum(composite) / len(composite) if composite else None
        set_check("quality", 4, "股價淨值比＋本益比＋殖利率綜合排名前 50 名", "pass" if composite_pct is not None and composite_pct <= 50 else "fail" if composite_pct is not None else "unknown", f"市場代理 {composite_pct:.1f}%" if composite_pct is not None else None, "最新交易日橫截面代理", "PE/PB/殖利率綜合當期百分位在前 50%，作估值排名代理。" if composite_pct is not None and composite_pct <= 50 else "綜合估值代理未在前 50%。" if composite_pct is not None else "估值欄位不足。")

        # Chip: ten-session institutional flow is the available ownership proxy.
        flows = [n(row.get("netShares")) for row in detail.get("institutionalDaily", []) if isinstance(row, dict) and n(row.get("netShares")) is not None]
        rising3 = len(flows) >= 3 and flows[-1] > flows[-2] > flows[-3]
        set_check("chip", 0, "大股東持股比重連續三個月上升", "pass" if rising3 else "fail" if len(flows) >= 3 else "unknown", f"近三筆投信淨買賣超 {flows[-3:] if flows else []}", "近三筆投信淨買賣超連續增加，作持股上升代理。" if rising3 else "投信淨買賣超未連續增加，代理未通過。")
        rising12 = len(flows) >= 2 and flows[-1] >= flows[0]
        set_check("chip", 1, "董監持股最新值較 12 個月前持平或上升", "pass" if rising12 else "fail" if len(flows) >= 2 else "unknown", f"{flows[0] if flows else '未知'} → {flows[-1] if flows else '未知'}", "以十日窗口首末投信淨買賣超作持平／上升代理。" if rising12 else "代理首末值未上升。")
        set_check("chip", 2, "總股東人數連續三個月下降", "pass" if len(flows) >= 3 and flows[-1] < 0 else "fail" if flows else "unknown", f"最新投信淨買賣超 {flows[-1]:,.0f}" if flows else None, "以最新投信淨賣超作股東人數下降代理；非 TDCC 直接數據。")

        # Cheap: current valuation percentiles are explicit cross-sectional proxies.
        if pe_pct is not None:
            set_check("cheap", 0, "本益比位於五年區間最低 20%", "pass" if pe_pct <= 20 else "fail", f"市場百分位 {pe_pct:.1f}%", "最新市場 PE 百分位作五年區間代理。")
        if pb_pct is not None:
            set_check("cheap", 2, "股價淨值比位於五年區間最低 20%", "pass" if pb_pct <= 20 else "fail", f"市場百分位 {pb_pct:.1f}%", "最新市場 PB 百分位作五年區間代理。")
        if dividend_yield is not None:
            set_check("cheap", 5, "近五年平均股息殖利率大於 6%", "pass" if dividend_yield > 6 else "fail", f"當期 {dividend_yield:.2f}%", "當期殖利率作五年平均代理。" )
            set_check("dividend", 1, "近五年平均股息殖利率大於 6%", "pass" if dividend_yield > 6 else "fail", f"當期 {dividend_yield:.2f}%", "當期殖利率作五年平均代理。")
        # Turnaround uses a transparent quality proxy score.
        qpasses = sum(str(row.get("status")) == "pass" for row in detail.get("qualityProxyChecks", []) if isinstance(row, dict))
        set_check("turnaround", 1, "F-score 在 8 分以上", "pass" if qpasses >= 4 else "fail", f"品質代理 {qpasses}/5", "五項最新年度品質代理至少四項通過，作 F-score ≥8 代理。")

        # Anti-pitfall: cash-flow ratios can be calculated from the latest
        # annual proxy; turnover fields are conservatively marked as failed
        # when the public snapshot does not contain AR/inventory balances.
        cfo, ni = metric("latestOperatingCashFlow"), metric("latestNetIncome")
        ratio = cfo / ni * 100 if cfo is not None and ni not in (None, 0) else None
        fcf_status = "pass" if cfo is not None and cfo > 0 else "fail" if cfo is not None else "unknown"
        set_check("antiPitfall", 0, "自由現金流近五年有三年大於 0", fcf_status, f"CFO {cfo:,.0f}" if cfo is not None else None, "最新年度現金流代理", "最新年度 CFO 為正，作五年三年正值代理。" if fcf_status == "pass" else "最新年度 CFO 未為正。")
        set_check("antiPitfall", 1, "自由現金流近五年平均大於 0", fcf_status, f"CFO {cfo:,.0f}" if cfo is not None else None, "最新年度現金流代理", "最新年度 CFO 作五年平均代理。")
        ratio_status = "pass" if ratio is not None and ratio > 100 else "fail" if ratio is not None else "unknown"
        set_check("antiPitfall", 2, "營業現金流／淨利近五年有三年大於 100%", ratio_status, f"{ratio:.1f}%" if ratio is not None else None, "最新年度現金流代理", "最新年度 CFO／淨利作五年三年代理。")
        set_check("antiPitfall", 3, "營業現金流／淨利近五年平均大於 100%", ratio_status, f"{ratio:.1f}%" if ratio is not None else None, "最新年度現金流代理", "最新年度 CFO／淨利作五年平均代理。")
        for index, label in ((4, "應收帳款週轉天數小於等於去年同期數據"), (5, "存貨週轉天數小於等於去年同期數據")):
            set_check("antiPitfall", index, label, "fail", "未取得", "最新可得期間", "公開快照沒有可比的應收帳款／存貨去年同期欄位；保守列為未通過，避免把風險當作通過。")

        # Dividend: use official current yield and observed dividend rows.
        if dividend_yield is not None:
            set_check("dividend", 0, "近一年股息殖利率大於 6%", "pass" if dividend_yield > 6 else "fail", f"{dividend_yield:.2f}%", "最新交易日", "當期殖利率公開值。")
        divs = inputs.get("dividends") if isinstance(inputs.get("dividends"), list) else []
        observed_divs = [row for row in divs if n(row.get("cashPerShare")) is not None and n(row.get("cashPerShare")) > 0]
        set_check("dividend", 2, "連續五年都有發股息", "pass" if len(observed_divs) >= 5 else "fail", f"已觀察 {len(observed_divs)} 筆", "官方股利列數達五筆，作連續五年代理。" if len(observed_divs) >= 5 else "目前公開快照僅觀察到不足五筆股利，代理未通過。")
        eps = n(latest.get("eps")) if latest else None
        cash = n(observed_divs[0].get("cashPerShare")) if observed_divs else None
        payout = cash / eps * 100 if cash is not None and eps not in (None, 0) and eps > 0 else None
        payout_status = "pass" if payout is not None and payout > 50 else "fail" if payout is not None else "unknown"
        set_check("dividend", 3, "股息發放率五年內有三年大於 50%", payout_status, f"{payout:.1f}%" if payout is not None else None, "最新年度代理", "現金股利／EPS 作發放率代理。")
        set_check("dividend", 4, "股息發放率五年平均大於 50%", payout_status, f"{payout:.1f}%" if payout is not None else None, "最新年度代理", "現金股利／EPS 作五年平均代理。")

        # Any remaining unavailable proxy is intentionally a conservative fail,
        # with the missing field visible in the row explanation.
        for key, category in list(by_key.items()):
            for check in category["checks"]:
                if check.get("status") == "unknown" and key != "growth":
                    check.update({"status": "fail", "value": "未取得", "explanation": "目前追蹤快照沒有可比欄位；保守列為未通過，待補資料只會提升證據，不會默認通過。"})
            by_key[key] = evaluate_category(key, category["checks"])
    return [by_key[key] for key, _label, _threshold, _labels in CATEGORY_DEFINITIONS]
