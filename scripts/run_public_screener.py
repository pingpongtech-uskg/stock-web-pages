#!/usr/bin/env python3
"""Official institutional-flow → public seven-category screener.

Flow:
  TWSE T86 + TPEx three-institution daily data
  -> local trust_all_cache.json
  -> signed ten-trading-day investment-trust net shares
  -> top-N share candidates
  -> official closing-price amount ranking
  -> optional yfinance historical price for the existing Z calculation
  -> transparent public category scores and site JSON

No StatementDog page/API/cookie/session is read.  No credential is read or
written.  Raw HTTP bodies stay in memory and are represented only by hashes in
normalized facts.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screener.institutional_sources import (
    TPEX_3INSTI_URL,
    TWSE_T86_URL,
    InstitutionalRow,
    merge_daily_rows,
    normalize_market_date,
    parse_tpex_3insti,
    parse_twse_t86,
    ten_day_rank,
)
from screener.market_sources import parse_tpex_prices, parse_twse_prices, regression_z
from screener.public_data_models import ScoreConfig, stable_hash
from screener.public_daily_pipeline import build_scored_entries, build_site_payload
from screener.public_market_facts import parse_company_master, parse_tpex_valuation, parse_twse_valuation

DEFAULT_ROOT = ROOT / "data" / "public_screener"
DEFAULT_CACHE = DEFAULT_ROOT / "trust_all_cache.json"
DEFAULT_META = DEFAULT_ROOT / "trust_cache_meta.json"
DEFAULT_REPORTS = DEFAULT_ROOT / "reports"
DEFAULT_SITE = ROOT / "src" / "data" / "public_screener.json"
ALLOWED_HOSTS = {"www.twse.com.tw", "openapi.twse.com.tw", "www.tpex.org.tw"}
USER_AGENT = "public-stock-screener/1.0"
MAX_BODY_BYTES = 12 * 1024 * 1024


class PublicScreenerError(RuntimeError):
    pass


def _request_body(url: str, *, max_bytes: int = MAX_BODY_BYTES, timeout: int = 60) -> bytes:
    host = urlparse(url).hostname
    if host not in ALLOWED_HOSTS:
        raise PublicScreenerError(f"blocked source host: {host}")
    last_error: Exception | None = None
    for attempt in range(3):
        response = None
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = urlopen(request, timeout=timeout)
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise PublicScreenerError(f"response exceeds body cap: {host}")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise PublicScreenerError(f"response exceeds body cap: {host}")
            return body
        except (http.client.IncompleteRead, http.client.HTTPException, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1 + attempt)
                continue
            raise PublicScreenerError(f"official response download failed after retries: {host}") from exc
        finally:
            if response is not None:
                response.close()
    raise PublicScreenerError(f"official response download failed: {host}") from last_error


def _json_get(url: str, *, timeout: int = 60) -> Any:
    body = _request_body(url, timeout=timeout)
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicScreenerError(f"JSON parse failed for {urlparse(url).hostname}") from exc


def _text_get(url: str, *, timeout: int = 60) -> str:
    body = _request_body(url, timeout=timeout)
    try:
        return body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PublicScreenerError(f"text decode failed for {urlparse(url).hostname}") from exc


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicScreenerError(f"cannot parse {path.name}: {type(exc).__name__}") from exc


def _previous_dates(as_of: date, lookback_calendar_days: int) -> list[date]:
    return [as_of - timedelta(days=offset) for offset in range(max(1, lookback_calendar_days))]


def _tpex_url(day: date) -> str:
    return TPEX_3INSTI_URL + "?" + urlencode({"l": "zh-tw", "se": "AL", "t": "D", "d": day.strftime("%Y/%m/%d")})


def _twse_url(day: date) -> str:
    return TWSE_T86_URL + "?" + urlencode({"response": "json", "date": day.strftime("%Y%m%d"), "selectType": "ALL"})


def _cache_dates(cache: Mapping[str, Any]) -> set[str]:
    dates: set[str] = set()
    for item in cache.values():
        if not isinstance(item, Mapping):
            continue
        for value in item.get("dates", []):
            try:
                dates.add(normalize_market_date(value))
            except ValueError:
                continue
    return dates


def update_institutional_cache(
    cache_path: Path,
    meta_path: Path,
    *,
    as_of: date,
    required_sessions: int = 10,
    lookback_calendar_days: int = 24,
    timeout: int = 60,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cache = _load_json(cache_path, {})
    if not isinstance(cache, dict):
        raise PublicScreenerError("trust cache root must be an object")
    meta = _load_json(meta_path, {"fetched_dates": {}, "source": "official_twse_t86_tpex_3insti"})
    if not isinstance(meta, dict):
        raise PublicScreenerError("trust cache meta root must be an object")
    fetched_dates = meta.setdefault("fetched_dates", {})
    known_dates = _cache_dates(cache)
    conflicts: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    successful_dates: set[str] = set(known_dates)
    for day in _previous_dates(as_of, lookback_calendar_days):
        iso_day = day.isoformat()
        # Existing cache can satisfy the initial history; current/new dates
        # still get one official refresh per date, recorded in meta.
        if iso_day in fetched_dates and iso_day in known_dates:
            continue
        day_rows: list[InstitutionalRow] = []
        statuses: dict[str, str] = {}
        for market, url, parser in (
            ("TWSE", _twse_url(day), parse_twse_t86),
            ("TPEx", _tpex_url(day), parse_tpex_3insti),
        ):
            try:
                payload = _json_get(url, timeout=timeout)
                rows = parser(payload, source_url=url, requested_date=iso_day)
                day_rows.extend(rows)
                statuses[market] = f"PASS:{len(rows)}"
            except (OSError, ValueError, PublicScreenerError) as exc:
                statuses[market] = f"ERROR:{type(exc).__name__}"
                errors.append({"date": iso_day, "market": market, "error": str(exc)[:240]})
        if day_rows:
            cache, day_conflicts = merge_daily_rows(cache, day_rows)
            conflicts.extend(day_conflicts)
            successful_dates.add(iso_day)
            known_dates.add(iso_day)
        fetched_dates[iso_day] = {"status": statuses, "row_count": len(day_rows)}
        if len(successful_dates) >= required_sessions:
            break
    if len(successful_dates) < required_sessions:
        raise PublicScreenerError(f"only {len(successful_dates)} official trading dates available; need {required_sessions}")
    meta["last_run_as_of"] = as_of.isoformat()
    meta["last_run_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["successful_date_count"] = len(successful_dates)
    meta["conflicts"] = conflicts
    meta["errors"] = errors
    meta["formula_version"] = "public-data-health-v1"
    _atomic_write_json(cache_path, cache)
    _atomic_write_json(meta_path, meta)
    return cache, meta


def _twse_price_date(csv_text: str) -> str:
    rows = list(__import__("csv").DictReader(io.StringIO(csv_text.lstrip("\ufeff"))))
    if not rows:
        raise PublicScreenerError("TWSE price CSV has no rows")
    return normalize_market_date(rows[0].get("日期"))


def fetch_current_market_data(*, timeout: int = 60) -> tuple[dict[str, float], dict[str, dict[str, Any]], str, dict[str, str]]:
    twse_price_url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=json"
    twse_valuation_url = "https://www.twse.com.tw/exchangeReport/BWIBBU_ALL?response=json"
    tpex_price_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    tpex_valuation_url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
    twse_price_text = _text_get(twse_price_url, timeout=timeout)
    twse_prices = parse_twse_prices(twse_price_text)
    twse_date = _twse_price_date(twse_price_text)
    tpex_price_payload = _json_get(tpex_price_url, timeout=timeout)
    tpex_prices = parse_tpex_prices(tpex_price_payload)
    price_map = {**twse_prices, **tpex_prices}
    twse_valuation = parse_twse_valuation(_json_get(twse_valuation_url, timeout=timeout), source_url=twse_valuation_url)
    tpex_valuation = parse_tpex_valuation(_json_get(tpex_valuation_url, timeout=timeout), source_url=tpex_valuation_url)
    valuations = {**twse_valuation, **tpex_valuation}
    source_urls = {"twse_price": twse_price_url, "tpex_price": tpex_price_url, "twse_valuation": twse_valuation_url, "tpex_valuation": tpex_valuation_url}
    return price_map, valuations, twse_date, source_urls


def fetch_company_masters(*, timeout: int = 60) -> dict[str, dict[str, Any]]:
    twse_url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    tpex_url = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
    twse = parse_company_master(_json_get(twse_url, timeout=timeout), market="TWSE")
    tpex = parse_company_master(_json_get(tpex_url, timeout=timeout), market="TPEx")
    return {**twse, **tpex}


def _load_price_history(path: Path) -> dict[str, list[float]]:
    payload = _load_json(path, {})
    if not isinstance(payload, dict):
        raise PublicScreenerError("price history cache root must be an object")
    result: dict[str, list[float]] = {}
    for code, item in payload.items():
        if isinstance(item, Mapping):
            values = item.get("close", [])
        else:
            values = item
        if not isinstance(values, list):
            continue
        cleaned = []
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number > 0:
                cleaned.append(number)
        if cleaned:
            result[str(code)] = cleaned
    return result


def _save_price_history(path: Path, histories: Mapping[str, Sequence[float]]) -> None:
    payload = {str(code): {"close": [round(float(value), 6) for value in values], "provider": "yfinance", "formula_version": "public-z-v1"} for code, values in histories.items()}
    _atomic_write_json(path, payload)


def _fetch_yfinance_history(code: str, market: str, *, timeout: int = 60) -> list[float] | None:
    try:
        import yfinance as yf
    except ImportError:
        return None
    suffix = ".TW" if market == "TWSE" else ".TWO"
    try:
        ticker = yf.Ticker(f"{code}{suffix}")
        frame = ticker.history(period="5y", auto_adjust=False, timeout=timeout)
        if frame is None or len(frame) < 200 or "Close" not in frame:
            return None
        values = []
        for value in frame["Close"].tolist():
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number > 0:
                values.append(number)
        return values if len(values) >= 200 else None
    except Exception:
        return None


def enrich_z(
    candidates: Sequence[Mapping[str, Any]],
    *,
    history_path: Path,
    timeout: int = 60,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    histories = _load_price_history(history_path)
    sources: dict[str, str] = {}
    enriched: list[dict[str, Any]] = []
    dirty = False
    for candidate in candidates:
        row = dict(candidate)
        code = str(row["code"])
        values = histories.get(code)
        if values is None:
            values = _fetch_yfinance_history(code, str(row.get("market", "TWSE")), timeout=timeout)
            if values is not None:
                histories[code] = values
                dirty = True
                sources[code] = "yfinance"
        else:
            sources[code] = "price_history_cache"
        row["regression_z"] = regression_z(values) if values is not None else None
        row["z_source"] = sources.get(code, "unavailable")
        enriched.append(row)
    if dirty:
        _save_price_history(history_path, histories)
    return enriched, sources


def load_archive(reports_dir: Path, *, exclude_date: str, as_of: date) -> dict[str, list[dict[str, Any]]]:
    """Load one calendar year of complete historical candidate records."""
    cutoff = as_of.replace(year=as_of.year - 1)
    archive: dict[str, list[dict[str, Any]]] = {}
    if not reports_dir.is_dir():
        return archive
    for path in sorted(reports_dir.glob("daily_public_screener_*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        day = str(payload.get("market_date") or payload.get("date") or "")
        if not day or day == exclude_date:
            continue
        try:
            if date.fromisoformat(day) < cutoff:
                continue
        except ValueError:
            continue
        rows = payload.get("records")
        if isinstance(rows, list):
            archive[day] = [dict(row) for row in rows if isinstance(row, Mapping)]
    return archive


def run_public_screener(
    *,
    as_of: date,
    cache_path: Path = DEFAULT_CACHE,
    meta_path: Path = DEFAULT_META,
    reports_dir: Path = DEFAULT_REPORTS,
    site_path: Path = DEFAULT_SITE,
    price_history_path: Path | None = None,
    share_candidates: int = 100,
    output_candidates: int = 100,
    z_max: float = 0.0,
    timeout: int = 60,
    backfill_sessions: int = 10,
    lookback_calendar_days: int = 24,
) -> dict[str, Any]:
    if share_candidates < 1 or output_candidates < 1:
        raise ValueError("candidate limits must be positive")
    if output_candidates > share_candidates:
        raise ValueError("output_candidates cannot exceed share_candidates")
    cache, meta = update_institutional_cache(cache_path, meta_path, as_of=as_of, required_sessions=backfill_sessions, lookback_calendar_days=lookback_calendar_days, timeout=timeout)
    prices, valuations, price_date, source_urls = fetch_current_market_data(timeout=timeout)
    masters = fetch_company_masters(timeout=timeout)
    ranked = ten_day_rank(cache, as_of=as_of.isoformat(), prices=prices, share_limit=share_candidates, limit=output_candidates)
    for index, row in enumerate(ranked, 1):
        row["rank"] = index
        row["screening_date"] = as_of.isoformat()
        row["price_date"] = price_date
        row["price_source_url"] = source_urls["twse_price"] if row.get("market") == "TWSE" else source_urls["tpex_price"]
    history_path = price_history_path or (cache_path.parent / "price_history_cache.json")
    ranked, z_sources = enrich_z(ranked, history_path=history_path, timeout=timeout)
    entries = build_scored_entries(ranked, valuations, masters, as_of=as_of, config=ScoreConfig(universe_complete=True, min_history_observations=20))
    payload = build_site_payload(entries, as_of=as_of, z_max=z_max, archive=load_archive(reports_dir, exclude_date=as_of.isoformat(), as_of=as_of))
    payload["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["candidate_scope"] = "top share-ranked daily investment-trust candidates; then amount-ranked"
    payload["candidate_limit"] = output_candidates
    payload["source_urls"] = source_urls
    payload["cache_meta"] = {"successful_date_count": meta.get("successful_date_count"), "conflict_count": len(meta.get("conflicts", [])), "error_count": len(meta.get("errors", []))}
    payload["z_known_count"] = sum(entry.get("regression_z") is not None for entry in entries)
    payload["z_unknown_count"] = sum(entry.get("regression_z") is None for entry in entries)
    payload["g_l_gate"] = False
    payload["legacy_g_l_filter_removed"] = True
    report_path = reports_dir / f"daily_public_screener_{as_of.strftime('%Y%m%d')}.json"
    _atomic_write_json(report_path, payload)
    _atomic_write_json(site_path, payload)
    return {"report_path": str(report_path), "site_path": str(site_path), "market_date": as_of.isoformat(), "records": len(entries), "active_z_pass": len(payload["active"]), "z_known": payload["z_known_count"], "z_unknown": payload["z_unknown_count"], "source_conflicts": payload["cache_meta"]["conflict_count"], "source_errors": payload["cache_meta"]["error_count"], "free_fallback_transport_calls": 0, "g_l_gate": False, "z_max": z_max}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="market date YYYY-MM-DD")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    parser.add_argument("--site", type=Path, default=DEFAULT_SITE)
    parser.add_argument("--price-history", type=Path, default=None)
    parser.add_argument("--share-candidates", type=int, default=100)
    parser.add_argument("--output-candidates", type=int, default=100)
    parser.add_argument("--z-max", type=float, default=0.0)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--backfill-sessions", type=int, default=10)
    parser.add_argument("--lookback-calendar-days", type=int, default=24)
    args = parser.parse_args(argv)
    try:
        as_of = date.fromisoformat(args.date)
        result = run_public_screener(as_of=as_of, cache_path=args.cache, meta_path=args.meta, reports_dir=args.reports, site_path=args.site, price_history_path=args.price_history, share_candidates=args.share_candidates, output_candidates=args.output_candidates, z_max=args.z_max, timeout=args.timeout, backfill_sessions=args.backfill_sessions, lookback_calendar_days=args.lookback_calendar_days)
    except (ValueError, OSError, PublicScreenerError) as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__, "error": str(exc)[:500]}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "ok", **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
