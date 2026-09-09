#!/usr/bin/env python3
"""Build a small, honest static snapshot from the FinMind free-plan boundary.

The browser never receives a token and never calls FinMind. This script stores
only normalized, published fields. Missing/uncertain fields remain unknown.
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
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.finmind_client import BudgetExceeded, FinMindClient, FinMindError, SourceBlocked  # noqa: E402
from pipeline.health_checks import empty_health_categories, health_totals  # noqa: E402
from pipeline.indicators import linear_regression, revenue_growth, trust_metrics  # noqa: E402

SCHEMA_VERSION = "1.0"
STRATEGY_VERSION = "quality-growth-v1"
FORMULA_VERSION = "lohas-linear-4y-v1"
TAIPEI = ZoneInfo("Asia/Taipei")
DATA_REF = "https://api.finmindtrade.com/api/v4/data"
SOURCE_REFS = [
    "FinMind:TaiwanStockInfo",
    "FinMind:TaiwanStockPrice",
    "FinMind:TaiwanStockInstitutionalInvestorsBuySell",
    "FinMind:TaiwanStockMonthRevenue",
    "FinMind:TaiwanStockFinancialStatements",
    "FinMind:TaiwanStockBalanceSheet",
    "FinMind:TaiwanStockCashFlowsStatement",
]
DEFAULT_CODES = ["2330", "2454", "2303", "2317", "2382", "2881", "3034", "3711"]


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def as_int(value: Any) -> int | None:
    number = as_float(value)
    return None if number is None else int(number)


def parse_day(value: Any) -> str | None:
    text = str(value or "")[:10]
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def subtract_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def next_expected_update() -> str:
    now = datetime.now(TAIPEI)
    next_day = (now + timedelta(days=1)).date()
    candidate = datetime(next_day.year, next_day.month, next_day.day, 23, 17, tzinfo=TAIPEI)
    return candidate.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def info_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        code = str(row.get("stock_id") or "").strip()
        if not code:
            continue
        current = result.get(code)
        current_date = str(current.get("date", "")) if current else ""
        if current is None or str(row.get("date") or "") >= current_date:
            raw_type = str(row.get("type") or "").lower()
            market = "TPEx" if raw_type in {"tpex", "otc"} else "TWSE" if raw_type in {"twse", "listed"} else "unknown"
            result[code] = {
                "name": str(row.get("stock_name") or code),
                "sector": str(row.get("industry_category") or ""),
                "market": market,
                "date": str(row.get("date") or ""),
            }
    return result


def price_points(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = parse_day(row.get("date"))
        close = as_float(row.get("close"))
        if not day or close is None or close <= 0:
            continue
        by_date[day] = {
            "date": day,
            "close": close,
            "volume": as_float(row.get("Trading_Volume")),
            "amount": as_float(row.get("Trading_money")),
        }
    return [by_date[key] for key in sorted(by_date)]


def institution_window(
    price: list[dict[str, Any]], rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_day: dict[str, float] = {}
    for row in rows:
        if str(row.get("name") or "") != "Investment_Trust":
            continue
        day = parse_day(row.get("date"))
        buy = as_float(row.get("buy"))
        sell = as_float(row.get("sell"))
        if day and buy is not None and sell is not None:
            by_day[day] = by_day.get(day, 0.0) + buy - sell
    last_days = [point["date"] for point in price[-10:]]
    daily: list[dict[str, Any]] = []
    nets: list[float | None] = []
    volumes: list[float | None] = []
    for day in last_days:
        net = by_day.get(day)
        volume = next((point["volume"] for point in price if point["date"] == day), None)
        nets.append(net)
        volumes.append(volume)
        daily.append({"date": day, "netShares": net, "volume": volume, "status": "pass" if net is not None and volume is not None and volume > 0 else "unknown"})
    metrics = trust_metrics(nets, volumes)
    return daily, metrics


def revenue_window(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float | None]:
    by_key: dict[tuple[int, int], float] = {}
    for row in rows:
        year = as_int(row.get("revenue_year"))
        month = as_int(row.get("revenue_month"))
        value = as_float(row.get("revenue"))
        if year is None or month is None or value is None or not 1 <= month <= 12:
            continue
        by_key[(year, month)] = value
    keys = sorted(by_key)
    points = [
        {
            "month": f"{year:04d}-{month:02d}",
            "revenue": by_key[(year, month)],
            "availableAt": str(next((row.get("create_time") for row in rows if as_int(row.get("revenue_year")) == year and as_int(row.get("revenue_month")) == month and row.get("create_time")), "")) or None,
            "status": "pass",
        }
        for year, month in keys
    ]
    if len(keys) < 3:
        return points, None
    latest = keys[-3:]
    prior = [(year - 1, month) for year, month in latest]
    if any(key not in by_key for key in prior):
        return points, None
    return points, revenue_growth([by_key[key] for key in latest], [by_key[key] for key in prior])


def unknown_quality_checks() -> list[dict[str, Any]]:
    refs = ["FinMind:TaiwanStockFinancialStatements", "FinMind:TaiwanStockBalanceSheet", "FinMind:TaiwanStockCashFlowsStatement"]
    return [
        {"label": "最近三年歸屬母公司淨利皆正", "status": "unknown", "value": "待核對", "period": "最近三個完整年度", "explanation": "已取得財報資料集，但免費快照尚未完成合併／個別、年度／累計與歸屬口徑的正式正規化。", "sourceRefs": refs},
        {"label": "最近三年營業現金流皆正", "status": "unknown", "value": "待核對", "period": "最近三個完整年度", "explanation": "缺少可重現的單季還原與報表口徑驗證，不把缺項視為 0。", "sourceRefs": refs},
        {"label": "三年 ROE 中位數 ≥ 12%", "status": "unknown", "value": "待核對", "period": "最近三個完整年度", "explanation": "ROE 必須使用期初期末平均母公司權益；任何非正分母都應為 unknown。", "sourceRefs": refs},
        {"label": "淨現金或淨負債／EBITDA < 2", "status": "unknown", "value": "待核對", "period": "近四季", "explanation": "現金、有息負債、租賃負債與 EBITDA 尚未通過同口徑組合檢查。", "sourceRefs": refs},
    ]


def make_stock(
    code: str,
    meta: dict[str, str],
    price: list[dict[str, Any]],
    institution: list[dict[str, Any]],
    trust: dict[str, Any],
    revenue: list[dict[str, Any]],
    revenue_growth_value: float | None,
    fetch_errors: list[str],
) -> dict[str, Any]:
    closes = [point["close"] for point in price]
    regression = linear_regression(closes)
    last_price = price[-1]["close"] if price else None
    previous_price = price[-2]["close"] if len(price) >= 2 else None
    change_pct = None if last_price is None or previous_price in (None, 0) else (last_price - previous_price) / previous_price
    liquidity_values = [point["amount"] for point in price[-20:]]
    liquidity_ok = len(liquidity_values) == 20 and all(value is not None for value in liquidity_values)
    avg_amount = sum(value for value in liquidity_values if value is not None) / 20 if liquidity_ok else None
    liquidity_status = "pass" if avg_amount is not None and avg_amount >= 20_000_000 else "unknown"
    entry_reasons: list[str] = []
    if trust.get("status") == "pass" and (trust.get("net_shares_10") or 0) > 0:
        net = int(trust["net_shares_10"])
        pct = float(trust["participation_10"] or 0) * 100
        if liquidity_status == "pass":
            entry_reasons.append(f"投信關注：十日淨買超 {net:,} 股，該股成交占比 {pct:.2f}%")
        else:
            entry_reasons.append(f"投信觀察：十日淨買超 {net:,} 股；20 日流動性仍待驗證")
    if revenue_growth_value is not None:
        entry_reasons.append(f"營收線索：三月合計年增 {revenue_growth_value * 100:+.1f}%；營業利益條件待核對")
    if regression.get("z") is not None:
        entry_reasons.append(f"價格描述：raw close proxy Z {float(regression['z']):+.2f}；未作正式四年訊號")
    if not entry_reasons:
        entry_reasons.append("尚無足夠條件形成正式候選理由")
    risks = [
        "免費版未驗證核准調整價／公司行動",
        "財務品質必要條件 unknown",
    ]
    if fetch_errors:
        risks.append("部分資料集請求未完成")
    if not price:
        risks.insert(0, "尚無可用報價")
    state = "值得研究" if trust.get("status") == "pass" and (trust.get("net_shares_10") or 0) > 0 and liquidity_status == "pass" else "待補資料" if price else "資料不足"
    detail_limitations = [
        "TaiwanStockPrice 是未調整行情；免費快照未使用付費 TaiwanStockPriceAdj。",
        "因此四年回歸數值只作 raw close proxy，signalEligible=false。",
        "財報日期不是天然公告時間；未完成 point-in-time 可得性認證。",
    ]
    quality_checks = unknown_quality_checks()
    health_categories = empty_health_categories(
        reason="已抓到部分公開資料，但尚未完成年度／季度、合併口徑與公告日的正規化；此項暫不判定。",
        refs=["FinMind:TaiwanStockFinancialStatements", "FinMind:TaiwanStockBalanceSheet", "FinMind:TaiwanStockCashFlowsStatement", "TWSE OpenAPI", "TPEx OpenAPI"],
    )
    health_score = health_totals(health_categories)
    summary = {
        "code": code,
        "name": meta.get("name", code),
        "market": meta.get("market", "unknown"),
        "sector": meta.get("sector", ""),
        "asOf": price[-1]["date"] if price else None,
        "lastPrice": last_price,
        "changePct": change_pct,
        "zScore": regression.get("z"),
        "slope": regression.get("slope"),
        "fiveLineStatus": "unknown",
        "qualityStatus": "unknown",
        "growthStatus": "unknown" if revenue_growth_value is not None else "unknown",
        "liquidityStatus": liquidity_status,
        "dataStatus": "unknown" if price else "fail",
        "signalState": state,
        "entryReasons": entry_reasons,
        "risks": risks,
        "institutionNetShares10": trust.get("net_shares_10"),
        "participation10": trust.get("participation_10"),
        "positiveDays10": trust.get("positive_days_10"),
        "revenueGrowth3m": revenue_growth_value,
        "ttmOperatingProfitGrowth": None,
        "sourceRefs": SOURCE_REFS,
        "healthCategories": health_categories,
        "healthScore": health_score,
    }
    bands = {str(k): None for k in [-2, -1, 0, 1, 2]}
    if regression.get("last_mid") is not None and regression.get("sigma") is not None:
        bands = {str(k): regression["last_mid"] + k * regression["sigma"] for k in [-2, -1, 0, 1, 2]}
    for index, point in enumerate(price):
        mid = None if regression.get("intercept") is None or regression.get("slope") is None else regression["intercept"] + regression["slope"] * index
        sigma = regression.get("sigma")
        point["mid"] = mid
        point["bands"] = {str(k): None if mid is None or sigma is None else mid + k * sigma for k in [-2, -1, 0, 1, 2]}
    detail = {
        **summary,
        "priceSeries": price,
        "regression": {
            "status": "unknown",
            "method": FORMULA_VERSION,
            "label": "raw close proxy（免費版未取得已核准還原價）",
            "intercept": regression.get("intercept"),
            "slope": regression.get("slope"),
            "lastMid": regression.get("last_mid"),
            "sigma": regression.get("sigma"),
            "z": regression.get("z"),
            "bands": bands,
            "coveragePct": None,
            "historyStart": price[0]["date"] if price else None,
            "historyEnd": price[-1]["date"] if price else None,
            "signalEligible": False,
            "reason": "免費 FinMind 快照只取得 TaiwanStockPrice 未調整收盤價；圖表可研究行情，正式四年訊號待調整價與公司行動驗證。",
            "sourceRefs": ["FinMind:TaiwanStockPrice"],
        },
        "institutionalDaily": institution,
        "revenueMonthly": revenue,
        "qualityChecks": quality_checks,
        "healthCategories": health_categories,
        "healthScore": health_score,
        "historySnapshots": [],
        "notes": [],
        "detailLimitations": detail_limitations,
    }
    return detail


def ranking_row(stock: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind == "trust":
        value = None if stock["participation10"] is None else stock["participation10"] * 100
        reason = stock["entryReasons"][0]
        label = "%"
        status = "pass" if stock["liquidityStatus"] == "pass" and stock["participation10"] is not None else "unknown"
    elif kind == "growth":
        value = None if stock["revenueGrowth3m"] is None else stock["revenueGrowth3m"] * 100
        reason = "三月合計營收可計算；近四季營業利益與可得時間仍待核對"
        label = "%"
        status = "unknown"
    else:
        value = stock["zScore"]
        reason = "免費版調整價未驗證，暫不產生低位正式排行"
        label = ""
        status = "unknown"
    return {"rank": 0, "code": stock["code"], "name": stock["name"], "sector": stock["sector"], "value": value, "valueLabel": label, "status": status, "reason": reason}


def rank(rows: list[dict[str, Any]], reverse: bool) -> list[dict[str, Any]]:
    valid = [row for row in rows if row["value"] is not None]
    valid.sort(key=lambda row: (-row["value"] if reverse else row["value"], row["code"]))
    for index, row in enumerate(valid[:100], start=1):
        row["rank"] = index
    return valid[:100]


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def fetch_optional(client: FinMindClient, label: str, **kwargs: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return client.get(label, **kwargs), None
    except SourceBlocked:
        raise
    except (BudgetExceeded, FinMindError) as exc:
        return [], type(exc).__name__


def build_snapshot(codes: list[str], output: Path, as_of: str | None = None) -> dict[str, Any]:
    client = FinMindClient.from_env()
    info_rows = client.get("TaiwanStockInfo")
    metadata = info_map(info_rows)
    end = date.fromisoformat(as_of) if as_of else date.today()
    start = subtract_years(end, 4)
    institution_start = end - timedelta(days=70)
    revenue_start = end - timedelta(days=620)
    financial_start = subtract_years(end, 4)
    details: list[dict[str, Any]] = []
    queue: list[str] = []
    blocked_reason: str | None = None

    for code in codes:
        errors: list[str] = []
        try:
            price_rows, error = fetch_optional(client, "TaiwanStockPrice", data_id=code, start_date=start.isoformat(), end_date=end.isoformat())
            if error: errors.append(f"price:{error}")
            price = price_points(price_rows)
            institution_rows, error = fetch_optional(client, "TaiwanStockInstitutionalInvestorsBuySell", data_id=code, start_date=institution_start.isoformat(), end_date=end.isoformat())
            if error: errors.append(f"institution:{error}")
            institution, trust = institution_window(price, institution_rows)
            revenue_rows, error = fetch_optional(client, "TaiwanStockMonthRevenue", data_id=code, start_date=revenue_start.isoformat(), end_date=end.isoformat())
            if error: errors.append(f"revenue:{error}")
            revenue, rev_growth = revenue_window(revenue_rows)
            # These calls establish whether the free account returned the raw
            # financial datasets. The current base keeps their rule status
            # unknown until period/statement normalization is implemented.
            for dataset in ("TaiwanStockFinancialStatements", "TaiwanStockBalanceSheet", "TaiwanStockCashFlowsStatement"):
                _, error = fetch_optional(client, dataset, data_id=code, start_date=financial_start.isoformat(), end_date=end.isoformat())
                if error: errors.append(f"{dataset}:{error}")
            details.append(make_stock(code, metadata.get(code, {"name": code, "market": "unknown", "sector": ""}), price, institution, trust, revenue, rev_growth, errors))
        except (SourceBlocked, BudgetExceeded) as exc:
            blocked_reason = str(exc)
            queue = codes[codes.index(code):]
            break
        except FinMindError as exc:
            errors.append(type(exc).__name__)
            details.append(make_stock(code, metadata.get(code, {"name": code, "market": "unknown", "sector": ""}), [], [], {"status": "unknown", "net_shares_10": None, "positive_days_10": None, "participation_10": None}, [], None, errors))

    fetched_codes = {detail["code"] for detail in details}
    queue.extend(code for code in codes if code not in fetched_codes and code not in queue)
    market_dates = [stock["asOf"] for stock in details if stock["asOf"]]
    market_date = max(market_dates) if market_dates else None
    trust_candidates = [ranking_row(stock, "trust") for stock in details if stock["participation10"] is not None and (stock["institutionNetShares10"] or 0) > 0 and stock["liquidityStatus"] == "pass"]
    growth_observations = [ranking_row(stock, "growth") for stock in details if stock["revenueGrowth3m"] is not None]
    trust_rank = rank(trust_candidates, reverse=True)
    growth_rank = rank(growth_observations, reverse=True)
    low_rank: list[dict[str, Any]] = []
    generated = iso_now()
    canonical = json.dumps({"codes": codes, "details": details, "marketDate": market_date}, ensure_ascii=False, sort_keys=True).encode()
    digest = hashlib.sha256(canonical).hexdigest()[:10]
    run_id = f"live-{datetime.now(TAIPEI).strftime('%Y%m%d-%H%M%S')}-{digest}"
    stats = client.stats()
    blocked = blocked_reason or (stats.blocked_reason if stats.blocked else None)
    freshness = "degraded" if blocked or len(details) < len(codes) or any(stock["dataStatus"] != "pass" for stock in details) else "current"
    if blocked:
        status_message = f"FinMind 已停止補資料（{blocked}）；已取得內容保留，待補隊列未丟失。"
    else:
        status_message = "FinMind 免費版按股快照已生成；財務與調整價仍依規格標示 unknown。"
    universe_count = len(metadata)
    coverage_pct = len(details) / universe_count * 100 if universe_count else None
    release = {
        "schemaVersion": SCHEMA_VERSION,
        "strategyVersion": STRATEGY_VERSION,
        "formulaVersion": FORMULA_VERSION,
        "runId": run_id,
        "marketDate": market_date,
        "generatedAt": generated,
        "nextExpectedUpdateAt": next_expected_update(),
        "freshness": freshness,
        "statusMessage": status_message,
        "sourceRefs": SOURCE_REFS + ["FinMind:user_info"],
        "coverage": {
            "universeCount": universe_count,
            "databaseCount": len(details),
            "candidateCount": len(trust_rank),
            "pendingCount": max(0, universe_count - len(details)) + len(queue),
            "financialCompleteCount": 0,
            "priceCompleteCount": sum(bool(stock["asOf"]) for stock in details),
            "completenessPct": coverage_pct,
            "finmindRequests": stats.attempts,
            "queueStatus": "待補：免費版按股增量；未驗證欄位不進場" if not blocked else "FinMind 暫停；待補隊列已保存",
        },
        "summary": {
            "watchCount": 0,
            "lowPositionCount": 0,
            "candidateRouteCounts": {"trust": len(trust_rank), "growth": 0, "lowPosition": 0},
            "addedToday": 0,
            "improvedToday": 0,
            "removedToday": 0,
        },
        "stocks": [{key: stock[key] for key in stock if key not in {"priceSeries", "regression", "institutionalDaily", "revenueMonthly", "qualityChecks", "historySnapshots", "notes", "detailLimitations"}} for stock in details],
        "rankings": {"trust": trust_rank, "growth": growth_rank, "lowPosition": low_rank},
        "research": {
            "status": "not_evaluable",
            "reason": "尚未完成 point-in-time 母體、公告可得時間、公司行動、成本與樣本外回測；不以示範績效填空。",
            "cagr": None,
            "maxDrawdown": None,
            "periods": [],
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    release_dir = output / "releases" / run_id
    release_dir.mkdir(parents=True, exist_ok=True)
    for detail in details:
        atomic_json(release_dir / "stocks" / f"{detail['code']}.json", detail)
    atomic_json(release_dir / "manifest.json", {**release, "inputHash": hashlib.sha256(canonical).hexdigest(), "queue": queue})
    atomic_json(output / "latest.json", release)
    if queue:
        atomic_json(output.parent.parent / "private" / "refresh_queue.json", {"createdAt": generated, "codes": queue, "reason": blocked or "not_fetched", "source": "FinMind"})
    return {"run_id": run_id, "market_date": market_date, "stocks": len(details), "queued": len(queue), "requests": stats.attempts, "allowed_attempts": stats.allowed_attempts, "blocked": blocked}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", default=",".join(DEFAULT_CODES), help="comma-separated stock codes")
    parser.add_argument("--as-of", default=None, help="optional query end date YYYY-MM-DD")
    parser.add_argument("--output", default=str(ROOT / "public" / "data"))
    args = parser.parse_args()
    codes = list(dict.fromkeys(code.strip() for code in args.codes.split(",") if code.strip()))
    if not codes:
        parser.error("at least one code is required")
    try:
        result = build_snapshot(codes, Path(args.output), args.as_of)
    except (FinMindError, ValueError) as exc:
        print(f"snapshot_failed={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
