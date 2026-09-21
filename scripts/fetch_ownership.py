#!/usr/bin/env python3
"""Acquire and cache TDCC/MOPS ownership reference data for static releases."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import time
from calendar import monthrange
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.ownership_inputs import normalize_director_rows, normalize_tdcc_rows, merge_ownership_rows

OWNERSHIP_SNAPSHOT_VERSION = "ownership-snapshot-v1"
TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
MOPS_URL = "https://mops.twse.com.tw/mops/api/stapap1"
TDCC_HISTORY_URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
DIRECTOR_SCOPE = ("董事長本人", "董事本人", "獨立董事本人", "監察人本人")


class _TableParser(__import__("html.parser", fromlist=["HTMLParser"]).HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr": self._row = []
        elif tag in {"td", "th"} and self._row is not None: self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None: self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split())); self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row: self.rows.append(self._row)
            self._row = None


def parse_tdcc_history_html(document: str, *, code: str, as_of: str) -> list[dict[str, Any]]:
    parser = _TableParser(); parser.feed(document)
    header = next((row for row in parser.rows if "序" in row and "持股/單位數分級" in row and "人數" in row and any("占集保" in cell for cell in row)), None)
    if not header:
        return []
    sequence_i = header.index("序")
    band_i, count_i, shares_i = header.index("持股/單位數分級"), header.index("人數"), header.index("股數/單位數")
    pct_i = next(i for i, cell in enumerate(header) if "占集保" in cell)
    result = []
    for values in parser.rows[parser.rows.index(header) + 1:]:
        if max(band_i, count_i, shares_i, pct_i) >= len(values):
            continue
        sequence = values[sequence_i].strip()
        if not sequence.isdigit() or not 1 <= int(sequence) <= 17:
            continue
        # TDCC's HTML band column is a display label.  The stable class ID is
        # the first `序` column, which is what the CSV normalizer consumes.
        result.append({"資料日期": as_of, "證券代號": code, "持股分級": sequence, "人數": values[count_i], "股數": values[shares_i], "占集保庫存數比例%": values[pct_i]})
    return result

def fetch_tdcc_historical(code: str, months: list[str], *, timeout: float = 20.0) -> list[dict[str, Any]]:
    """Query one latest available TDCC week per requested month with token/cookie."""
    from http.cookiejar import CookieJar
    from urllib.request import build_opener, HTTPCookieProcessor
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    rows: list[dict[str, Any]] = []
    for month in sorted(set(months)):
        year, mon = (int(part) for part in month.split("-"))
        month_rows: list[dict[str, Any]] = []
        for day in range(monthrange(year, mon)[1], max(0, monthrange(year, mon)[1] - 8), -1):
            date_value = f"{year:04d}{mon:02d}{day:02d}"
            # The TDCC synchronizer token rotates after a POST.  Fetch a new
            # page/token for every date probe instead of reusing a consumed
            # token and misreading later valid dates as empty results.
            page = opener.open(Request(TDCC_HISTORY_URL, headers={"User-Agent": "stock-release-ownership/1.0"}), timeout=timeout).read().decode("utf-8", "replace")
            token_match = re.search(r'name=[\"\']SYNCHRONIZER_TOKEN[\"\'][^>]*value=[\"\']([^\"\']+)', page, re.I)
            uri_match = re.search(r'name=[\"\']SYNCHRONIZER_URI[\"\'][^>]*value=[\"\']([^\"\']+)', page, re.I)
            token = token_match.group(1) if token_match else ""
            uri = uri_match.group(1) if uri_match else "/portal/zh/smWeb/qryStock"
            form = {"SYNCHRONIZER_TOKEN": token, "SYNCHRONIZER_URI": uri, "method": "submit", "firDate": date_value, "scaDate": date_value, "sqlMethod": "StockNo", "stockNo": code, "stockName": ""}
            body = urlencode(form).encode()
            document = opener.open(Request(TDCC_HISTORY_URL, data=body, headers={"User-Agent": "stock-release-ownership/1.0", "Content-Type": "application/x-www-form-urlencoded"}), timeout=timeout).read().decode("utf-8", "replace")
            month_rows = parse_tdcc_history_html(document, code=code, as_of=f"{year:04d}-{mon:02d}-{day:02d}")
            if month_rows:
                break
        rows.extend(month_rows)
    return normalize_tdcc_rows(rows, source="TDCC", dataset="history")


def _number(value: Any) -> float | None:
    try:
        result = float(str(value or "").replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def parse_tdcc_csv(document: str, *, retrieved_at: str | None = None) -> list[dict[str, Any]]:
    """Parse the public 1-5 CSV and normalize class 15/17 only."""
    rows = list(csv.DictReader(io.StringIO(document.lstrip("\ufeff"))))
    return normalize_tdcc_rows(rows, retrieved_at=retrieved_at, source="TDCC", dataset="1-5")


def parse_mops_payload(payload: dict[str, Any], *, code: str, period: str, retrieved_at: str | None = None) -> list[dict[str, Any]]:
    if isinstance(payload.get("result"), dict):
        payload = payload["result"]
    parent = payload.get("parentCompany") if isinstance(payload, dict) else {}
    data = parent.get("data", []) if isinstance(parent, dict) else []
    total = parent.get("total", {}) if isinstance(parent, dict) else {}
    denominator = None
    # allDirectorSupervisor is an aggregate holding total, not issued common shares.
    # It is intentionally not used as a percentage denominator.
    rows = []
    for raw in data if isinstance(data, list) else []:
        if isinstance(raw, dict):
            title = raw.get("title") or raw.get("職稱")
            holding = raw.get("current holding") or raw.get("目前持股")
        elif isinstance(raw, list):
            title = raw[0] if len(raw) > 0 else None
            holding = raw[3] if len(raw) > 3 else None
        else:
            continue
        if str(title or "").strip() not in DIRECTOR_SCOPE:
            continue
        rows.append({"資料年月": period, "公司代號": code, "職稱": title,
                     "目前持股": holding, "已發行普通股數": denominator})
    return normalize_director_rows(rows, retrieved_at=retrieved_at, source="MOPS", dataset="stapap1")


def _request(url: str, *, data: bytes | None = None, timeout: float = 20.0, retries: int = 2) -> bytes:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, data=data, headers={"User-Agent": "stock-release-ownership/1.0", "Content-Type": "application/json"})
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # network sources are explicitly best-effort
            last = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"ownership source unavailable: {last}")


def fetch_tdcc(*, retrieved_at: str | None = None) -> list[dict[str, Any]]:
    return parse_tdcc_csv(_request(TDCC_URL).decode("utf-8-sig", errors="replace"), retrieved_at=retrieved_at)


def fetch_mops(code: str, year: str, month: str, *, retrieved_at: str | None = None) -> list[dict[str, Any]]:
    payload = json.dumps({"companyId": code, "dataType": "2", "year": year, "month": str(int(month))}).encode()
    raw = json.loads(_request(MOPS_URL, data=payload).decode("utf-8"))
    roc_year = int(year) + 1911
    return parse_mops_payload(raw, code=code, period=f"{roc_year:04d}-{int(month):02d}", retrieved_at=retrieved_at)


def shift_month(period: str, offset: int) -> str:
    year, month = (int(part) for part in period.split("-"))
    absolute = year * 12 + month - 1 + offset
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def fetch_ownership_rows(codes: list[str], *, as_of: str | None = None) -> list[dict[str, Any]]:
    """Fetch three TDCC months plus MOPS comparison months.

    TDCC's public CSV contains the latest week only.  Missing target months
    are filled through the official session query; a failed month remains
    absent and therefore evaluates to ``unknown`` rather than a fake zero.
    """
    requested = list(dict.fromkeys(str(code).strip() for code in codes if str(code).strip()))
    retrieved = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    current = [row for row in fetch_tdcc(retrieved_at=retrieved) if str(row.get("code")) in requested]
    periods = {str(row.get("period")) for row in current if row.get("period")}
    anchor = str(as_of or max(periods, default=datetime.now(timezone.utc).strftime("%Y-%m")))[:7]
    current = [row for row in current if str(row.get("period") or "") <= anchor]
    target_months = [shift_month(anchor, offset) for offset in (-2, -1, 0)]
    current_by_code: dict[str, set[str]] = {}
    for row in current:
        current_by_code.setdefault(str(row.get("code")), set()).add(str(row.get("period")))
    historical: list[dict[str, Any]] = []
    for code in requested:
        missing = [month for month in target_months if month not in current_by_code.get(code, set())]
        if missing:
            try:
                historical.extend(fetch_tdcc_historical(code, missing))
            except Exception:
                # Preserve whatever validated data exists; caller marks the
                # resulting cache stale and the evaluator stays fail-closed.
                continue

    directors: list[dict[str, Any]] = []
    for code in requested:
        latest_director_period: str | None = None
        for candidate in (anchor, shift_month(anchor, -1), shift_month(anchor, -2)):
            year, month = candidate.split("-")
            try:
                latest_rows = fetch_mops(code, str(int(year) - 1911), month, retrieved_at=retrieved)
            except Exception:
                continue
            if latest_rows:
                directors.extend(latest_rows)
                latest_director_period = candidate
                break
            time.sleep(0.05)
        if latest_director_period:
            prior_period = shift_month(latest_director_period, -12)
            year, month = prior_period.split("-")
            try:
                directors.extend(fetch_mops(code, str(int(year) - 1911), month, retrieved_at=retrieved))
            except Exception:
                pass
    return merge_ownership_rows(current, historical, directors)


def build_snapshot(previous: dict[str, Any] | None, fresh_rows: list[dict[str, Any]], *, requested_codes: list[str], retrieved_at: str | None = None) -> dict[str, Any]:
    """Keep a validated prior cache on source failure; never synthesize zeroes."""
    old_rows = previous.get("rows", []) if isinstance(previous, dict) else []
    merged = merge_ownership_rows(old_rows, fresh_rows)
    fresh_codes = {str(row.get("code")) for row in fresh_rows if isinstance(row, dict)}
    periods_by_code: dict[str, set[str]] = {}
    for row in merged:
        code = str(row.get("code") or "")
        if row.get("largeHolderPct") is not None and row.get("shareholderCount") is not None:
            periods_by_code.setdefault(code, set()).add(str(row.get("period") or ""))
    complete = bool(requested_codes) and all(
        code in fresh_codes and len(periods_by_code.get(code, set())) >= 3
        for code in requested_codes
    )
    status = "current" if complete else "stale" if merged else "unavailable"
    refs = []
    for row in merged:
        refs.extend(row.get("sourceRefs") or [])
    return {"schemaVersion": OWNERSHIP_SNAPSHOT_VERSION, "status": status, "retrievedAt": retrieved_at,
            "rows": merged, "sourceRefs": list(dict.fromkeys(refs)),
            "requestedCodes": list(dict.fromkeys(requested_codes))}


def load_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) and value.get("schemaVersion") == OWNERSHIP_SNAPSHOT_VERSION else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def acquire_snapshot(path: Path, codes: list[str], *, as_of: str | None = None, fetcher: Callable[[], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    retrieved = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    previous = load_snapshot(path)
    try:
        rows = fetcher() if fetcher is not None else fetch_ownership_rows(codes, as_of=as_of)
    except Exception:
        rows = []
    snapshot = build_snapshot(previous, rows, requested_codes=codes, retrieved_at=retrieved)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + ".tmp")
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
    return snapshot


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", required=True)
    parser.add_argument("--output", default=".cache/ownership_snapshot.json")
    parser.add_argument("--as-of", default=None, help="target month/date; defaults to latest TDCC month")
    args = parser.parse_args()
    result = acquire_snapshot(Path(args.output), [code.strip() for code in args.codes.split(",") if code.strip()], as_of=args.as_of)
    print(json.dumps({"status": result["status"], "rows": len(result["rows"])}, ensure_ascii=False))
