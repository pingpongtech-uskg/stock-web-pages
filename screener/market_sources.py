"""Official daily price parsers and the legacy-compatible Z calculation."""
from __future__ import annotations

import csv
from datetime import date
import io
import math
import re
from typing import Any, Mapping, Sequence

from .institutional_sources import normalize_market_date


def _code(value: Any) -> str | None:
    text = str(value or "").strip()
    # ETF/fund rows in the all-market quote files commonly begin with 0. The
    # institutional source already supplies ordinary stock candidates; keeping
    # this guard prevents an ETF from entering the common-share price map.
    return text if re.fullmatch(r"[1-9]\d{3}", text) else None


def _price(value: Any) -> float | None:
    text = str(value if value is not None else "").strip().replace(",", "")
    if text in {"", "-", "—", "－－", "－", "N/A", "NA"}:
        return None
    try:
        result = float(text)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def parse_twse_prices(csv_text: str, *, requested_date: str | None = None) -> dict[str, float]:
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("TWSE price CSV is empty")
    rows = list(csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"))))
    required = {"日期", "證券代號", "收盤價"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError("TWSE price CSV required fields missing")
    expected = normalize_market_date(requested_date) if requested_date else None
    result: dict[str, float] = {}
    for row in rows:
        if expected is not None and normalize_market_date(row.get("日期")) != expected:
            continue
        code = _code(row.get("證券代號"))
        price = _price(row.get("收盤價"))
        if code is not None and price is not None:
            result[code] = price
    if expected is not None and not result:
        raise ValueError(f"TWSE price CSV has no common-share rows for {expected}")
    return result


def parse_tpex_prices(payload: Sequence[Mapping[str, Any]], *, requested_date: str | None = None) -> dict[str, float]:
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise ValueError("TPEx price payload must be a list")
    expected = normalize_market_date(requested_date) if requested_date else None
    result: dict[str, float] = {}
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        if expected is not None and normalize_market_date(row.get("Date")) != expected:
            continue
        code = _code(row.get("SecuritiesCompanyCode", row.get("Code")))
        price = _price(row.get("Close", row.get("ClosingPrice")))
        if code is not None and price is not None:
            result[code] = price
    if expected is not None and not result:
        raise ValueError(f"TPEx price payload has no common-share rows for {expected}")
    return result


def regression_z(prices: Sequence[float], *, window: int = 882, min_history: int = 200) -> float | None:
    """Return raw-close OLS residual Z used by the former stock screener."""
    if len(prices) < min_history:
        return None
    values: list[float] = []
    for value in prices[-window:]:
        number = _price(value)
        if number is None:
            return None
        values.append(number)
    n = len(values)
    if n < min_history:
        return None
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    denominator = sum((index - mean_x) ** 2 for index in range(n))
    if denominator <= 0:
        return None
    slope = sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values)) / denominator
    intercept = mean_y - slope * mean_x
    residuals = [value - (slope * index + intercept) for index, value in enumerate(values)]
    sigma = math.sqrt(sum(value * value for value in residuals) / n)
    if sigma <= 0 or not math.isfinite(sigma):
        return None
    result = (values[-1] - (slope * (n - 1) + intercept)) / sigma
    return round(result, 2) if math.isfinite(result) else None
