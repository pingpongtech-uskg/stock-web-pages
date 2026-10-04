#!/usr/bin/env python3
"""Acquire and cache TDCC/MOPS ownership reference data for static releases."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import tempfile
from calendar import monthrange
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, HTTPRedirectHandler
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.ownership_inputs import DIRECTOR_SCOPE, normalize_director_rows, normalize_tdcc_rows, merge_ownership_rows
from pipeline.source_receipts import safe_directory

OWNERSHIP_SNAPSHOT_VERSION = "ownership-snapshot-v1"
TDCC_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
MOPS_URL = "https://mops.twse.com.tw/mops/api/stapap1"
TWSE_OPENAPI_BASE = "https://openapi.twse.com.tw/v1"
DIRECTOR_ENDPOINTS = ("t187ap11_L", "t187ap11_P")
ISSUED_SHARES_ENDPOINTS = ("t187ap03_L", "t187ap03_P")
TDCC_HISTORY_URL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urlopen(request, *, timeout):
    # Redirects otherwise issue extra HTTP attempts outside the shared budget.
    from urllib.request import build_opener
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


class OwnershipLimit(RuntimeError):
    """A bounded reference acquisition stopped; never fabricate missing rows."""


class OwnershipBudget:
    def __init__(self, *, max_runtime_seconds=180, max_requests=40, max_history_requests=20):
        if (type(max_runtime_seconds) not in (int, float) or not 0 < max_runtime_seconds <= 360
                or type(max_requests) is not int or not 1 <= max_requests <= 100
                or type(max_history_requests) is not int or not 0 <= max_history_requests <= max_requests):
            raise ValueError("invalid ownership acquisition limits")
        self.deadline = time.monotonic() + max_runtime_seconds
        self.max_runtime_seconds, self.max_requests, self.max_history_requests = max_runtime_seconds, max_requests, max_history_requests
        self.requests, self.history_requests = 0, 0

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise OwnershipLimit("runtime_limit")
        return remaining

    def check(self):
        remaining = self.remaining()
        if self.requests >= self.max_requests:
            raise OwnershipLimit("request_limit")
        return remaining

    def consume(self, timeout=20, *, historical=False):
        remaining = self.check()
        if historical and self.history_requests >= self.max_history_requests:
            raise OwnershipLimit("history_request_limit")
        self.requests += 1
        self.history_requests += int(historical)
        return min(timeout, remaining)


def _cutoff(as_of):
    if as_of is None:
        return None
    if not isinstance(as_of, str):
        raise ValueError("invalid ownership cutoff")
    parsed = date.fromisoformat(as_of + "-01" if len(as_of) == 7 else as_of)
    if parsed.isoformat()[:len(as_of)] != as_of or len(as_of) not in (7, 10):
        raise ValueError("invalid ownership cutoff")
    return as_of


def _before_cutoff(rows, cutoff):
    if cutoff and len(cutoff) == 7:
        year, month = map(int, cutoff.split("-"))
        cutoff = f"{cutoff}-{monthrange(year, month)[1]:02d}"
    return [row for row in rows if isinstance(row, dict) and (cutoff is None or
            (str(row.get("asOf") or row.get("period") or "") <= cutoff and
             all(str(row[field]) <= cutoff for field in ("publishedAt", "availableAt") if row.get(field))))]


def _read_body(response, budget=None):
    """Bound size and streaming duration, without accepting a truncated response."""
    limit = 16 * 1024 * 1024
    chunks, size = [], 0
    read = getattr(response, "read1", response.read)
    while True:
        if budget:
            remaining = budget.remaining()
            socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
            if socket is not None:
                socket.settimeout(min(20, remaining))
        chunk = read(min(64 * 1024, limit + 1 - size))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            raise ValueError("ownership response exceeds size limit")


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
        # TDCC's HTML band column is a display label.  Some issuers omit the
        # adjustment row, so `合計` is sequence 16 rather than 17.  Normalize
        # semantic labels to the stable CSV class IDs.
        label = values[band_i]
        if "合" in label:
            band = "17"
        elif "差異" in label:
            band = "16"
        else:
            band = sequence
        result.append({"資料日期": as_of, "證券代號": code, "持股分級": band, "人數": values[count_i], "股數": values[shares_i], "占集保庫存數比例%": values[pct_i]})
    return result

def fetch_tdcc_historical(code: str, months: list[str], *, timeout: float = 20.0, as_of=None,
                          budget=None, on_rows=None) -> list[dict[str, Any]]:
    """Select the last official available date; GET/token and POST per month."""
    from http.cookiejar import CookieJar
    from urllib.request import build_opener, HTTPCookieProcessor
    opener = build_opener(HTTPCookieProcessor(CookieJar()), _NoRedirect())
    cutoff = _cutoff(as_of)
    budget = budget or OwnershipBudget()
    result = []
    for month in sorted(set(months)):
        if cutoff and month > cutoff[:7]:
            continue
        with opener.open(Request(TDCC_HISTORY_URL),timeout=budget.consume(timeout,historical=True)) as response:
            page = _read_body(response,budget).decode("utf-8","replace")
        available = [value for value in parse_tdcc_available_dates(page) if value[:7]==month
                     and (not cutoff or value<=cutoff if len(cutoff or "")==10 else True)]
        if not available:
            continue
        selected = max(available)
        token_match = re.search(r'name=["\']SYNCHRONIZER_TOKEN["\'][^>]*value=["\']([^"\']+)',page,re.I)
        uri_match = re.search(r'name=["\']SYNCHRONIZER_URI["\'][^>]*value=["\']([^"\']+)',page,re.I)
        if not token_match:
            raise ValueError("TDCC session token absent")
        form = {"SYNCHRONIZER_TOKEN":token_match[1],"SYNCHRONIZER_URI":uri_match[1] if uri_match else "/portal/zh/smWeb/qryStock",
                "method":"submit","firDate":selected.replace("-",""),"scaDate":selected.replace("-",""),
                "sqlMethod":"StockNo","stockNo":code,"stockName":""}
        request = Request(TDCC_HISTORY_URL,data=urlencode(form).encode(),headers={"Content-Type":"application/x-www-form-urlencoded"})
        with opener.open(request,timeout=budget.consume(timeout,historical=True)) as response:
            document = _read_body(response,budget).decode("utf-8","replace")
        from scripts.update_ownership_checkpoint import tdcc_reported_date
        if tdcc_reported_date(document)!=selected:
            raise ValueError("TDCC official report date mismatch")
        rows = normalize_tdcc_rows(parse_tdcc_history_html(document,code=code,as_of=selected),
                                   retrieved_at=datetime.now(timezone.utc).isoformat(),source="TDCC",dataset="history")
        result.extend(rows)
        if rows and on_rows:
            on_rows(rows)
    return merge_ownership_rows(result)


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
            name = raw.get("name") or raw.get("姓名")
        elif isinstance(raw, list):
            title = raw[0] if len(raw) > 0 else None
            holding = raw[3] if len(raw) > 3 else None
            name = raw[1] if len(raw) > 1 else None
        else:
            continue
        if str(title or "").strip() not in DIRECTOR_SCOPE:
            continue
        rows.append({"資料年月": period, "公司代號": code, "職稱": title,
                     "目前持股": holding, "姓名": name, "已發行普通股數": denominator})
    result = normalize_director_rows(rows, retrieved_at=retrieved_at, source="MOPS", dataset="stapap1")
    aggregate = total.get("allDirectorSupervisor") if isinstance(total, dict) else None
    official = _number(aggregate[0] if isinstance(aggregate, list) and aggregate else aggregate)
    return [{**row, "officialDirectorSupervisorShares": official,
             "directorTotalMatches": official == row.get("directorSupervisorShares") if official is not None else None}
            for row in result]


def parse_twse_issued_shares(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Map the official company-basic snapshot to issued common shares."""
    result: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("公司代號") or row.get("code") or "").strip()
        shares = _number(
            row.get("已發行普通股數或TDR原股發行股數")
            or row.get("已發行普通股數")
            or row.get("issuedCommonShares")
        )
        if code and shares is not None and shares > 0:
            result[code] = shares
    return result


def parse_twse_director_rows(
    rows: list[dict[str, Any]],
    *,
    issued_shares_by_code: dict[str, float],
    dataset: str,
    retrieved_at: str | None = None,
) -> list[dict[str, Any]]:
    """Normalize holdings without joining an undated current denominator."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("公司代號") or row.get("code") or "").strip()
        normalized.append({
            "資料年月": row.get("資料年月") or row.get("period"),
            "公司代號": code,
            "職稱": row.get("職稱") or row.get("title"),
            "目前持股": row.get("目前持股") or row.get("holding"),
            "已發行普通股數": None,
            "姓名": row.get("姓名") or row.get("name"),
        })
    return normalize_director_rows(
        normalized,
        retrieved_at=retrieved_at,
        source="TWSE OpenAPI",
        dataset=dataset,
    )


def _request(url: str, *, data: bytes | None = None, timeout: float = 20.0, retries: int = 2, budget=None) -> bytes:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, data=data, headers={"User-Agent": "stock-release-ownership/1.0", "Content-Type": "application/json"})
            with urlopen(request, timeout=budget.consume(timeout) if budget else timeout) as response:
                return _read_body(response, budget)
        except OwnershipLimit:
            raise
        except Exception as exc:  # network sources are explicitly best-effort
            last = exc
            if attempt < retries:
                delay = 0.5 * (attempt + 1)
                if budget:
                    delay = min(delay, budget.check())
                time.sleep(delay)
    raise RuntimeError(f"ownership source unavailable: {last}")


def fetch_twse_director_rows(codes: list[str], *, retrieved_at: str | None = None, budget=None, on_error=None) -> list[dict[str, Any]]:
    """Fetch official director holdings and same-snapshot issued shares."""
    requested = {str(code).strip() for code in codes if str(code).strip()}
    def payload_for(endpoint):
        try:
            return json.loads(_request(f"{TWSE_OPENAPI_BASE}/opendata/{endpoint}", budget=budget).decode("utf-8"))
        except Exception as exc:
            if on_error is None:
                raise
            on_error("TWSE:" + endpoint, exc)
            return []
    issued_rows: list[dict[str, Any]] = []
    for endpoint in ISSUED_SHARES_ENDPOINTS:
        payload = payload_for(endpoint)
        if isinstance(payload, list):
            issued_rows.extend(row for row in payload if isinstance(row, dict))
    issued = parse_twse_issued_shares(issued_rows)
    result: list[dict[str, Any]] = []
    for endpoint in DIRECTOR_ENDPOINTS:
        payload = payload_for(endpoint)
        rows = [row for row in payload if isinstance(row, dict) and str(row.get("公司代號") or "").strip() in requested] if isinstance(payload, list) else []
        result.extend(parse_twse_director_rows(rows, issued_shares_by_code=issued, dataset=endpoint, retrieved_at=retrieved_at))
    return merge_ownership_rows(result)


def fetch_tdcc(*, retrieved_at: str | None = None, budget=None) -> list[dict[str, Any]]:
    return parse_tdcc_csv(_request(TDCC_URL, budget=budget).decode("utf-8-sig", errors="replace"), retrieved_at=retrieved_at)


def fetch_mops(code: str, year: str, month: str, *, retrieved_at: str | None = None) -> list[dict[str, Any]]:
    payload = json.dumps({"companyId": code, "dataType": "2", "year": year, "month": str(int(month))}).encode()
    raw = json.loads(_request(MOPS_URL, data=payload).decode("utf-8"))
    roc_year = int(year) + 1911
    return parse_mops_payload(raw, code=code, period=f"{roc_year:04d}-{int(month):02d}", retrieved_at=retrieved_at)


def shift_month(period: str, offset: int) -> str:
    year, month = (int(part) for part in period.split("-"))
    absolute = year * 12 + month - 1 + offset
    return f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"


def completed_months(verified_market_date: str) -> list[str]:
    """The three finished calendar months preceding the verified market date."""
    parsed = date.fromisoformat(verified_market_date)
    return [shift_month(parsed.strftime("%Y-%m"), offset) for offset in (-3, -2, -1)]


class _DatesParser(__import__("html.parser", fromlist=["HTMLParser"]).HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_dates = False
        self.dates = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "select":
            self.in_dates = values.get("name") == "scaDate"
        if tag == "option" and self.in_dates and re.fullmatch(r"\d{8}", values.get("value", "")):
            raw = values["value"]
            try:
                self.dates.append(date(int(raw[:4]), int(raw[4:6]), int(raw[6:])).isoformat())
            except ValueError:
                pass

    def handle_endtag(self, tag):
        if tag == "select":
            self.in_dates = False


def parse_tdcc_available_dates(document: str) -> list[str]:
    parser = _DatesParser()
    parser.feed(document)
    return sorted(set(parser.dates))


def fetch_ownership_rows(codes: list[str], *, as_of: str | None = None, budget=None,
                         previous_rows=(), on_checkpoint=None, on_error=None) -> list[dict[str, Any]]:
    """Fetch three TDCC months plus MOPS comparison months.

    TDCC's public CSV contains the latest week only.  Missing target months
    are filled through the official session query; a failed month remains
    absent and therefore evaluates to ``unknown`` rather than a fake zero.
    """
    requested = list(dict.fromkeys(str(code).strip() for code in codes if str(code).strip()))
    as_of = _cutoff(as_of)
    budget = budget or OwnershipBudget()
    retrieved = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    current, directors, historical = [], [], []
    def error(source, exc):
        if on_error:
            on_error({"source": source, "category": str(exc) if isinstance(exc, OwnershipLimit) else type(exc).__name__})
    def checkpoint():
        if on_checkpoint:
            on_checkpoint(merge_ownership_rows(current, directors, historical))
    try:
        current = [row for row in fetch_tdcc(retrieved_at=retrieved, budget=budget) if str(row.get("code")) in requested]
        current = _before_cutoff(current, as_of)
    except Exception as exc:
        error("TDCC:1-5", exc)
    checkpoint()
    try:
        directors = _before_cutoff(fetch_twse_director_rows(requested, retrieved_at=retrieved, budget=budget, on_error=error), as_of)
    except Exception as exc:
        error("TWSE:directors", exc)
    checkpoint()
    periods = {str(row.get("period")) for row in current if row.get("period")}
    anchor = str(as_of or max(periods, default=datetime.now(timezone.utc).strftime("%Y-%m")))[:7]
    current = [row for row in current if str(row.get("period") or "") <= anchor]
    target_months = completed_months(as_of if as_of and len(as_of)==10 else anchor+"-01")
    current_by_code: dict[str, set[str]] = {}
    for row in merge_ownership_rows(current, _before_cutoff(previous_rows, as_of)):
        if row.get("largeHolderPct") is None or row.get("shareholderCount") is None:
            continue
        current_by_code.setdefault(str(row.get("code")), set()).add(str(row.get("period")))
    def record_history(rows):
        nonlocal historical
        historical = merge_ownership_rows(historical, _before_cutoff(rows, as_of))
        checkpoint()
    for code in requested:
        missing = [month for month in target_months if month not in current_by_code.get(code, set())]
        if missing:
            try:
                if budget.max_history_requests == 0:
                    raise OwnershipLimit("history_request_limit")
                record_history(fetch_tdcc_historical(code, missing, as_of=as_of, budget=budget, on_rows=record_history))
            except OwnershipLimit as exc:
                error("TDCC:history:" + code, exc)
                break
            except Exception as exc:
                # Preserve whatever validated data exists; caller marks the
                # resulting cache stale and the evaluator stays fail-closed.
                error("TDCC:history:" + code, exc)
    return merge_ownership_rows(current, historical, directors)


def build_snapshot(previous: dict[str, Any] | None, fresh_rows: list[dict[str, Any]], *, requested_codes: list[str], retrieved_at: str | None = None, as_of=None) -> dict[str, Any]:
    """Keep a validated prior cache on source failure; never synthesize zeroes."""
    old_rows = previous.get("rows", []) if isinstance(previous, dict) else []
    ordered = sorted([*old_rows, *fresh_rows], key=lambda row: str(row.get("asOf") or row.get("period") or ""), reverse=True)
    merged = merge_ownership_rows(ordered)
    fresh_codes = {str(row.get("code")) for row in fresh_rows if isinstance(row, dict) and row.get("largeHolderPct") is not None and row.get("shareholderCount") is not None}
    periods_by_code: dict[str, set[str]] = {}
    for row in merged:
        code = str(row.get("code") or "")
        if row.get("largeHolderPct") is not None and row.get("shareholderCount") is not None:
            periods_by_code.setdefault(code, set()).add(str(row.get("period") or ""))
    target_months = set(completed_months(as_of if len(as_of)==10 else as_of+"-01")) if as_of else None
    complete = bool(requested_codes) and all(
        code in fresh_codes and (target_months <= periods_by_code.get(code, set()) if target_months else len(periods_by_code.get(code, set())) >= 3)
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


def _save_snapshot(path, snapshot):
    parent = safe_directory(path.parent)
    destination = parent / path.name
    if destination.is_symlink():
        raise ValueError("ownership output must not be a symlink")
    parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".ownership-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def acquire_snapshot(path: Path, codes: list[str], *, as_of: str | None = None, fetcher: Callable[[], list[dict[str, Any]]] | None = None,
                     max_runtime_seconds=180, max_requests=40, max_history_requests=20) -> dict[str, Any]:
    as_of = _cutoff(as_of)
    if not codes or any(not isinstance(code, str) or re.fullmatch(r"\d{4,6}[A-Z]?", code) is None for code in codes):
        raise ValueError("invalid ownership codes")
    budget = OwnershipBudget(max_runtime_seconds=max_runtime_seconds, max_requests=max_requests, max_history_requests=max_history_requests)
    retrieved = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    previous = load_snapshot(path)
    if previous:
        previous = {**previous, "rows": _before_cutoff(previous.get("rows", []), as_of)}
    errors, latest_rows = [], []
    def record_error(error):
        nonlocal errors
        errors = [*errors, error]
    def checkpoint(rows):
        nonlocal latest_rows
        eligible = [dict(row) for row in _before_cutoff(rows, as_of)]
        snapshot = build_snapshot(previous, eligible, requested_codes=codes, retrieved_at=retrieved, as_of=as_of)
        if errors:
            snapshot = {**snapshot, "status": "stale" if snapshot["rows"] else "unavailable"}
        snapshot = {**snapshot, "acquisition": {"asOf": as_of, "maxRuntimeSeconds": max_runtime_seconds,
                    "maxRequests": max_requests, "maxHistoryRequests": max_history_requests,
                    "requests": budget.requests, "historyRequests": budget.history_requests, "errors": errors}}
        _save_snapshot(path, snapshot)
        latest_rows = eligible
        return snapshot
    try:
        rows = fetcher() if fetcher is not None else fetch_ownership_rows(codes, as_of=as_of, budget=budget,
                previous_rows=(previous or {}).get("rows", []), on_checkpoint=checkpoint, on_error=record_error)
    except Exception as exc:
        record_error({"source": "ownership", "category": str(exc) if isinstance(exc, OwnershipLimit) else type(exc).__name__})
        rows = latest_rows
    return checkpoint(rows)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", required=True)
    parser.add_argument("--output", default=".cache/ownership_snapshot.json")
    parser.add_argument("--as-of", default=None, help="target month/date; defaults to latest TDCC month")
    parser.add_argument("--max-runtime-seconds", type=int, default=180)
    parser.add_argument("--max-requests", type=int, default=40)
    parser.add_argument("--max-history-requests", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        result = acquire_snapshot(Path(args.output), [code.strip() for code in args.codes.split(",") if code.strip()], as_of=args.as_of,
                max_runtime_seconds=args.max_runtime_seconds, max_requests=args.max_requests, max_history_requests=args.max_history_requests)
    except (ValueError, OSError) as exc:
        print("ownership_cache_invalid=" + type(exc).__name__, file=sys.stderr)
        return 1
    print(json.dumps({"status": result["status"], "rows": len(result["rows"]), "acquisition": result["acquisition"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
