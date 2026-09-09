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
    python scripts/refresh_snapshot.py --codes 2330,2454,2303,2317,2382,2881,3034,3711 --output public/data

The browser never calls Yahoo or FinMind and no API token is written to the
published files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
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
    derive_signal_state,
    formal_growth_status,
    growth_proxy_status,
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


def baseline_details(data_dir: Path, release: dict[str, Any]) -> list[dict[str, Any]]:
    run_id = str(release.get("runId") or "")
    result: list[dict[str, Any]] = []
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
    }
    return {key: value for key, value in detail.items() if key not in hidden}


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


def enrich_detail(detail: dict[str, Any], *, end: date, offline: bool = False, public_inputs: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    code = str(detail.get("code") or "")
    market = str(detail.get("market") or "TWSE")
    errors: list[str] = []
    source_refs: list[str] = []
    raw_price = [dict(point) for point in detail.get("priceSeries", []) if isinstance(point, dict)]
    start = end.replace(year=end.year - 4) if end.month != 2 or end.day != 29 else end.replace(year=end.year - 4, day=28)

    adjusted_rows: list[dict[str, Any]] = []
    if not offline:
        adjusted_rows, price_source, error = fetch_adjusted_history(code, market, start, end)
        if price_source:
            source_refs.append(price_source)
        if error:
            errors.append(error)
    price = merge_adjusted_prices(raw_price, adjusted_rows)
    price, regression = apply_regression(price, prefer_adjusted=True)
    if regression["priceBasis"] == "adjusted":
        source_refs.append(YFINANCE_PRICE_SOURCE if any(row.get("source") == YFINANCE_PRICE_SOURCE for row in adjusted_rows) else YAHOO_CHART_SOURCE)
    elif raw_price:
        source_refs.append("FinMind:TaiwanStockPrice")

    metrics = _proxy_metrics_from_existing(detail)
    if not offline:
        fresh_metrics, fundamentals_source, error = fetch_fundamental_proxies(code, market)
        if fresh_metrics:
            metrics = fresh_metrics
        if fundamentals_source:
            source_refs.append(fundamentals_source)
        if error:
            errors.append(error)
    proxy_checks = quality_proxy_checks(metrics, source_ref=YFINANCE_FUNDAMENTAL_SOURCE)
    quality_proxy = proxy_status(proxy_checks)
    quality_proxy_reason = proxy_status_reason(proxy_checks)

    revenue_growth = detail.get("revenueGrowth3m")
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
                f"低位代理：{basis_label} 四年 Z {float(regression_z):+.2f}、斜率 {float(regression_slope):+.4f}；"
                + ("正式八週與品質條件仍待核對" if not formal_entry else "正式條件已通過")
            )
        else:
            reasons.append(f"價格描述：{basis_label} 四年 Z {float(regression_z):+.2f}；未形成低位條件")
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
            "lastPrice": latest_raw if latest_raw is not None else _current_price(detail),
            "changePct": change_pct if change_pct is not None else detail.get("changePct"),
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
    limitations = [
        str(value)
        for value in detail.get("detailLimitations", [])
        if value and "raw close proxy" not in str(value) and "調整價" not in str(value)
    ]
    if regression.get("priceBasis") == "adjusted":
        limitations.insert(0, "四年研究曲線使用 yfinance Adj Close；原始 FinMind close 仍保留作報價參考。")
        limitations.insert(1, "yfinance 非交易所官方資料；此頁供個人研究，來源與處理版本隨快照保存。")
    elif raw_values:
        limitations.insert(0, "四年研究曲線目前使用 FinMind 未調整 close proxy；公司行動／股利調整待驗證。")
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

    trust_rows: list[dict[str, Any]] = []
    growth_rows: list[dict[str, Any]] = []
    low_rows: list[dict[str, Any]] = []
    low_count = 0
    formal_entries = 0
    proxy_candidates = 0
    candidate_codes: set[str] = set()
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
                        "reason": f"Z {float(z):+.2f} ≤ 0；正斜率低位代理，完整歷史條件仍待驗證",
                    }
                )

    trust_rank = rank_rows(trust_rows, reverse=True)
    growth_rank = rank_rows(growth_rows, reverse=True)
    low_rank = rank_rows(low_rows, reverse=False)
    if formal_entries == 0:
        formal_entries = sum(1 for detail in enriched if detail.get("signalState") == "進場觀察")
    if proxy_candidates == 0:
        proxy_candidates = sum(1 for detail in enriched if detail.get("signalState") in {"低位觀察", "值得研究"})

    tracked_count = len(enriched)
    tracked_complete = sum(1 for detail in enriched if detail.get("dataStatus") == "pass")
    tracked_pct = tracked_complete / tracked_count * 100 if tracked_count else None
    universe = int((baseline.get("coverage") or {}).get("universeCount") or tracked_count)
    universe_pct = tracked_count / universe * 100 if universe else None
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
        status_message = f"已更新 {adjusted_count}/{tracked_count} 檔調整價；其餘沿用可得 raw close，代理與正式條件分開標示。"
    else:
        freshness = "current"
        status_message = f"已更新 {tracked_count} 檔追蹤研究；四年曲線使用 yfinance Adj Close，財務品質仍依可得期間標示。"
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
        "scopeLabel": f"明確追蹤 {tracked_count} 檔（非全市場）",
        "queueStatus": f"研究範圍 {tracked_count}/{tracked_count}；市場母體 {universe:,} 檔，未覆蓋 {max(0, universe - tracked_count):,} 檔",
    }
    source_refs = merge_refs(baseline.get("sourceRefs"), used_sources)
    release = {
        **baseline,
        "schemaVersion": "1.1",
        "formulaVersion": "lohas-linear-4y-research-v2",
        "runId": run_id,
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
            },
            "formalEntryCount": formal_entries,
            "proxyCandidateCount": proxy_candidates,
        },
        "stocks": [_summary(detail) for detail in enriched],
        "rankings": {"trust": trust_rank, "growth": growth_rank, "lowPosition": low_rank},
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
