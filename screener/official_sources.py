"""Allow-listed, fail-closed normalizers for official market sources."""
from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

TDCC_ENDPOINTS = {
    "listed": "https://openapi.tdcc.com.tw/v1/opendata/2-22",
    "otc": "https://openapi.tdcc.com.tw/v1/opendata/2-23",
}


def _month(row: Mapping[str, object]) -> str:
    raw = str(row.get("資料年月", row.get("\ufeff資料年月", ""))).strip()
    if not re.fullmatch(r"\d{5}", raw):
        raise ValueError("invalid month")
    year, month = int(raw[:3]) + 1911, int(raw[3:])
    if not 1 <= month <= 12:
        raise ValueError("invalid month")
    return f"{year:04d}-{month:02d}"


def _number(value: object, field: str) -> float:
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError(f"invalid {field}") from None
    if not math.isfinite(number):
        raise ValueError(f"invalid {field}")
    return number


def normalize_tdcc_rows(rows: object, *, market: str) -> list[dict[str, object]]:
    """Normalize TDCC monthly rows; reject ETFs and malformed records."""
    if market not in TDCC_ENDPOINTS:
        raise ValueError("unsupported market")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("rows must be a sequence")
    output: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("row must be an object")
        code = str(row.get("股票代號", "")).strip()
        if not re.fullmatch(r"\d{4}", code):
            raise ValueError("invalid ordinary share code")
        if code.startswith("00"):
            raise ValueError("not an ordinary share")
        output.append({
            "code": code,
            "month": _month(row),
            "shareholder_count": _number(row.get("集保股東戶數"), "shareholder_count"),
            "held_thousand_shares": _number(row.get("本月底保管千股數", 0), "held_thousand_shares"),
            "market": market,
        })
    return output
