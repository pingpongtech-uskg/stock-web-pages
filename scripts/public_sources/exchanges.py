"""Public TWSE/TPEx JSON normalization helpers."""
from __future__ import annotations

import json
import math
import re
from typing import Any


def _rows(payload: Any) -> list[dict[str, Any]]:
    def normalize(row: dict[str, Any]) -> dict[str, Any]:
        return {str(k).lstrip(chr(0xFEFF)).strip(): v for k, v in row.items()}

    if isinstance(payload, list):
        return [normalize(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        data = payload["data"]
        fields = payload.get("fields")
        if isinstance(fields, list) and all(isinstance(x, str) for x in fields):
            return [dict(zip([x.lstrip(chr(0xFEFF)).strip() for x in fields], row)) for row in data if isinstance(row, list)]
        return [normalize(row) for row in data if isinstance(row, dict)]
    raise ValueError("exchange payload must be a list or object with data")


def _first(row: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return default


def _code(value: Any) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[1-9]\d{3}", text):
        raise ValueError(f"non-ordinary or invalid stock code: {value!r}")
    return text


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "-", "－", "—", "–", "N/A", "NA"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid valuation number: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError("valuation number must be finite")
    return number


def normalize_company_rows(rows: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    if market not in {"TWSE", "TPEx"}:
        raise ValueError("market must be TWSE or TPEx")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        try:
            code = _code(_first(raw, ("公司代號", "證券代號", "SecuritiesCompanyCode", "Code")))
        except ValueError:
            # ETFs, preferred instruments, and malformed rows are not ordinary shares.
            continue
        if code in seen:
            raise ValueError(f"duplicate {market} company code: {code}")
        seen.add(code)
        result.append(
            {
                "code": code,
                "name": str(_first(raw, ("公司簡稱", "公司名稱", "CompanyAbbreviation", "CompanyName", "Name"), "")).strip(),
                "market": market,
                "ordinary_share": True,
                "listing_date": _first(raw, ("上市日期", "DateOfListing")),
                "industry": _first(raw, ("產業別", "SecuritiesIndustryCode")),
            }
        )
    return result


def join_eligible_universe(*markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    codes_by_market: dict[str, set[str]] = {}
    for rows in markets:
        for row in rows:
            code = str(row.get("code", ""))
            market = str(row.get("market", ""))
            key = (code, market)
            if key in result:
                raise ValueError(f"duplicate universe row: {code}/{market}")
            codes_by_market.setdefault(code, set()).add(market)
            result[key] = row
    overlap = sorted(code for code, market_set in codes_by_market.items() if len(market_set) > 1)
    if overlap:
        raise ValueError(f"market overlap: {','.join(overlap)}")
    return [result[key] for key in sorted(result)]


def parse_valuation_payload(payload: Any, *, market: str) -> dict[str, dict[str, Any]]:
    if market not in {"TWSE", "TPEx"}:
        raise ValueError("market must be TWSE or TPEx")
    result: dict[str, dict[str, Any]] = {}
    for raw in _rows(payload):
        raw_code = _first(raw, ("Code", "證券代號", "SecuritiesCompanyCode", "公司代號"))
        try:
            code = _code(raw_code)
        except ValueError:
            continue
        if code in result:
            raise ValueError(f"duplicate valuation code: {code}/{market}")
        result[code] = {
            "code": code,
            "market": market,
            "date": str(_first(raw, ("Date", "日期", "出表日期"), "")).strip(),
            "name": str(_first(raw, ("Name", "證券名稱", "CompanyName", "公司名稱"), "")).strip(),
            "pe": _optional_number(_first(raw, ("PEratio", "本益比", "PriceEarningRatio"))),
            "pb": _optional_number(_first(raw, ("PBratio", "股價淨值比", "PriceBookRatio"))),
            "yield": _optional_number(_first(raw, ("DividendYield", "殖利率(%)", "YieldRatio"))),
        }
    return result


def parse_json_text(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception as exc:
        raise ValueError("exchange JSON parse error") from exc


def parse_price_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("price payload must contain data rows")
    fields = payload.get("fields")
    if not isinstance(fields, list):
        raise ValueError("price payload must contain fields")
    rows: list[dict[str, Any]] = []
    for raw in payload["data"]:
        if not isinstance(raw, list):
            continue
        row = dict(zip(fields, raw))
        close = _optional_number(_first(row, ("收盤價", "Close", "ClosePrice")))
        if close is None:
            continue
        rows.append({"date": str(_first(row, ("日期", "Date"), "")).strip(), "close": close})
    if not rows:
        raise ValueError("price payload has no finite close rows")
    return rows
