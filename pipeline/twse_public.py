"""Small, dependency-free client for the public TWSE OpenAPI snapshots.

The endpoints return the whole market.  We fetch each endpoint once, then keep
only the tracked symbols in the published release.  The normalizer deliberately
keeps the original field names alongside a compact set of numeric fields so a
future MOPS/XBRL backfill can be compared without losing provenance.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from typing import Any, Iterable

BASE = "https://openapi.twse.com.tw/v1"
SOURCE = "TWSE OpenAPI"


def _number(value: Any) -> float | None:
    if value in (None, "", "-", "--", "N/A", "null"):
        return None
    try:
        result = float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _code(row: dict[str, Any]) -> str:
    return str(row.get("公司代號") or row.get("Code") or row.get("證券代號") or "").strip()


def _roc_date(value: Any) -> Any:
    """Normalize TWSE ROC calendar dates while preserving unknown values."""
    text = str(value or "")
    digits = "".join(character for character in text if character.isdigit())
    if len(digits) == 8 and int(digits[:4]) >= 1900:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(digits) == 7 and digits[:3].isdigit():
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}-{digits[5:7]}"
    if len(digits) == 6 and int(digits[:4]) >= 1900:
        return f"{digits[:4]}-{digits[4:6]}"
    if len(digits) == 6 and digits[:3].isdigit():
        return f"{int(digits[:3]) + 1911:04d}-{digits[3:5]}"
    return value


def fetch_endpoint(endpoint: str, *, timeout: int = 20) -> list[dict[str, Any]]:
    request = Request(f"{BASE}/{endpoint}", headers={"User-Agent": "stock-web-pages/1.0"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _income(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "availableAt": _roc_date(row.get("出表日期")),
        "year": str(row.get("年度") or ""),
        "quarter": row.get("季別"),
        "revenue": _number(row.get("營業收入")),
        "grossProfit": _number(row.get("營業毛利（毛損）")),
        "operatingProfit": _number(row.get("營業利益（損失）")),
        "pretaxProfit": _number(row.get("稅前淨利（淨損）")),
        "netIncome": _number(row.get("本期淨利（淨損）")),
        "parentNetIncome": _number(row.get("淨利（淨損）歸屬於母公司業主")),
        "eps": _number(row.get("基本每股盈餘（元）")),
    }


def _balance(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "availableAt": _roc_date(row.get("出表日期")),
        "year": str(row.get("年度") or ""),
        "quarter": row.get("季別"),
        "assets": _number(row.get("資產總計")),
        "liabilities": _number(row.get("負債總計")),
        "equity": _number(row.get("權益總計")),
        "currentAssets": _number(row.get("流動資產")),
        "currentLiabilities": _number(row.get("流動負債")),
        "receivables": _number(row.get("應收帳款淨額")),
        "inventory": _number(row.get("存貨")),
        "bookValuePerShare": _number(row.get("每股參考淨值")),
    }


def _revenue(row: dict[str, Any]) -> dict[str, Any]:
    raw_month = str(row.get("資料年月") or "")
    month_value = _roc_date(raw_month)
    month = str(month_value)[:7] if month_value else raw_month[:7]
    return {
        "month": month,
        "revenue": _number(row.get("營業收入-當月營收")),
        "priorMonthRevenue": _number(row.get("營業收入-上月營收")),
        "priorYearRevenue": _number(row.get("營業收入-去年當月營收")),
        "availableAt": _roc_date(row.get("出表日期")),
    }


def _dividend(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "year": str(row.get("股利年度") or ""),
        "period": row.get("股利所屬年(季)度"),
        "cashPerShare": _number(row.get("股東配發-盈餘分配之現金股利(元/股)")),
        "stockPerShare": _number(row.get("股東配發-盈餘轉增資配股(元/股)")),
        "boardDate": _roc_date(row.get("董事會（擬議）股利分派日")),
        "availableAt": _roc_date(row.get("出表日期")),
    }


def _valuation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": _roc_date(row.get("Date")),
        "pe": _number(row.get("PEratio")),
        "pb": _number(row.get("PBratio")),
        "dividendYield": _number(row.get("DividendYield")),
    }


def build_health_inputs(codes: Iterable[str], *, timeout: int = 20) -> dict[str, dict[str, Any]]:
    wanted = {str(code) for code in codes}
    result = {code: {"source": SOURCE, "fetchedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat()} for code in wanted}
    endpoint_rows: dict[str, list[dict[str, Any]]] = {}
    endpoints = {
        "valuation": "exchangeReport/BWIBBU_ALL",
        "monthlyRevenue": "opendata/t187ap05_L",
        "dividend": "opendata/t187ap45_L",
    }
    # Industry-specific financial endpoints are snapshots of different
    # company populations (general, financial holding, insurance, etc.).
    # Fetching all variants once prevents a bank or insurer from becoming an
    # unexplained blank simply because it is not in the general-industry feed.
    financial_endpoints = {
        "income": [f"opendata/t187ap06_L_{suffix}" for suffix in ("ci", "basi", "fh", "ins", "bd", "mim")],
        "balance": [f"opendata/t187ap07_L_{suffix}" for suffix in ("ci", "basi", "fh", "ins", "bd", "mim")],
    }
    errors: dict[str, str] = {}
    for key, endpoint in endpoints.items():
        try:
            endpoint_rows[key] = fetch_endpoint(endpoint, timeout=timeout)
        except Exception as exc:  # the caller publishes the error, never fake a value
            endpoint_rows[key] = []
            errors[key] = f"{endpoint}: {type(exc).__name__}"
    for key, endpoint_list in financial_endpoints.items():
        endpoint_rows[key] = []
        failed = []
        for endpoint in endpoint_list:
            try:
                endpoint_rows[key].extend(fetch_endpoint(endpoint, timeout=timeout))
            except Exception as exc:
                failed.append(f"{endpoint}: {type(exc).__name__}")
        if not endpoint_rows[key] and failed:
            errors[key] = "; ".join(failed)
    valuation_universe = []
    for row in endpoint_rows["valuation"]:
        item = _valuation(row)
        if item["pe"] is not None or item["pb"] is not None or item["dividendYield"] is not None:
            valuation_universe.append(item)
    for code in wanted:
        entry = result[code]
        entry["incomeQuarterly"] = [_income(row) for row in endpoint_rows["income"] if _code(row) == code]
        entry["balanceQuarterly"] = [_balance(row) for row in endpoint_rows["balance"] if _code(row) == code]
        entry["monthlyRevenueOfficial"] = [_revenue(row) for row in endpoint_rows["monthlyRevenue"] if _code(row) == code and row.get("資料年月")]
        entry["dividends"] = [_dividend(row) for row in endpoint_rows["dividend"] if _code(row) == code]
        valuation_rows = [_valuation(row) for row in endpoint_rows["valuation"] if _code(row) == code]
        entry["valuationCurrent"] = valuation_rows[-1] if valuation_rows else {}
        entry["valuationUniverse"] = valuation_universe
        if errors:
            entry["errors"] = errors
    return result
