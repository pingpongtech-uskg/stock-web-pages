"""Official daily investment-trust flow collection and ranking.

TWSE reports shares. TPEx reports lots. This module normalizes both to shares
before combining the two markets, then exposes adjacent ten-session windows so
"new entry" means a real rank transition rather than a subset re-rank.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any
from zoneinfo import ZoneInfo

from pipeline.release_contract import is_common_stock_code

TWSE_ENDPOINT = "https://www.twse.com.tw/rwd/zh/fund/TWT44U"
TPEX_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/insti/sitcStat"
TWSE_SOURCE = "TWSE:TWT44U"
TPEX_SOURCE = "TPEx:insti/sitcStat"
USER_AGENT = "taiwan-stock-screener/official-institutional-v1"
TAIPEI = ZoneInfo("Asia/Taipei")
MAX_SOURCE_NUMBER_CHARS = 64


class OfficialInstitutionalError(RuntimeError):
    """Raised when a complete cross-market daily report is unavailable."""


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\u3000", " ").strip()


def _clean_code(value: Any) -> str:
    return re.sub(r"\s+", "", _clean_text(value)).upper()


def _number(value: Any, *, multiplier: int = 1) -> int | None:
    """Parse exact source quantities and convert only whole shares."""

    if isinstance(value, bool):
        raise ValueError("boolean is not a source quantity")
    text = str(value if value is not None else "").replace("\u3000", " ").strip()
    if not text or text in {"-", "--", "—", "…", "N/A", "無"}:
        return None
    if len(text) > MAX_SOURCE_NUMBER_CHARS:
        raise ValueError("source quantity exceeds length limit")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
        if text.startswith(("+", "-")):
            raise ValueError("accounting negative quantity cannot include a sign")
    elif "(" in text or ")" in text:
        raise ValueError("malformed negative source quantity")
    if not re.fullmatch(r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)", text):
        raise ValueError("malformed source quantity")
    try:
        quantity = Decimal(text.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("malformed source quantity") from exc
    if not quantity.is_finite():
        raise ValueError("non-finite source quantity")
    if negative:
        quantity = quantity.copy_negate()
    coefficient_digits = len(text.replace(",", "").replace(".", "").lstrip("+-"))
    with localcontext() as context:
        context.prec = max(1, coefficient_digits + len(str(multiplier)) + 1)
        shares = quantity * multiplier
    if shares != shares.to_integral_value():
        raise ValueError("source quantity is not a whole share")
    return int(shares)


def _is_empty_row(row: list[Any]) -> bool:
    return not any(str(value).replace("\u3000", " ").strip() for value in row if value is not None)


def _parse_amounts(row: list[Any], indexes: tuple[int, int, int], *, multiplier: int = 1) -> tuple[int | None, ...]:
    return tuple(_number(_row_value(row, index), multiplier=multiplier) for index in indexes)


def _field_index(fields: list[Any], *names: str) -> int:
    cleaned = [_clean_text(field) for field in fields]
    for name in names:
        if name in cleaned:
            return cleaned.index(name)
    raise OfficialInstitutionalError(f"missing official field: {'/'.join(names)}")


def _row_value(row: list[Any], index: int) -> Any:
    return row[index] if 0 <= index < len(row) else None


def parse_twse_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse TWSE TWT44U JSON, retaining the report's share unit."""

    fields = payload.get("fields")
    rows = payload.get("data")
    if not isinstance(fields, list) or not isinstance(rows, list):
        raise OfficialInstitutionalError("TWSE payload has no tabular data")
    code_i = _field_index(fields, "證券代號")
    name_i = _field_index(fields, "證券名稱")
    buy_i = _field_index(fields, "買進股數")
    sell_i = _field_index(fields, "賣出股數")
    net_i = _field_index(fields, "買賣超股數")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            raise OfficialInstitutionalError("TWSE report contains a malformed row")
        code = _clean_code(_row_value(row, code_i))
        if not code:
            if _is_empty_row(row):
                continue
            raise OfficialInstitutionalError("TWSE report row has no identifiable security code")
        try:
            buy, sell, net = _parse_amounts(row, (buy_i, sell_i, net_i))
        except ValueError as exc:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TWSE common-stock row contains an invalid quantity") from exc
            continue
        if buy is None or sell is None or net is None:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TWSE common-stock row is missing a quantity")
            continue
        if buy < 0 or sell < 0 or buy - sell != net:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TWSE common-stock row has inconsistent quantities")
            continue
        result.append({
            "code": code,
            "name": _clean_text(_row_value(row, name_i)),
            "market": "TWSE",
            "buyShares": buy,
            "sellShares": sell,
            "netShares": net,
        })
    return result


def parse_tpex_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse TPEx daily report and convert its lot columns to shares."""

    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise OfficialInstitutionalError("TPEx payload has no tables")
    table = next(
        (
            item for item in tables
            if isinstance(item, dict)
            and isinstance(item.get("fields"), list)
            and any("買賣超" in _clean_text(field) for field in item["fields"])
        ),
        None,
    )
    if not isinstance(table, dict):
        raise OfficialInstitutionalError("TPEx payload has no institutional table")
    fields = table["fields"]
    rows = table.get("data")
    if not isinstance(rows, list):
        raise OfficialInstitutionalError("TPEx institutional table has no rows")
    code_i = _field_index(fields, "代號")
    name_i = _field_index(fields, "名稱")
    buy_i = _field_index(fields, "買進")
    sell_i = _field_index(fields, "賣出")
    net_i = _field_index(fields, "買賣超(張數)", "買賣超")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            raise OfficialInstitutionalError("TPEx report contains a malformed row")
        code = _clean_code(_row_value(row, code_i))
        if not code:
            if _is_empty_row(row):
                continue
            raise OfficialInstitutionalError("TPEx report row has no identifiable security code")
        try:
            buy_shares, sell_shares, net_shares = _parse_amounts(
                row, (buy_i, sell_i, net_i), multiplier=1000)
        except ValueError as exc:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TPEx common-stock row contains an invalid quantity") from exc
            continue
        if buy_shares is None or sell_shares is None or net_shares is None:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TPEx common-stock row is missing a quantity")
            continue
        if buy_shares < 0 or sell_shares < 0 or buy_shares - sell_shares != net_shares:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TPEx common-stock row has inconsistent quantities")
            continue
        result.append({
            "code": code,
            "name": _clean_text(_row_value(row, name_i)),
            "market": "TPEx",
            "buyShares": buy_shares,
            "sellShares": sell_shares,
            "netShares": net_shares,
        })
    return result


def _get_json(url: str, *, data: dict[str, str] | None = None) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(data or {}).encode() if data is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    request = urllib.request.Request(url, data=encoded, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise OfficialInstitutionalError(f"official report request failed: {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise OfficialInstitutionalError(f"official report is not an object: {url}")
    return payload


def fetch_twse_day(day: date) -> list[dict[str, Any]]:
    payload = _get_json(
        TWSE_ENDPOINT,
        data={"date": day.strftime("%Y%m%d"), "response": "json"},
    )
    if str(payload.get("date") or "") != day.strftime("%Y%m%d"):
        return []
    return parse_twse_payload(payload)


def fetch_tpex_day(day: date) -> list[dict[str, Any]]:
    payload = _get_json(
        TPEX_ENDPOINT,
        data={"type": "Daily", "date": day.strftime("%Y/%m/%d"), "searchType": "buy", "response": "json"},
    )
    if str(payload.get("date") or "") != day.strftime("%Y%m%d"):
        return []
    return parse_tpex_payload(payload)


def fetch_complete_day(day: date) -> list[dict[str, Any]]:
    """Fetch both markets; empty means a weekend/holiday, not zero flow."""

    twse = fetch_twse_day(day)
    tpex = fetch_tpex_day(day)
    if not twse or not tpex:
        return []
    return [*twse, *tpex]


def fetch_recent_complete_days(
    *,
    as_of: date | None = None,
    sessions: int = 11,
    lookback_days: int = 35,
) -> list[dict[str, Any]]:
    """Return newest-first complete cross-market sessions with row data."""

    if sessions < 1 or lookback_days < sessions:
        raise ValueError("invalid institutional session window")
    end = as_of or datetime.now(TAIPEI).date()
    result: list[dict[str, Any]] = []
    for offset in range(lookback_days):
        day = end - timedelta(days=offset)
        rows = fetch_complete_day(day)
        if rows:
            result.append({"date": day.isoformat(), "rows": rows})
            if len(result) >= sessions:
                break
    if len(result) < sessions:
        raise OfficialInstitutionalError(
            f"only {len(result)} complete market sessions found; need {sessions}"
        )
    return result


def aggregate_window(days: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Sum normalized share flows and rank positive net-buy rows."""

    aggregate: dict[str, dict[str, Any]] = {}
    for rows in days:
        for row in rows:
            code = _clean_code(row.get("code"))
            net = row.get("netShares")
            if not code or not is_common_stock_code(code) or not isinstance(net, (int, float)):
                continue
            current = aggregate.setdefault(
                code,
                {
                    "code": code,
                    "name": _clean_text(row.get("name")),
                    "market": _clean_text(row.get("market")),
                    "netShares": 0,
                },
            )
            current["netShares"] += int(net)
    positive = [row for row in aggregate.values() if row["netShares"] > 0]
    positive.sort(key=lambda row: (-int(row["netShares"]), str(row["code"])))
    for rank, row in enumerate(positive, start=1):
        row["rank"] = rank
    return positive


def rank_adjacent_windows(
    snapshots: list[dict[str, Any]],
    *,
    window: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rank current and previous rolling windows from newest-first snapshots."""

    if len(snapshots) < window + 1:
        raise ValueError(f"need at least {window + 1} snapshots")
    current = aggregate_window([snapshot["rows"] for snapshot in snapshots[:window]])
    previous = aggregate_window([snapshot["rows"] for snapshot in snapshots[1:window + 1]])
    return current, previous
