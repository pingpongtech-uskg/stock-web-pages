"""Small, strict parsers for official current valuation and company-master data."""
from __future__ import annotations

import math
import re
from typing import Any, Mapping, Sequence

from .institutional_sources import normalize_market_date
from .public_data_models import stable_hash


def _numeric(value: Any) -> float | None:
    text = str(value if value is not None else "").strip().replace(",", "")
    if text in {"", "-", "—", "－－", "－", "N/A", "NA"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _common_code(value: Any) -> str | None:
    code = str(value or "").strip()
    return code if re.fullmatch(r"[1-9]\d{3}", code) else None


def _check_date(value: Any, requested_date: str | None) -> str:
    actual = normalize_market_date(value)
    if requested_date is not None and actual != normalize_market_date(requested_date):
        raise ValueError(f"response date {actual} does not match requested date {requested_date}")
    return actual


def parse_twse_valuation(payload: Mapping[str, Any], *, source_url: str, requested_date: str | None = None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, Mapping) or str(payload.get("stat", "")).upper() != "OK":
        raise ValueError("TWSE valuation status is not OK")
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise ValueError("TWSE valuation fields/data missing")
    required = ("股票代號", "股票名稱", "本益比", "殖利率(%)", "股價淨值比")
    if any(field not in fields for field in required):
        raise ValueError("TWSE valuation required field missing")
    _check_date(payload.get("date"), requested_date)
    indexes = {field: fields.index(field) for field in required}
    result: dict[str, dict[str, Any]] = {}
    for row in data:
        if not isinstance(row, Sequence) or len(row) <= max(indexes.values()):
            continue
        code = _common_code(row[indexes["股票代號"]])
        if code is None:
            continue
        result[code] = {
            "name": str(row[indexes["股票名稱"]]).strip(),
            "market": "TWSE",
            "pe": _numeric(row[indexes["本益比"]]),
            "pb": _numeric(row[indexes["股價淨值比"]]),
            "dividend_yield": _numeric(row[indexes["殖利率(%)"]]),
            "source_id": "twse.valuation_current",
            "source_url": source_url,
        }
    if not result:
        raise ValueError("TWSE valuation has no common-share rows")
    return result


def parse_tpex_valuation(payload: Sequence[Mapping[str, Any]], *, source_url: str, requested_date: str | None = None) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise ValueError("TPEx valuation payload must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        code = _common_code(row.get("SecuritiesCompanyCode", row.get("Code")))
        if code is None:
            continue
        _check_date(row.get("Date"), requested_date)
        result[code] = {
            "name": str(row.get("CompanyName", "")).strip(),
            "market": "TPEx",
            "pe": _numeric(row.get("PriceEarningRatio")),
            "pb": _numeric(row.get("PriceBookRatio")),
            "dividend_yield": _numeric(row.get("YieldRatio")),
            "source_id": "tpex.valuation_current",
            "source_url": source_url,
        }
    if not result:
        raise ValueError("TPEx valuation has no common-share rows")
    return result


def parse_company_master(rows: Sequence[Mapping[str, Any]], *, market: str) -> dict[str, dict[str, Any]]:
    if market not in {"TWSE", "TPEx"}:
        raise ValueError("market must be TWSE or TPEx")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("company master must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if market == "TWSE":
            code = _common_code(row.get("公司代號"))
            name = str(row.get("公司簡稱") or row.get("公司名稱") or "").strip()
            listing = row.get("上市日期")
        else:
            code = _common_code(row.get("SecuritiesCompanyCode"))
            name = str(row.get("CompanyAbbreviation") or row.get("CompanyName") or "").strip()
            listing = row.get("DateOfListing")
        if code is None or not name:
            continue
        listing_date = None
        if listing not in (None, "", "-"):
            listing_date = normalize_market_date(listing)
        result[code] = {"code": code, "name": name, "market": market, "listing_date": listing_date}
    if not result:
        raise ValueError(f"{market} company master has no common-share rows")
    return result


def fact_hash(payload: Any) -> str:
    return stable_hash(payload)
