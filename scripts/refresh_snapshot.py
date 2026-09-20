#!/usr/bin/env python3
"""Enrich the checked-in research snapshot with free adjusted prices.

The FinMind job and this enrichment job are intentionally separate.  The
FinMind job can refresh official Taiwan price/volume, institutional, and
revenue rows when its token is available.  This script then reuses that same
run and tries yfinance for adjusted prices plus latest-period financial
proxies.  If either source is unavailable, existing observed rows stay
visible, and every fallback is labelled in the published contract.

Typical CI invocation::

    python -m pip install -r requirements.txt
    python scripts/refresh_snapshot.py --output public/data

The browser never calls Yahoo or FinMind and no API token is written to the
published files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.enrichment import (  # noqa: E402
    apply_regression,
    clip_price_window,
    derive_signal_state,
    formal_growth_status,
    growth_proxy_status,
    low_base_growth_gates,
    low_base_quality_gates,
    LOW_POSITION_Z_MAX,
    MIN_QUALITY_PROXY_PASSES,
    merge_adjusted_prices,
    proxy_status,
    proxy_status_reason,
    proxy_pass_count,
    quality_proxy_checks,
)
from pipeline.health_checks import evaluate_snapshot_health, health_totals  # noqa: E402
from pipeline.yahoo_client import (  # noqa: E402
    YAHOO_CHART_SOURCE,
    YFINANCE_FUNDAMENTAL_SOURCE,
    YFINANCE_PRICE_SOURCE,
    fetch_adjusted_history,
    fetch_fundamental_proxies,
)
from pipeline.twse_public import SOURCE as TWSE_SOURCE, build_health_inputs  # noqa: E402
from pipeline.earnings_proxy import derive_ltm_eps_proxy  # noqa: E402
from pipeline.release_contract import (  # noqa: E402
    FORMULA_VERSIONS,
    compute_funnel,
    is_common_stock_code,
)
from pipeline.institutional_ranking import annotate_top_n_entries  # noqa: E402
from pipeline.valuation import calculate_zulu_valuation  # noqa: E402


TAIPEI = ZoneInfo("Asia/Taipei")
BAND_KEYS = ("-2", "-1", "0", "1", "2")
GROWTH_MIN = 0.15


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def merge_refs(*groups: list[str] | None) -> list[str]:
    result: list[str] = []
    for group in groups:
        for value in group or []:
            if value and value not in result:
                result.append(value)
    return result


def parse_date(value: str | None, fallback: date) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return fallback


def _git_head() -> str | None:
    """Record the code commit that produced a release, when git is available."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def baseline_details(data_dir: Path, release: dict[str, Any]) -> list[dict[str, Any]]:
    run_id = str(release.get("runId") or "")
    result: list[dict[str, Any]] = []
    known_codes: set[str] = set()
    for summary in release.get("stocks", []):
        if not isinstance(summary, dict):
            continue
        code = str(summary.get("code") or "")
        if not code:
            continue
        path = data_dir / "releases" / run_id / "stocks" / f"{code}.json"
        if path.exists():
            try:
                detail = load_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                detail = dict(summary)
        else:
            detail = dict(summary)
        detail.setdefault("priceSeries", [])
        detail.setdefault("institutionalDaily", [])
        detail.setdefault("revenueMonthly", [])
        detail.setdefault("qualityChecks", [])
        detail.setdefault("qualityProxyChecks", [])
        detail.setdefault("historySnapshots", [])
        detail.setdefault("notes", [])
        detail.setdefault("detailLimitations", [])
        result.append(detail)
        known_codes.add(code)

    # Keep the checked-in snapshot aligned with the versioned tracked universe
    # even when a newly added symbol has not completed its first API fetch.
    # The placeholder is explicit unknown data and can never become a signal
    # without a later source-backed enrichment.
    config_path = data_dir.parent.parent / "config" / "tracked_symbols.json"
    try:
        config = load_json(config_path)
    except (OSError, ValueError, json.JSONDecodeError):
        config = {}
    symbols = config.get("symbols") if isinstance(config, dict) else None
    metadata = config.get("metadata") if isinstance(config, dict) and isinstance(config.get("metadata"), dict) else {}
    if isinstance(symbols, list):
        allowed_codes = {str(raw_code).strip() for raw_code in symbols if str(raw_code).strip()}
        # The published A list is the complete research universe.  Drop
        # symbols left over from older snapshots so every strategy and every
        # coverage count describes the same 100-stock mother set.
        result = [detail for detail in result if str(detail.get("code") or "") in allowed_codes]
        known_codes = {str(detail.get("code") or "") for detail in result}
        for raw_code in symbols:
            code = str(raw_code).strip()
            if not code or code in known_codes:
                continue
            info = metadata.get(code) if isinstance(metadata, dict) and isinstance(metadata.get(code), dict) else {}
            placeholder = {
                "code": code,
                "name": str(info.get("name") or code),
                "market": str(info.get("market") or "unknown"),
                "sector": str(info.get("sector") or ""),
                "asOf": None,
                "lastPrice": None,
                "changePct": None,
                "zScore": None,
                "slope": None,
                "fiveLineStatus": "unknown",
                "qualityStatus": "unknown",
                "growthStatus": "unknown",
                "liquidityStatus": "unknown",
                "dataStatus": "unknown",
                "signalState": "資料不足",
                "entryReasons": ["尚未完成首次資料抓取；所有策略 gate 保持 unknown"],
                "risks": ["新加入追蹤標的尚無可用來源資料"],
                "institutionNetShares10": None,
                "participation10": None,
                "positiveDays10": None,
                "revenueGrowth3m": None,
                "ttmOperatingProfitGrowth": None,
                "sourceRefs": [],
            }
            for key, value in (
                ("priceSeries", []),
                ("institutionalDaily", []),
                ("revenueMonthly", []),
                ("qualityChecks", []),
                ("qualityProxyChecks", []),
                ("historySnapshots", []),
                ("notes", []),
                ("detailLimitations", ["尚未完成首次資料抓取；不將缺值轉成 0。"]),
            ):
                placeholder[key] = value
            result.append(placeholder)
            known_codes.add(code)
    return result


def _current_price(detail: dict[str, Any]) -> float | None:
    value = detail.get("lastPrice")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _current_adjusted(detail: dict[str, Any]) -> float | None:
    values = [point.get("adjustedClose") for point in detail.get("priceSeries", []) if isinstance(point, dict)]
    for value in reversed(values):
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _shares_from_detail(detail: dict[str, Any]) -> float | None:
    for key in ("sharesOutstanding", "shares", "shareCount"):
        value = detail.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0:
            return float(value)
    health_inputs = detail.get("healthInputs")
    if not isinstance(health_inputs, dict):
        return None
    balances = [row for row in health_inputs.get("balanceQuarterly", []) if isinstance(row, dict)]
    for row in reversed(balances):
        equity = row.get("equity")
        book_value = row.get("bookValuePerShare")
        if isinstance(equity, (int, float)) and isinstance(book_value, (int, float)) and float(equity) > 0 and float(book_value) > 0:
            return float(equity) / float(book_value)
    return None


def _ltm_revenue_growth(detail: dict[str, Any]) -> float | None:
    health_inputs = detail.get("healthInputs")
    rows = health_inputs.get("monthlyRevenueOfficial", []) if isinstance(health_inputs, dict) else []
    if not rows:
        rows = detail.get("revenueMonthly", [])
    by_month: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        month = str(row.get("month") or "")[:7]
        value = row.get("revenue")
        if len(month) == 7 and month[4] == "-" and isinstance(value, (int, float)) and math.isfinite(float(value)):
            by_month[month] = float(value)
    months = sorted(by_month)
    if len(months) < 24:
        return None
    current = months[-12:]
    prior = [f"{int(month[:4]) - 1:04d}-{month[5:7]}" for month in current]
    if any(month not in by_month for month in prior):
        return None
    current_total = sum(by_month[month] for month in current)
    prior_total = sum(by_month[month] for month in prior)
    if prior_total <= 0:
        return None
    return current_total / prior_total - 1.0


def _earnings_proxy_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    health_inputs = detail.get("healthInputs")
    rows = health_inputs.get("incomeQuarterly", []) if isinstance(health_inputs, dict) else []
    proxy = derive_ltm_eps_proxy([row for row in rows if isinstance(row, dict)], shares=_shares_from_detail(detail))
    if proxy.get("growth") is not None:
        return proxy
    ltm_revenue_growth = _ltm_revenue_growth(detail)
    if ltm_revenue_growth is not None:
        return {"method": "ltm_revenue_proxy", "method_label": "LTM 營收成長代理", "growth": ltm_revenue_growth, "current_eps": None, "prior_eps": None}
    fallback = detail.get("revenueGrowth3m")
    if fallback is None:
        fallback = detail.get("revenueGrowthProxy")
    if isinstance(fallback, (int, float)) and math.isfinite(float(fallback)) and float(fallback) > 0:
        return {"method": "three_month_revenue_proxy", "method_label": "三月營收成長代理", "growth": float(fallback), "current_eps": None, "prior_eps": None}
    return {"method": "no_growth_input", "method_label": "可用營收與財務資料不足", "growth": None, "current_eps": None, "prior_eps": None}


def _valuation_from_detail(detail: dict[str, Any]) -> dict[str, Any] | None:
    """Build Zulu PEG from the best known earnings-growth proxy."""
    health_inputs = detail.get("healthInputs")
    valuation_current = health_inputs.get("valuationCurrent") if isinstance(health_inputs, dict) else None
    if not isinstance(valuation_current, dict):
        valuation_current = {}
    proxy = _earnings_proxy_from_detail(detail)
    valuation = calculate_zulu_valuation(
        current_price=_current_price(detail),
        current_pe=valuation_current.get("pe"),
        eps_growth=proxy.get("growth"),
        growth_method=str(proxy.get("method") or "eps_growth"),
        growth_method_label=str(proxy.get("method_label") or "EPS 成長"),
    )
    if valuation is not None:
        valuation["proxy_current_eps"] = proxy.get("current_eps")
        valuation["proxy_prior_eps"] = proxy.get("prior_eps")
    return valuation


def _attach_valuation(
    rows: list[dict[str, Any]],
    detail_by_code: dict[str, dict[str, Any]],
    *,
    require_peg_below_075: bool = True,
) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("code"))
        # PEG 股票策略只服務普通股；ETF／ETN／權證類代碼在此排除，
        # 排除數另由 funnel.instrumentExcluded 誠實揭露。
        if not is_common_stock_code(code):
            continue
        detail = detail_by_code.get(code, {})
        valuation = detail.get("valuation")
        if not isinstance(valuation, dict):
            continue
        if require_peg_below_075 and not valuation.get("below_075"):
            continue
        growth_method = str(valuation.get("growth_method") or "")
        growth_method_label = str(valuation.get("growth_method_label") or "")
        is_proxy = "proxy" in growth_method or "代理" in growth_method_label
        growth_input = valuation.get("eps_growth")
        fair_price = valuation.get("fair_price")
        current_price = valuation.get("current_price")
        extreme = False
        if is_proxy and isinstance(growth_input, (int, float)) and math.isfinite(float(growth_input)):
            ratio = None
            if (
                isinstance(fair_price, (int, float))
                and isinstance(current_price, (int, float))
                and float(current_price) > 0
            ):
                ratio = float(fair_price) / float(current_price)
            extreme = float(growth_input) > 1.0 or (ratio is not None and ratio > 3.0)
        regression = detail.get("regression")
        if not isinstance(regression, dict):
            regression = {}
        row.update(
            {
                "currentPrice": valuation.get("current_price"),
                "fairPrice": valuation.get("fair_price"),
                "valuePrice075": valuation.get("value_price_075"),
                "valuePrice066": valuation.get("value_price_066"),
                "currentPeg": valuation.get("current_peg"),
                "currentPe": valuation.get("current_pe"),
                "currentEps": valuation.get("current_eps"),
                "pegBand": "strict" if valuation.get("below_066") else "acceptable",
                "valuationMethod": valuation.get("method"),
                "valuationGrowthInput": valuation.get("eps_growth"),
                "valuationGrowthMethod": growth_method,
                "valuationGrowthMethodLabel": growth_method_label,
                "valuationEvidenceLevel": "proxy" if is_proxy else "formal",
                "valuationFormulaVersion": valuation.get("formula_version"),
                "extremeExtrapolation": extreme,
                "priceBasis": detail.get("priceBasis"),
                "zScore": detail.get("zScore"),
                "slope": detail.get("slope"),
                "regressionStart": regression.get("historyStart"),
                "regressionEnd": regression.get("historyEnd"),
                "regressionObservations": regression.get("observations"),
                "regressionExpectedObservations": regression.get("expectedObservations"),
            }
        )
        visible.append(row)
    return visible


def _summary(detail: dict[str, Any]) -> dict[str, Any]:
    hidden = {
        "priceSeries",
        "regression",
        "institutionalDaily",
        "revenueMonthly",
        "qualityChecks",
        "qualityProxyChecks",
        "historySnapshots",
        "notes",
        "detailLimitations",
        # Full raw public inputs stay on the per-stock evidence endpoint; the
        # ranking payload only needs compact health summaries.
        "healthInputs",
        "financialInputs",
    }
    return {key: value for key, value in detail.items() if key not in hidden}


def clean_detail_limitations(values: list[Any]) -> list[str]:
    """Drop stale baseline wording before publishing the current contract."""

    stale_markers = ("raw close proxy", "調整價", "四年", "4y", "4-year")
    return [
        str(value)
        for value in values
        if value and not any(marker in str(value) for marker in stale_markers)
    ]


def _reason_without_old_price(detail: dict[str, Any]) -> list[str]:
    return [
        str(reason)
        for reason in detail.get("entryReasons", [])
        if isinstance(reason, str)
        and not reason.startswith(("價格描述", "低位代理", "四年五線譜", "營收線索", "成長代理", "營收觀察"))
    ]


def _proxy_metrics_from_existing(detail: dict[str, Any]) -> dict[str, Any]:
    """Use an already-published proxy if an earlier run provided one."""

    value = detail.get("qualityProxyMetrics")
    return dict(value) if isinstance(value, dict) else {}


def _metrics_from_public_inputs(public_inputs: dict[str, Any] | None) -> dict[str, Any]:
    """Derive a small quality proxy from the official bulk snapshot."""
    if not isinstance(public_inputs, dict):
        return {}
    income = [row for row in public_inputs.get("incomeQuarterly", []) if isinstance(row, dict)]
    balance = [row for row in public_inputs.get("balanceQuarterly", []) if isinstance(row, dict)]
    income.sort(key=lambda row: (str(row.get("availableAt") or ""), str(row.get("year") or ""), str(row.get("quarter") or "")), reverse=True)
    balance.sort(key=lambda row: (str(row.get("availableAt") or ""), str(row.get("year") or ""), str(row.get("quarter") or "")), reverse=True)
    latest = income[0] if income else {}
    latest_balance = balance[0] if balance else {}
    revenue = latest.get("revenue")
    operating = latest.get("operatingProfit")
    net_income = latest.get("parentNetIncome")
    equity = latest_balance.get("equity")
    margin = operating / revenue if isinstance(operating, (int, float)) and isinstance(revenue, (int, float)) and revenue > 0 else None
    roe = net_income / equity if isinstance(net_income, (int, float)) and isinstance(equity, (int, float)) and equity > 0 else None
    return {
        "period": str(latest.get("availableAt") or latest.get("year") or "官方最新期")[:10],
        "latestNetIncome": net_income,
        "latestOperatingCashFlow": None,
        "latestOperatingMargin": margin,
        "latestRoe": roe,
        "netDebtToEbitda": None,
        "latestRevenue": revenue,
    }


def _revenue_growth_from_public_inputs(public_inputs: dict[str, Any] | None) -> float | None:
    if not isinstance(public_inputs, dict):
        return None
    rows = [row for row in public_inputs.get("monthlyRevenueOfficial", []) if isinstance(row, dict)]
    by_month = {str(row.get("month") or "")[:7]: row.get("revenue") for row in rows}
    months = sorted(month for month, value in by_month.items() if month and isinstance(value, (int, float)))
    if len(months) < 3:
        return None
    latest = months[-3:]
    prior = [f"{int(month[:4]) - 1:04d}-{month[5:7]}" for month in latest]
    if any(month not in by_month or not isinstance(by_month[month], (int, float)) for month in prior):
        return None
    current_total = sum(float(by_month[month]) for month in latest)
    prior_total = sum(float(by_month[month]) for month in prior)
    return (current_total - prior_total) / prior_total if prior_total else None


def enrich_detail(detail: dict[str, Any], *, end: date, offline: bool = False, public_inputs: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    code = str(detail.get("code") or "")
    market = str(detail.get("market") or "TWSE")
    # Offline recalculation must keep using the last successful public-input
    # payload.  Otherwise a refresh that only updates prices would turn all
    # revenue and quality proxies back into unknown.
    source_inputs = public_inputs if isinstance(public_inputs, dict) and public_inputs else (
        detail.get("healthInputs") if isinstance(detail.get("healthInputs"), dict) else None
    )
    errors: list[str] = []
    source_refs: list[str] = []
    raw_price = [dict(point) for point in detail.get("priceSeries", []) if isinstance(point, dict)]
    start = end - timedelta(days=round(365 * 3.5))

    adjusted_rows: list[dict[str, Any]] = []
    if not offline:
        adjusted_rows, price_source, error = fetch_adjusted_history(code, market, start, end)
        if price_source:
            source_refs.append(price_source)
        if error:
            errors.append(error)
    price = merge_adjusted_prices(raw_price, adjusted_rows)
    # The 3.5-year label is a fixed window, not a minimum: merged rows that
    # fall before the window start must be dropped so an older fetch's longer
    # history can never widen the published regression back to four years.
    price = clip_price_window(price, start=start, end=end)
    price, regression = apply_regression(price, prefer_adjusted=True)
    if regression["priceBasis"] == "adjusted":
        source_refs.append(YFINANCE_PRICE_SOURCE if any(row.get("source") == YFINANCE_PRICE_SOURCE for row in adjusted_rows) else YAHOO_CHART_SOURCE)
    elif raw_price:
        source_refs.append("FinMind:TaiwanStockPrice")

    metrics = _proxy_metrics_from_existing(detail)
    if not offline and os.environ.get("FAST_REFRESH") != "1":
        fresh_metrics, fundamentals_source, error = fetch_fundamental_proxies(code, market)
        if fresh_metrics:
            metrics = fresh_metrics
        if fundamentals_source:
            source_refs.append(fundamentals_source)
        if error:
            errors.append(error)
    if not metrics:
        metrics = _metrics_from_public_inputs(source_inputs)
    proxy_checks = quality_proxy_checks(metrics, source_ref=YFINANCE_FUNDAMENTAL_SOURCE)
    quality_proxy = proxy_status(proxy_checks)
    quality_proxy_reason = proxy_status_reason(proxy_checks)

    revenue_growth = detail.get("revenueGrowth3m") if detail.get("revenueGrowth3m") is not None else detail.get("revenueGrowthProxy")
    if revenue_growth is None:
        revenue_growth = _revenue_growth_from_public_inputs(source_inputs)
    if revenue_growth is None and isinstance(source_inputs, dict):
        latest_rows = [row for row in source_inputs.get("monthlyRevenueOfficial", []) if isinstance(row, dict)]
        latest_row = latest_rows[-1] if latest_rows else {}
        current = latest_row.get("revenue")
        prior = latest_row.get("priorYearRevenue")
        if isinstance(current, (int, float)) and isinstance(prior, (int, float)) and prior:
            revenue_growth = (current - prior) / prior
    try:
        revenue_growth = float(revenue_growth) if revenue_growth is not None else None
    except (TypeError, ValueError):
        revenue_growth = None
    growth_proxy = growth_proxy_status(revenue_growth, minimum=GROWTH_MIN)
    if revenue_growth is None:
        growth_proxy_reason = "未知：三月合計營收年增未取得"
    elif growth_proxy == "pass":
        growth_proxy_reason = f"通過：三月合計營收年增 {revenue_growth * 100:+.1f}% ≥ 15%"
    else:
        growth_proxy_reason = f"未通過：三月合計營收年增 {revenue_growth * 100:+.1f}% < 15%"
    operating_growth = detail.get("ttmOperatingProfitGrowth")
    try:
        operating_growth = float(operating_growth) if operating_growth is not None else None
    except (TypeError, ValueError):
        operating_growth = None
    formal_growth = formal_growth_status(revenue_growth, operating_growth, minimum=GROWTH_MIN)
    if detail.get("growthStatus") in {"pass", "fail"} and operating_growth is None:
        # Preserve a previously calculated formal status, but do not upgrade
        # unknown to pass just because revenue exists.
        formal_growth = str(detail["growthStatus"])

    regression_z = regression.get("z")
    regression_slope = regression.get("slope")
    trust_positive = (detail.get("institutionNetShares10") or 0) > 0 and detail.get("participation10") is not None
    low_position_proxy = (
        isinstance(regression_z, (int, float))
        and math.isfinite(float(regression_z))
        and isinstance(regression_slope, (int, float))
        and math.isfinite(float(regression_slope))
        and float(regression_z) <= 0
        and float(regression_slope) > 0
    )
    formal_quality = detail.get("qualityStatus") == "pass"
    # Historical eight-week evidence is not reconstructed from today's curve.
    historical_low_evidence = bool(detail.get("historySnapshots")) and any(
        isinstance(item, dict) and isinstance(item.get("z"), (int, float)) and float(item["z"]) <= -1
        for item in detail.get("historySnapshots", [])
    )
    formal_entry = bool(
        regression.get("signalEligible")
        and formal_quality
        and formal_growth == "pass"
        and historical_low_evidence
        and regression_z is not None
        and float(regression_z) <= 0
    )
    has_price = bool(price)
    state = derive_signal_state(
        formal_entry=formal_entry,
        z=float(regression_z) if isinstance(regression_z, (int, float)) else None,
        slope=float(regression_slope) if isinstance(regression_slope, (int, float)) else None,
        has_route_evidence=trust_positive or growth_proxy == "pass",
        has_price=has_price,
    )

    reasons = _reason_without_old_price(detail)
    if trust_positive and not any(reason.startswith("投信") for reason in reasons):
        net = detail.get("institutionNetShares10")
        participation = detail.get("participation10")
        if isinstance(net, (int, float)) and isinstance(participation, (int, float)):
            reasons.append(f"投信關注：十日淨買超 {int(net):,} 股，該股成交占比 {participation * 100:.2f}%")
    if revenue_growth is not None:
        prefix = "成長代理" if growth_proxy == "pass" else "營收觀察"
        reasons.append(
            f"{prefix}：三月合計營收年增 {revenue_growth * 100:+.1f}%；"
            + ("正式營業利益成長仍待核對" if formal_growth == "unknown" else "正式成長條件已計算")
        )
    if regression_z is not None:
        basis_label = "Adj Close" if regression.get("priceBasis") == "adjusted" else "未調整收盤"
        if low_position_proxy:
            reasons.append(
                f"低位代理：{basis_label} 3.5 年 Z {float(regression_z):+.2f}、斜率 {float(regression_slope):+.4f}；"
                + ("正式八週與品質條件仍待核對" if not formal_entry else "正式條件已通過")
            )
        else:
            reasons.append(f"價格描述：{basis_label} 3.5 年 Z {float(regression_z):+.2f}；未形成低位條件")
    if not reasons:
        reasons.append("尚無足夠條件形成研究理由")

    risks = [str(value) for value in detail.get("risks", []) if value]
    raw_proxy_risk_markers = ("未驗證核准調整價", "未調整收盤代理", "調整尚未驗證")
    if regression.get("priceBasis") == "raw_proxy":
        risks = [value for value in risks if not any(marker in value for marker in raw_proxy_risk_markers)]
        risks.insert(0, "目前使用未調整收盤代理；公司行動／股利調整尚未驗證")
    elif regression.get("priceBasis") == "adjusted":
        # A later successful adjusted-price fetch must clear an older
        # raw-proxy warning carried forward from the baseline release.
        risks = [value for value in risks if not any(marker in value for marker in raw_proxy_risk_markers)]
    if quality_proxy == "unknown" and not any("代理" in value and "財務" in value for value in risks):
        risks.append("最新期財務品質代理尚未完整；正式三年門檻仍 unknown")
    if errors:
        risks.append("部分免費來源本次未回傳；沿用已發布觀察值")

    raw_values = [point.get("close") for point in price if point.get("close") is not None]
    latest_raw = raw_values[-1] if raw_values else None
    previous_raw = raw_values[-2] if len(raw_values) >= 2 else None
    change_pct = None if latest_raw is None or previous_raw in (None, 0) else (latest_raw - previous_raw) / previous_raw
    adjusted_values = [point.get("adjustedClose") for point in price if point.get("adjustedClose") is not None]
    adjusted_latest = adjusted_values[-1] if adjusted_values else None
    adjusted_previous = adjusted_values[-2] if len(adjusted_values) >= 2 else None
    adjusted_change = None if adjusted_latest is None or adjusted_previous in (None, 0) else (adjusted_latest - adjusted_previous) / adjusted_previous
    old_formal_status = str(detail.get("qualityStatus") or "unknown")
    data_status = "pass" if raw_values or adjusted_values else "fail"
    detail.update(
        {
            "asOf": detail.get("asOf") or (price[-1].get("date") if price else None),
            # Some public rows expose only adjusted close.  It is still a
            # usable latest quote, so keep the price column populated and
            # label the research curve separately below.
            "lastPrice": latest_raw if latest_raw is not None else (adjusted_latest if adjusted_latest is not None else _current_price(detail)),
            "changePct": change_pct if change_pct is not None else (adjusted_change if adjusted_change is not None else detail.get("changePct")),
            "adjustedLastPrice": adjusted_latest,
            "adjustedChangePct": adjusted_change,
            "zScore": regression.get("z"),
            "slope": regression.get("slope"),
            "fiveLineStatus": "pass" if regression.get("signalEligible") else "unknown",
            "priceBasis": regression.get("priceBasis", "unknown"),
            "adjustedPriceStatus": "pass" if regression.get("priceBasis") == "adjusted" else "unknown" if raw_values else "fail",
            "qualityStatus": old_formal_status,
            "qualityProxyStatus": quality_proxy,
            "qualityProxyPassCount": proxy_pass_count(proxy_checks),
            "qualityProxyReason": quality_proxy_reason,
            "growthStatus": formal_growth,
            "growthProxyStatus": growth_proxy,
            "growthProxyReason": growth_proxy_reason,
            "revenueGrowthProxy": revenue_growth if detail.get("revenueGrowth3m") is None else detail.get("revenueGrowthProxy"),
            "dataStatus": data_status,
            "signalState": state,
            "entryReasons": reasons,
            "risks": list(dict.fromkeys(risks)),
            "priceSeries": price,
            "regression": {
                **regression,
                "sourceRefs": merge_refs(
                    [YFINANCE_PRICE_SOURCE] if regression.get("priceBasis") == "adjusted" else ["FinMind:TaiwanStockPrice"],
                    [YAHOO_CHART_SOURCE] if regression.get("priceBasis") == "adjusted" and adjusted_rows and adjusted_rows[0].get("source") == YAHOO_CHART_SOURCE else None,
                ),
            },
            "qualityProxyChecks": proxy_checks,
            "qualityProxyMetrics": metrics,
            "sourceRefs": merge_refs(detail.get("sourceRefs"), source_refs),
        }
    )
    if public_inputs:
        # A source outage must not erase the last successful structured
        # snapshot. Merge non-empty endpoint results and keep prior rows when
        # this run only returns an error or an empty list.
        previous_inputs = detail.get("healthInputs") if isinstance(detail.get("healthInputs"), dict) else {}
        merged_inputs = dict(previous_inputs)
        for key, value in public_inputs.items():
            if key in {"source", "fetchedAt", "errors"} or value not in (None, [], {}):
                merged_inputs[key] = value
        detail["healthInputs"] = merged_inputs
        detail["healthInputSummary"] = {
            "source": merged_inputs.get("source", TWSE_SOURCE),
            "valuationDate": (merged_inputs.get("valuationCurrent") or {}).get("date"),
            "incomePeriods": len(merged_inputs.get("incomeQuarterly") or []),
            "balancePeriods": len(merged_inputs.get("balanceQuarterly") or []),
            "dividendRows": len(merged_inputs.get("dividends") or []),
            "officialRevenueRows": len(merged_inputs.get("monthlyRevenueOfficial") or []),
        }
    elif isinstance(detail.get("healthInputs"), dict) and not detail.get("healthInputSummary"):
        existing = detail["healthInputs"]
        detail["healthInputSummary"] = {
            "source": existing.get("source", TWSE_SOURCE),
            "valuationDate": (existing.get("valuationCurrent") or {}).get("date"),
            "incomePeriods": len(existing.get("incomeQuarterly") or []),
            "balancePeriods": len(existing.get("balanceQuarterly") or []),
            "dividendRows": len(existing.get("dividends") or []),
            "officialRevenueRows": len(existing.get("monthlyRevenueOfficial") or []),
        }
    if public_inputs:
        detail["sourceRefs"] = merge_refs(detail.get("sourceRefs"), [TWSE_SOURCE])
        # Keep the longer FinMind series for charting, but let the official
        # monthly row fill a newly published month when it is not present.
        official_months = public_inputs.get("monthlyRevenueOfficial") or []
        known_months = {str(row.get("month"))[:7] for row in detail.get("revenueMonthly", []) if isinstance(row, dict)}
        for row in official_months:
            month = str(row.get("month") or "")[:7]
            revenue = row.get("revenue")
            if month and revenue is not None and month not in known_months:
                detail.setdefault("revenueMonthly", []).append({"month": month, "revenue": revenue, "availableAt": row.get("availableAt"), "status": "pass", "source": TWSE_SOURCE})
        detail["revenueMonthly"] = sorted(detail.get("revenueMonthly", []), key=lambda row: str(row.get("month") or ""))
    limitations = clean_detail_limitations(detail.get("detailLimitations", []))
    if regression.get("priceBasis") == "adjusted":
        limitations.insert(0, "3.5 年研究曲線使用 yfinance Adj Close；原始 FinMind close 仍保留作報價參考。")
        limitations.insert(1, "yfinance 非交易所官方資料；此頁供個人研究，來源與處理版本隨快照保存。")
    elif raw_values:
        limitations.insert(0, "3.5 年研究曲線目前使用 FinMind 未調整 close proxy；公司行動／股利調整待驗證。")
    limitations.append("品質代理只看最新可得期，不能替代三年 point-in-time 財報條件。")
    detail["detailLimitations"] = list(dict.fromkeys(limitations))
    health_categories = evaluate_snapshot_health(
        detail,
        refs=merge_refs(detail.get("sourceRefs"), ["FinMind:TaiwanStockMonthRevenue", "TWSE OpenAPI", "TPEx OpenAPI"]),
    )
    detail["healthCategories"] = health_categories
    detail["healthScore"] = health_totals(health_categories)
    detail["notes"] = list(dict.fromkeys([str(value) for value in detail.get("notes", []) if value] + [
        "正式進場觀察仍要求品質、公告可得時間、八週歷史低位與公司行動全部通過。",
    ]))
    return detail, errors


def rank_rows(rows: list[dict[str, Any]], *, reverse: bool) -> list[dict[str, Any]]:
    valid = [row for row in rows if row.get("value") is not None]
    valid.sort(key=lambda row: (-float(row["value"]) if reverse else float(row["value"]), str(row.get("code"))))
    for index, row in enumerate(valid[:100], start=1):
        row["rank"] = index
    return valid[:100]


def rank_low_base_rows(rows: list[dict[str, Any]], institutional_rank_by_code: dict[str, int]) -> list[dict[str, Any]]:
    """Rank eligible low-base rows by institutional context, without gating.

    A missing institutional value is sorted after known values.  The route
    remains eligible because this rank is presentation context only.
    """

    valid = [row for row in rows if row.get("value") is not None]
    valid.sort(
        key=lambda row: (
            institutional_rank_by_code.get(str(row.get("code")), 10**9),
            float(row["value"]),
            str(row.get("code")),
        )
    )
    for index, row in enumerate(valid[:100], start=1):
        row["rank"] = index
    return valid[:100]


def low_base_gap(results: dict[str, dict[str, Any]], *, label: str, tracked_count: int) -> dict[str, Any]:
    """Summarize why a low-base route has no qualified rows."""

    candidate_count = sum(result.get("status") == "pass" for result in results.values())
    blockers: list[str] = []
    for result in results.values():
        for gate in result.get("gates", []):
            if gate.get("status") not in {"pass", "not_applicable"}:
                status_label = {"pass": "通過", "fail": "未通過", "unknown": "未知", "not_applicable": "不適用"}.get(str(gate.get("status")), str(gate.get("status")))
                text = f"{gate.get('label', '條件')}：{status_label}"
                if text not in blockers:
                    blockers.append(text)
    if candidate_count:
        explanation = f"目前追蹤 {tracked_count} 檔，{label}已有 {candidate_count} 檔符合。"
    else:
        detail = "、".join(blockers[:8]) if blockers else "尚無可用 gate 證據"
        explanation = f"目前追蹤 {tracked_count} 檔，{label}暫無符合；缺口：{detail}。"
    return {
        "candidateCount": candidate_count,
        "trackedCount": tracked_count,
        "explanation": explanation,
        "missing": blockers,
    }


def build_release(data_dir: Path, codes: list[str], *, as_of: str | None, offline: bool) -> dict[str, Any]:
    latest_path = data_dir / "latest.json"
    if not latest_path.exists():
        raise FileNotFoundError(f"missing baseline release: {latest_path}")
    baseline = load_json(latest_path)
    details = baseline_details(data_dir, baseline)
    allowed = set(codes)
    if allowed:
        details = [detail for detail in details if str(detail.get("code")) in allowed]
    if not details:
        raise ValueError("no tracked stock details found in baseline release")
    fallback_end = max(
        (parse_date(str(detail.get("asOf") or ""), date.today()) for detail in details),
        default=date.today(),
    )
    end = parse_date(as_of, fallback_end)
    errors_by_code: dict[str, list[str]] = {}
    enriched: list[dict[str, Any]] = []
    used_sources: list[str] = []
    public_inputs_by_code: dict[str, dict[str, Any]] = {}
    public_errors: list[str] = []
    if not offline:
        public_inputs_by_code = build_health_inputs([str(detail.get("code")) for detail in details])
        public_errors = [f"TWSE {code}: {key}" for code, value in public_inputs_by_code.items() for key in (value.get("errors") or {})]
    for detail in details:
        next_detail, errors = enrich_detail(detail, end=end, offline=offline, public_inputs=public_inputs_by_code.get(str(detail.get("code"))))
        errors.extend(public_errors)
        enriched.append(next_detail)
        errors_by_code[str(next_detail.get("code"))] = errors
        used_sources = merge_refs(used_sources, next_detail.get("sourceRefs"))

    for detail in enriched:
        valuation = _valuation_from_detail(detail)
        if valuation is None:
            detail.pop("valuation", None)
        else:
            detail["valuation"] = valuation

    # A is the source-published research universe.  Preserve its rank as an
    # input label for every strategy; do not re-rank the already selected 100
    # symbols and call that result the universe.
    universe_rows: list[dict[str, Any]] = []
    universe_source = ""
    universe_label = "投信十日買超前100"
    previous_universe_rows: list[dict[str, Any]] = []
    try:
        config = load_json(data_dir.parent.parent / "config" / "tracked_symbols.json")
        raw_universe = config.get("universe")
        universe = raw_universe if isinstance(raw_universe, dict) else {}
        universe_rows = [row for row in universe.get("rows", []) if isinstance(row, dict)]
        universe_source = str(universe.get("sourceUrl") or "")
        universe_label = str(universe.get("label") or universe_label)
        previous_universe_rows = [row for row in universe.get("previousRows", []) if isinstance(row, dict)]
    except (OSError, ValueError, json.JSONDecodeError):
        universe_rows = []
    detail_by_code = {str(detail.get("code")): detail for detail in enriched}
    source_rank_rows: list[dict[str, Any]] = []
    for row in universe_rows:
        code = str(row.get("code") or "")
        detail = detail_by_code.get(code)
        if not detail:
            continue
        rank_value = row.get("rank")
        try:
            source_rank = int(rank_value)
        except (TypeError, ValueError):
            continue
        detail["researchUniverseId"] = "A"
        detail["researchUniverseLabel"] = universe_label
        detail["researchUniverseRank"] = source_rank
        detail["researchUniverseSource"] = universe_source or "https://stock.wearn.com/b50.asp"
        detail["sourceRefs"] = merge_refs(detail.get("sourceRefs"), [detail["researchUniverseSource"]])
        net_value = row.get("netShares")
        if not isinstance(net_value, (int, float)):
            net_text = str(row.get("net") or "").replace(",", "")
            try:
                net_value = float(net_text)
            except ValueError:
                net_value = None
        detail["sourceUniverseNetShares"] = float(net_value) if isinstance(net_value, (int, float)) else None
        source_rank_rows.append({
            "rank": source_rank,
            "code": code,
            "name": str(row.get("name") or detail.get("name") or code),
            "sector": str(detail.get("sector") or ""),
            "value": detail.get("sourceUniverseNetShares"),
            "valueLabel": "股",
            "status": "pass",
            "sourceRank": source_rank,
            "previousRank": row.get("previousRank"),
            "entryStatus": row.get("entryStatus", "not_applicable"),
            "reason": f"{universe_label}，第 {source_rank} 名；此名次是完整來源排行，不是子集合重算。",
            "source": detail["researchUniverseSource"],
        })

    trust_rows: list[dict[str, Any]] = []
    growth_rows: list[dict[str, Any]] = []
    low_rows: list[dict[str, Any]] = []
    strict_low_base_growth_rows: list[dict[str, Any]] = []
    strict_low_base_quality_rows: list[dict[str, Any]] = []
    low_base_growth_watch_rows: list[dict[str, Any]] = []
    low_base_quality_watch_rows: list[dict[str, Any]] = []
    low_count = 0
    formal_entries = 0
    proxy_candidates = 0
    candidate_codes: set[str] = set()
    low_base_growth_results: dict[str, dict[str, Any]] = {}
    low_base_quality_results: dict[str, dict[str, Any]] = {}
    low_base_growth_watch_results: dict[str, dict[str, Any]] = {}
    low_base_quality_watch_results: dict[str, dict[str, Any]] = {}

    # Rank every available ten-session net-share value within this tracked
    # range.  The rank is useful context for low-base rows, but is never a
    # qualification gate for either low-base path.
    institutional_rank_by_code: dict[str, int] = {}
    institutional_values = sorted(
        (
            (str(detail.get("code")), float(detail.get("institutionNetShares10")))
            for detail in enriched
            if isinstance(detail.get("institutionNetShares10"), (int, float))
            and math.isfinite(float(detail.get("institutionNetShares10")))
        ),
        key=lambda item: (-item[1], item[0]),
    )
    for rank, (code, _value) in enumerate(institutional_values, start=1):
        institutional_rank_by_code[code] = rank
    for detail in enriched:
        code = str(detail.get("code"))
        name = str(detail.get("name") or code)
        sector = str(detail.get("sector") or "")
        participation = detail.get("participation10")
        net = detail.get("institutionNetShares10")
        if isinstance(participation, (int, float)) and math.isfinite(float(participation)) and isinstance(net, (int, float)) and float(net) > 0:
            candidate_codes.add(code)
            trust_rows.append(
                {
                    "rank": 0,
                    "code": code,
                    "name": name,
                    "sector": sector,
                    "value": float(participation) * 100,
                    "valueLabel": "%",
                    "status": "pass" if detail.get("liquidityStatus") == "pass" else "unknown",
                    "reason": next((reason for reason in detail.get("entryReasons", []) if str(reason).startswith("投信")), "投信十日資料已取得"),
                }
            )
        growth = detail.get("revenueGrowth3m")
        if growth is None:
            growth = detail.get("revenueGrowthProxy")
        if isinstance(growth, (int, float)) and math.isfinite(float(growth)):
            growth_status = str(detail.get("growthProxyStatus") or growth_proxy_status(float(growth)))
            if growth_status == "pass":
                candidate_codes.add(code)
            growth_rows.append(
                {
                    "rank": 0,
                    "code": code,
                    "name": name,
                    "sector": sector,
                    "value": float(growth) * 100,
                    "valueLabel": "%",
                    "status": growth_status,
                    "reason": f"三月合計營收年增 {float(growth) * 100:+.1f}%；這是營收代理，正式營業利益成長為 {detail.get('growthStatus', 'unknown')}",
                }
            )
        z = detail.get("zScore")
        slope = detail.get("slope")
        if isinstance(z, (int, float)) and math.isfinite(float(z)):
            low = float(z) <= -1 and isinstance(slope, (int, float)) and float(slope) > 0
            proxy_low = float(z) <= 0 and isinstance(slope, (int, float)) and float(slope) > 0
            if proxy_low:
                low_count += 1
                candidate_codes.add(code)
            if detail.get("signalState") == "進場觀察":
                formal_entries += 1
            elif detail.get("signalState") in {"低位觀察", "值得研究"}:
                proxy_candidates += 1
            if proxy_low:
                low_rows.append(
                    {
                        "rank": 0,
                        "code": code,
                        "name": name,
                        "sector": sector,
                        "value": float(z),
                        "valueLabel": "",
                        "status": "pass" if low and detail.get("regression", {}).get("signalEligible") else "unknown",
                        "reason": f"Z {float(z):+.2f} ≤ 0；低位代理，完整歷史條件仍待驗證",
                    }
                )

        regression = detail.get("regression") if isinstance(detail.get("regression"), dict) else {}
        price_eligible = (
            None
            if not regression or regression.get("priceBasis") in (None, "unknown")
            else bool(regression.get("signalEligible"))
        )
        low_base_growth = low_base_growth_gates(
            z=z,
            slope=slope,
            price_eligible=price_eligible,
            growth=detail.get("revenueGrowth3m") if detail.get("revenueGrowth3m") is not None else detail.get("revenueGrowthProxy"),
            operating_profit_growth=detail.get("ttmOperatingProfitGrowth"),
        )
        low_base_quality = low_base_quality_gates(
            z=z,
            slope=slope,
            price_eligible=price_eligible,
            quality_checks=detail.get("qualityProxyChecks", []),
        )
        low_base_growth_watch = low_base_growth_gates(
            z=z,
            slope=slope,
            price_eligible=price_eligible,
            growth=detail.get("revenueGrowth3m") if detail.get("revenueGrowth3m") is not None else detail.get("revenueGrowthProxy"),
            operating_profit_growth=detail.get("ttmOperatingProfitGrowth"),
            z_maximum=LOW_POSITION_Z_MAX,
        )
        low_base_quality_watch = low_base_quality_gates(
            z=z,
            slope=slope,
            price_eligible=price_eligible,
            quality_checks=detail.get("qualityProxyChecks", []),
            z_maximum=LOW_POSITION_Z_MAX,
            minimum_quality_passes=3,
        )
        low_base_growth_results[code] = low_base_growth
        low_base_quality_results[code] = low_base_quality
        low_base_growth_watch_results[code] = low_base_growth_watch
        low_base_quality_watch_results[code] = low_base_quality_watch
        # Keep the route evidence in the stock detail so the UI can show the
        # exact backend decision without recalculating it in React.
        detail.update(
            {
                "lowBaseGrowthStatus": low_base_growth["status"],
                "lowBaseGrowthReason": low_base_growth["reason"],
                "lowBaseGrowthGates": low_base_growth["gates"],
                "lowBaseQualityStatus": low_base_quality["status"],
                "lowBaseQualityReason": low_base_quality["reason"],
                "lowBaseQualityGates": low_base_quality["gates"],
                "lowBaseStatus": "pass" if low_base_growth["status"] == "pass" or low_base_quality["status"] == "pass" else "unknown" if low_base_growth["status"] == "unknown" or low_base_quality["status"] == "unknown" else "fail",
                "lowBaseReason": f"成長路徑：{low_base_growth['status']}；品質路徑：{low_base_quality['status']}",
                "lowBaseGates": low_base_growth["gates"] + low_base_quality["gates"],
                "lowBaseGrowthWatchStatus": low_base_growth_watch["status"],
                "lowBaseQualityWatchStatus": low_base_quality_watch["status"],
            }
        )
        trust_rank = institutional_rank_by_code.get(code)
        sort_context = f"投信十日淨買超排序第 {trust_rank} 名（只作排序）" if trust_rank is not None else "投信十日淨買超排序未知（只作排序）"
        for route, result, rows in (
            ("lowBaseGrowth", low_base_growth, strict_low_base_growth_rows),
            ("lowBaseQuality", low_base_quality, strict_low_base_quality_rows),
        ):
            if result["status"] == "pass":
                candidate_codes.add(code)
                rows.append(
                    {
                        "rank": 0,
                        "code": code,
                        "name": name,
                        "sector": sector,
                        "value": float(z) if isinstance(z, (int, float)) else None,
                        "valueLabel": "",
                        "status": "pass",
                        "proxy": True,
                        "evidenceLevel": "proxy",
                        "route": route,
                        "gates": result["gates"],
                        "reason": f"{sort_context}；{result['reason']}",
                    }
                )

        # The published low-base tabs use the low-position ranking (Z ≤ 0,
        # positive slope) as a practical seed universe.  Strict Z ≤ -1
        # results remain available in the summary as an audit count.  This
        # keeps the dashboard useful without converting unavailable values to
        # passes or pretending the relaxed proxy is the formal rule.
        watch_common_growth = all(gate.get("status") == "pass" for gate in low_base_growth_watch["gates"][:3])
        if watch_common_growth and low_base_growth_watch["status"] == "pass":
            low_base_growth_watch_rows.append(
                {
                    "rank": 0, "code": code, "name": name, "sector": sector,
                    "value": float(z) if isinstance(z, (int, float)) else None,
                    "valueLabel": "", "status": "pass", "proxy": True,
                    "evidenceLevel": "proxy", "route": "lowBaseGrowth",
                    "gates": low_base_growth_watch["gates"],
                    "reason": f"{sort_context}；低位代理（Z ≤ 0）取代嚴格 Z ≤ -1 作為研究入口；{low_base_growth_watch['reason']}",
                }
            )
        watch_common_quality = all(gate.get("status") == "pass" for gate in low_base_quality_watch["gates"][:3])
        if watch_common_quality and low_base_quality_watch.get("qualityPasses", 0) >= 3:
            low_base_quality_watch_rows.append(
                {
                    "rank": 0, "code": code, "name": name, "sector": sector,
                    "value": float(z) if isinstance(z, (int, float)) else None,
                    "valueLabel": "", "status": "pass" if low_base_quality_watch["status"] == "pass" else "unknown",
                    "proxy": True, "evidenceLevel": "proxy", "route": "lowBaseQuality",
                    "gates": low_base_quality_watch["gates"],
                    "reason": f"{sort_context}；低位代理（Z ≤ 0）取代嚴格 Z ≤ -1 作為研究入口；{low_base_quality_watch['reason']}",
                }
            )

    if not previous_universe_rows:
        previous_universe_rows = [
            {
                "rank": stock.get("researchUniverseRank"),
                "code": stock.get("code"),
            }
            for stock in baseline.get("stocks", [])
            if isinstance(stock, dict) and stock.get("researchUniverseRank") is not None
        ]
    trust_signal_rank = annotate_top_n_entries(source_rank_rows, previous_universe_rows, limit=10) if source_rank_rows else []
    for row in trust_signal_rank:
        entry_status = str(row.get("entryStatus") or "unknown")
        if entry_status == "new":
            row["reason"] = f"{universe_label} Top10 新進榜，第 {row['rank']} 名；前期名次 {row.get('previousRank') or '未入榜'}。"
        elif entry_status == "retained":
            row["reason"] = f"{universe_label} Top10，第 {row['rank']} 名；前期第 {row.get('previousRank')} 名。"
        else:
            row["reason"] = f"{universe_label} Top10，第 {row['rank']} 名；前期排行資料不足，暫不判定新進榜。"
    trust_signal_count = len(trust_signal_rank)
    trust_new_entry_count = sum(1 for row in trust_signal_rank if row.get("entryStatus") == "new")
    trust_rank = trust_signal_rank
    growth_rank = rank_rows(growth_rows, reverse=True)
    low_rank = rank_rows(low_rows, reverse=False)
    strict_low_base_growth_rank = rank_low_base_rows(strict_low_base_growth_rows, institutional_rank_by_code)
    strict_low_base_quality_rank = rank_low_base_rows(strict_low_base_quality_rows, institutional_rank_by_code)
    low_base_growth_watch_rank = rank_low_base_rows(low_base_growth_watch_rows, institutional_rank_by_code)
    low_base_quality_watch_rank = rank_low_base_rows(low_base_quality_watch_rows, institutional_rank_by_code)
    low_base_growth_rank = low_base_growth_watch_rank or strict_low_base_growth_rank
    low_base_quality_rank = low_base_quality_watch_rank or strict_low_base_quality_rank
    low_base_by_code: dict[str, dict[str, Any]] = {}
    for row in [*low_base_growth_rank, *low_base_quality_rank]:
        code = str(row["code"])
        current = low_base_by_code.get(code)
        if current is None:
            low_base_by_code[code] = {**row, "route": "lowBase"}
            continue
        known_gate_keys = {str(gate.get("key")) for gate in current.get("gates", [])}
        current["gates"] = [
            *current.get("gates", []),
            *[gate for gate in row.get("gates", []) if str(gate.get("key")) not in known_gate_keys],
        ]
        current["reason"] = f"{current.get('reason', '')}；另一路徑亦通過"
    low_base_rank = rank_low_base_rows(list(low_base_by_code.values()), institutional_rank_by_code)
    trust_rank = _attach_valuation(trust_rank, detail_by_code, require_peg_below_075=False)
    growth_rank = _attach_valuation(growth_rank, detail_by_code)
    low_rank = _attach_valuation(low_rank, detail_by_code)
    strict_low_base_growth_rank = _attach_valuation(strict_low_base_growth_rank, detail_by_code)
    strict_low_base_quality_rank = _attach_valuation(strict_low_base_quality_rank, detail_by_code)
    low_base_growth_rank = _attach_valuation(low_base_growth_rank, detail_by_code)
    low_base_quality_rank = _attach_valuation(low_base_quality_rank, detail_by_code)
    low_base_rank = _attach_valuation(low_base_rank, detail_by_code)
    if formal_entries == 0:
        formal_entries = sum(1 for detail in enriched if detail.get("signalState") == "進場觀察")
    if proxy_candidates == 0:
        proxy_candidates = sum(1 for detail in enriched if detail.get("signalState") in {"低位觀察", "值得研究"})

    tracked_count = len(enriched)
    tracked_complete = sum(1 for detail in enriched if detail.get("dataStatus") == "pass")
    tracked_pct = tracked_complete / tracked_count * 100 if tracked_count else None
    low_base_growth_gap = low_base_gap(low_base_growth_results, label="嚴格低基期成長路徑（Z ≤ -1）", tracked_count=tracked_count)
    low_base_quality_gap = low_base_gap(low_base_quality_results, label="嚴格低基期品質路徑（Z ≤ -1）", tracked_count=tracked_count)
    low_base_gap_summary = {
        "candidateCount": len(low_base_rank),
        "trackedCount": tracked_count,
        "explanation": (
            f"目前追蹤 {tracked_count} 檔，低位代理低基期策略共 {len(low_base_rank)} 檔；嚴格 Z ≤ -1 成長 {len(strict_low_base_growth_rank)} 檔、品質 {len(strict_low_base_quality_rank)} 檔。"
            if low_base_rank
            else f"目前追蹤 {tracked_count} 檔，低基期策略暫無符合；成長路徑：{low_base_growth_gap['explanation']} 品質路徑：{low_base_quality_gap['explanation']}"
        ),
        "missing": list(dict.fromkeys(low_base_growth_gap["missing"] + low_base_quality_gap["missing"])),
    }
    universe = len(universe_rows) or int((baseline.get("coverage") or {}).get("universeCount") or tracked_count)
    universe_pct = tracked_count / universe * 100 if universe else None
    # Funnel stage counts are published by the producer from the full enriched
    # universe (never reconstructed from the already-filtered rankings).
    valuation_dicts: list[dict[str, Any]] = []
    for detail in enriched:
        value = detail.get("valuation")
        if isinstance(value, dict):
            valuation_dicts.append(value)
    funnel = compute_funnel(
        universe=universe,
        price_complete=sum(1 for detail in enriched if detail.get("dataStatus") == "pass"),
        instrument_excluded=sum(1 for detail in enriched if not is_common_stock_code(str(detail.get("code")))),
        valuations=valuation_dicts,
        strategy_counts={"trust": len(trust_rank), "growth": len(growth_rank), "lowPosition": len(low_rank)},
    )
    market_dates = [str(detail.get("asOf")) for detail in enriched if detail.get("asOf")]
    market_date = max(market_dates) if market_dates else baseline.get("marketDate")
    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    canonical = json.dumps(
        {"baselineRunId": baseline.get("runId"), "codes": codes, "details": enriched, "marketDate": market_date},
        ensure_ascii=False,
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(canonical).hexdigest()[:10]
    run_id = f"enriched-{datetime.now(TAIPEI).strftime('%Y%m%d-%H%M%S')}-{digest}"
    all_errors = sum(len(values) for values in errors_by_code.values())
    adjusted_count = sum(1 for detail in enriched if detail.get("priceBasis") == "adjusted")
    if offline:
        freshness = "degraded"
        if adjusted_count:
            status_message = f"離線重算 {tracked_count} 檔；沿用已發布的 {adjusted_count} 檔調整價與財務代理，未呼叫外部來源。"
        else:
            status_message = f"離線重算 {tracked_count} 檔；沿用可得官方觀察值，未呼叫外部來源。"
    elif all_errors and adjusted_count == 0:
        freshness = "degraded"
        status_message = "已保留官方觀察值；yfinance 調整價本次不可用，價格仍明示為未調整代理。"
    elif adjusted_count < tracked_count or all_errors:
        freshness = "degraded"
        status_message = f"已更新 {adjusted_count}/{tracked_count} 檔調整價；其餘沿用可得 raw close，代理與正式條件分開標示。3.5 年回歸資料需看 evidence level。"
    else:
        freshness = "current"
        status_message = f"已更新 {tracked_count} 檔追蹤研究；3.5 年曲線使用 yfinance Adj Close，財務品質仍依可得期間標示。"
    base_coverage = baseline.get("coverage") if isinstance(baseline.get("coverage"), dict) else {}
    coverage = {
        **base_coverage,
        "universeCount": universe,
        "databaseCount": tracked_count,
        "candidateCount": len(candidate_codes),
        "pendingCount": max(0, universe - tracked_count),
        "financialCompleteCount": sum(1 for detail in enriched if detail.get("qualityStatus") == "pass"),
        "priceCompleteCount": sum(1 for detail in enriched if detail.get("dataStatus") == "pass"),
        "completenessPct": tracked_pct,
        "trackedCount": tracked_count,
        "trackedCompleteCount": tracked_complete,
        "trackedCompletenessPct": tracked_pct,
        "universeCoveragePct": universe_pct,
        "scopeLabel": f"A 母體：{universe_label}（{tracked_count} 檔）",
        "universeId": "A",
        "universeLabel": universe_label,
        "universeSource": universe_source or "https://stock.wearn.com/b50.asp",
        "queueStatus": f"A 母體 {tracked_count}/{universe} 檔；所有策略共用此初始篩選",
    }
    source_refs = merge_refs(baseline.get("sourceRefs"), used_sources)
    rankings_payload = {
        "trust": trust_rank,
        "growth": growth_rank,
        "lowPosition": low_rank,
        "lowBase": low_base_rank,
        "lowBaseGrowth": low_base_growth_rank,
        "lowBaseQuality": low_base_quality_rank,
    }
    rankings_hash = hashlib.sha256(
        json.dumps(rankings_payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    release = {
        **baseline,
        "schemaVersion": "1.1",
        "formulaVersion": "lohas-linear-3.5y-research-v1",
        "runId": run_id,
        "inputCodes": list(codes),
        "marketDate": market_date,
        "generatedAt": generated,
        "freshness": freshness,
        "statusMessage": status_message,
        "sourceRefs": source_refs,
        "coverage": coverage,
        "summary": {
            **(baseline.get("summary") or {}),
            "watchCount": int((baseline.get("summary") or {}).get("watchCount") or 0),
            "lowPositionCount": low_count,
            "candidateRouteCounts": {
                "trust": len(trust_rank),
                "growth": sum(1 for row in growth_rank if row.get("status") == "pass"),
                "lowPosition": low_count,
                "lowBase": len(low_base_rank),
                "lowBaseGrowth": len(low_base_growth_rank),
                "lowBaseQuality": len(low_base_quality_rank),
                "lowBaseGrowthStrict": len(strict_low_base_growth_rank),
                "lowBaseQualityStrict": len(strict_low_base_quality_rank),
            },
            "formalEntryCount": formal_entries,
            "proxyCandidateCount": proxy_candidates,
            "trustSignalCount": trust_signal_count,
            "trustNewEntryCount": trust_new_entry_count,
            "trustValuationVisibleCount": len(trust_rank),
            "lowBaseGap": low_base_gap_summary,
            "lowBaseGrowthGap": low_base_growth_gap,
            "lowBaseQualityGap": low_base_quality_gap,
        },
        "stocks": [_summary(detail) for detail in enriched],
        "funnel": funnel,
        "rankings": rankings_payload,
        "research": {
            **(baseline.get("research") or {}),
            "proxyReadiness": {
                "label": "研究代理可用，正式績效不可評估",
                "candidateCount": len(candidate_codes),
                "formalEntryCount": formal_entries,
                "explanation": "代理候選只由已取得的價格、投信與營收證據排序；沒有 point-in-time 母體、成本、公司行動與樣本外回測，不宣稱策略績效。",
            },
        },
    }
    release_dir = data_dir / "releases" / run_id
    for detail in enriched:
        atomic_json(release_dir / "stocks" / f"{detail['code']}.json", detail)
    manifest = {
        **release,
        "inputHash": hashlib.sha256(canonical).hexdigest(),
        "codeCommit": _git_head(),
        "formulaVersions": FORMULA_VERSIONS,
        "rankingsHash": rankings_hash,
        "baselineRunId": baseline.get("runId"),
        "enrichment": {
            "adjustedPriceSource": "yfinance Adj Close when available; Yahoo chart fallback is tagged",
            "fundamentalSource": YFINANCE_FUNDAMENTAL_SOURCE,
            "adjustedStocks": adjusted_count,
            "trackedStocks": tracked_count,
            "errorsByCode": {code: values for code, values in errors_by_code.items() if values},
        },
    }
    atomic_json(release_dir / "manifest.json", manifest)
    atomic_json(latest_path, release)
    return {
        "run_id": run_id,
        "baseline_run_id": baseline.get("runId"),
        "market_date": market_date,
        "stocks": tracked_count,
        "adjusted_price_stocks": adjusted_count,
        "candidate_count": len(candidate_codes),
        "proxy_low_position_count": low_count,
        "formal_entry_count": formal_entries,
        "errors": all_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", default="", help="comma-separated tracked codes; default uses all baseline stocks")
    parser.add_argument("--as-of", default=None, help="query end date YYYY-MM-DD; default uses latest baseline date")
    parser.add_argument("--output", default=str(ROOT / "public" / "data"))
    parser.add_argument("--offline", action="store_true", help="skip network sources and recalculate from the checked-in snapshot")
    args = parser.parse_args()
    codes = list(dict.fromkeys(code.strip() for code in args.codes.split(",") if code.strip()))
    try:
        result = build_release(Path(args.output), codes, as_of=args.as_of, offline=args.offline)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"snapshot_refresh_failed={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
