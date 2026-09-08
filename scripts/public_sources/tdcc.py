"""Public TDCC JSON/CSV/query adapters."""
from __future__ import annotations

import csv
from datetime import date, datetime
import io
import json
import re
from http.cookiejar import CookieJar
from typing import Any
from urllib.request import HTTPCookieProcessor, build_opener

from scripts.probe_public_sources import request_text

TDCC_REQUIRED_JSON_FIELDS = ("股票代號", "集保股東戶數", "資料年月")
TDCC_REQUIRED_CSV_FIELDS = ("資料日期", "證券代號", "持股分級", "人數", "股數")


def _normalize_key(key: Any) -> str:
    return str(key).lstrip(chr(0xFEFF)).strip()


def normalize_tdcc_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize BOM-prefixed keys while retaining source values as strings."""
    if not isinstance(rows, list):
        raise ValueError("TDCC payload rows must be a list")
    return [{_normalize_key(key): value for key, value in row.items()} for row in rows if isinstance(row, dict)]


def parse_tdcc_json(text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise ValueError("TDCC JSON parse error") from exc
    if not isinstance(payload, list):
        raise ValueError("TDCC JSON payload must be a list")
    return normalize_tdcc_rows(payload)


def parse_dispersion_csv(text: str) -> list[dict[str, str]]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("TDCC CSV is empty")
    reader = csv.DictReader(io.StringIO(text))
    fields = [_normalize_key(value) for value in (reader.fieldnames or [])]
    missing = [field for field in TDCC_REQUIRED_CSV_FIELDS if field not in fields]
    if missing:
        raise ValueError(f"TDCC CSV missing fields: {', '.join(missing)}")
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {_normalize_key(key): (value or "") for key, value in raw.items() if key is not None}
        rows.append(row)
    if not rows:
        raise ValueError("TDCC CSV has no data rows")
    return rows


def _parse_date(value: Any) -> date:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return datetime.strptime(text, "%Y%m%d").date()
    if re.fullmatch(r"\d{5}", text):
        return date(1911 + int(text[:3]), int(text[3:]), 1)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    raise ValueError(f"invalid TDCC date: {value!r}")


def _row_date(row: dict[str, Any]) -> date:
    for key in ("資料日期", "snapshot_date", "date", "資料年月"):
        if key in row and str(row[key]).strip():
            return _parse_date(row[key])
    raise ValueError("TDCC row has no date")


def select_month_end_rows(
    rows: list[dict[str, Any]],
    code: str,
    *,
    code_field: str | None = None,
) -> list[dict[str, Any]]:
    """Select the latest available weekly row for each month, ascending."""
    if not re.fullmatch(r"\d{4,6}", str(code)):
        raise ValueError("code must be 4-6 ASCII digits")
    normalized = normalize_tdcc_rows(rows)
    selected: dict[str, tuple[date, dict[str, Any]]] = {}
    seen_dates: set[date] = set()
    for row in normalized:
        field = code_field or ("證券代號" if "證券代號" in row else "股票代號")
        if str(row.get(field, "")).strip() != str(code):
            continue
        current_date = _row_date(row)
        if current_date in seen_dates:
            raise ValueError(f"duplicate TDCC row for {code} on {current_date.isoformat()}")
        seen_dates.add(current_date)
        month = current_date.strftime("%Y-%m")
        previous = selected.get(month)
        if previous is None or current_date > previous[0]:
            selected[month] = (current_date, row)
    return [selected[key][1] for key in sorted(selected)]


def build_query_form(token: str, date_value: str, code: str) -> dict[str, str]:
    """Build the TDCC query POST form; caller must keep token in memory only."""
    if not isinstance(token, str) or not token:
        raise ValueError("TDCC synchronizer token is required in memory")
    _parse_date(date_value)
    if not re.fullmatch(r"\d{4,6}", str(code)):
        raise ValueError("code must be 4-6 ASCII digits")
    return {
        "SYNCHRONIZER_TOKEN": token,
        "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
        "method": "submit",
        "firDate": date_value,
        "scaDate": date_value,
        "sqlMethod": "StockNo",
        "stockNo": code,
        "stockName": "",
    }


def extract_query_dates(html_text: str) -> list[str]:
    dates = re.findall(r'<option\s+value="(\d{8})"', html_text or "", re.I)
    return list(dict.fromkeys(dates))


def fetch_query_once(
    url: str,
    date_value: str,
    code: str,
    allowed_hosts: set[str],
    timeout: int,
) -> dict[str, Any]:
    """Fetch one TDCC date with a fresh in-memory session.

    TDCC's synchronizer/session state can make a reused token return an empty
    shell for later dates.  Refreshing the form for every date is deliberate.
    The returned object omits the token and cookie jar.
    """
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    initial = request_text(url, allowed_hosts=allowed_hosts, timeout=timeout, opener=opener)
    token_match = re.search(r'name="SYNCHRONIZER_TOKEN"\s+value="([^"]+)"', initial.body, re.I)
    if initial.error_type or initial.status_code != 200 or not token_match:
        raise ValueError("TDCC query form/token unavailable")
    queried = request_text(
        url,
        allowed_hosts=allowed_hosts,
        method="POST",
        form=build_query_form(token_match.group(1), date_value, code),
        timeout=timeout,
        opener=opener,
    )
    return {
        "initial": initial,
        "queried": queried,
        "available_dates": extract_query_dates(initial.body),
    }




def parse_query_result(html_text: str, code: str) -> dict[str, Any]:
    text = html_text or ""
    return {
        "target_code": code,
        "target_present": str(code) in text,
        "table_marker_present": "持股/單位數分級" in text,
        "status": "PASS" if str(code) in text and "持股/單位數分級" in text else "FAIL",
    }
