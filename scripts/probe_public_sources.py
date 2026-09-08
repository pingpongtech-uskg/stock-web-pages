#!/usr/bin/env python3
"""Bounded read-only probes for the public Taiwan stock data sources.

This phase deliberately does not call FinMind or yfinance.  Their use is
allowed only through a later explicit free-quota budget gate.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.parse import urlsplit, urlencode
from urllib.request import (
    HTTPRedirectHandler,
    HTTPCookieProcessor,
    Request,
    build_opener,
    urlopen,
)

PROBE_VERSION = "public-osint-probe-v1"
MAX_BODY_BYTES = 8_000_000
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_LISTED_CODE = "2330"
DEFAULT_OTC_CODE = "6488"


class SafeRedirectHandler(HTTPRedirectHandler):
    """Allow only same-host HTTPS redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        old = urlsplit(req.full_url)
        new = urlsplit(newurl)
        if new.scheme != "https" or new.hostname != old.hostname:
            raise ValueError("cross-host or non-HTTPS redirect rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class Response:
    url: str
    method: str
    status_code: int | None
    content_type: str
    body: str
    body_bytes: int
    error_type: str | None = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _safe_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("only HTTPS sources are allowed")
    if parsed.hostname not in allowed_hosts:
        raise ValueError(f"host is not allow-listed: {parsed.hostname}")


def request_text(
    url: str,
    *,
    allowed_hosts: set[str],
    method: str = "GET",
    form: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    opener=None,
) -> Response:
    """Fetch bounded text while returning only safe response metadata to callers."""
    _safe_url(url, allowed_hosts)
    headers = {
        "User-Agent": "stock-screener-public-osint/1.0",
        "Accept": "application/json,text/html,text/csv,text/plain,*/*",
        "Accept-Encoding": "identity",
    }
    body = None
    if form is not None:
        body = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = Request(url, data=body, headers=headers, method=method)
    client = opener or build_opener(SafeRedirectHandler())
    try:
        with client.open(request, timeout=timeout) as response:
            raw = response.read(MAX_BODY_BYTES + 1)
            if len(raw) > MAX_BODY_BYTES:
                return Response(
                    url,
                    method,
                    response.status,
                    response.headers.get("content-type", ""),
                    "",
                    len(raw),
                    "body_limit_exceeded",
                )
            return Response(
                url,
                method,
                response.status,
                response.headers.get("content-type", ""),
                raw.decode("utf-8-sig", "replace"),
                len(raw),
            )
    except HTTPError as exc:
        raw = exc.read(MAX_BODY_BYTES + 1) if exc.fp else b""
        return Response(
            url,
            method,
            exc.code,
            exc.headers.get("content-type", "") if exc.headers else "",
            "",
            len(raw),
            "http_error",
        )
    except Exception as exc:  # do not expose URLs/transport messages in reports
        return Response(url, method, None, "", "", 0, type(exc).__name__)


def _json(text: str) -> tuple[Any | None, str | None]:
    try:
        return json.loads(text), None
    except Exception as exc:
        return None, type(exc).__name__


def _rows(payload: Any) -> list[dict[str, Any]]:
    def normalize(row: dict[str, Any]) -> dict[str, Any]:
        return {str(key).lstrip(chr(0xFEFF)): value for key, value in row.items()}

    if isinstance(payload, list):
        return [normalize(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return []
    fields = payload.get("fields")
    if isinstance(fields, list) and all(isinstance(x, str) for x in fields):
        normalized_fields = [field.lstrip(chr(0xFEFF)) for field in fields]
        return [dict(zip(normalized_fields, row)) for row in payload["data"] if isinstance(row, list)]
    return [normalize(row) for row in payload["data"] if isinstance(row, dict)]


def _row_keys(rows: Iterable[dict[str, Any]]) -> list[str]:
    return sorted({key for row in rows for key in row})


def _periods(rows: Iterable[dict[str, Any]], payload: Any) -> list[str]:
    keys = {
        "資料年月",
        "資料日期",
        "出表日期",
        "Date",
        "日期",
        "年度",
        "Year",
        "股利年度",
    }
    found: list[str] = []
    for row in rows:
        for key, value in row.items():
            if key in keys or key.endswith("日期") or key.endswith("年月"):
                text = str(value).strip()
                if text and text not in found:
                    found.append(text)
                if len(found) >= 8:
                    return found
    if isinstance(payload, dict):
        for key in ("date", "title"):
            value = payload.get(key)
            if value is not None and str(value) not in found:
                found.append(str(value))
    return found[:8]


def _code_in_row(row: dict[str, Any], code: str) -> bool:
    code_keys = {
        "公司代號",
        "公司代碼",
        "股票代號",
        "證券代號",
        "Code",
        "SecuritiesCompanyCode",
    }
    return any(str(row.get(key, "")).strip() == code for key in code_keys)


def probe_json(
    source_id: str,
    url: str,
    *,
    allowed_hosts: set[str],
    required_fields: list[str],
    target_code: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    response = request_text(url, allowed_hosts=allowed_hosts, timeout=timeout)
    result: dict[str, Any] = {
        "source_id": source_id,
        "url": url,
        "method": "GET",
        "http_status": response.status_code,
        "content_type": response.content_type,
        "body_bytes": response.body_bytes,
        "parser_version": PROBE_VERSION,
    }
    if response.error_type:
        result.update({"status": "BLOCKED", "error_type": response.error_type})
        return result
    payload, parse_error = _json(response.body)
    if parse_error:
        result.update({"status": "PARSE_ERROR", "error_type": parse_error})
        return result
    rows = _rows(payload)
    keys = _row_keys(rows)
    missing = [field for field in required_fields if field not in keys]
    target_rows = [row for row in rows if target_code and _code_in_row(row, target_code)]
    result.update(
        {
            "status": "PASS" if response.status_code == 200 and rows and not missing else "FAIL",
            "shape": "list_of_objects" if isinstance(payload, list) else "object_with_data",
            "row_count": len(rows),
            "field_count": len(keys),
            "missing_required_fields": missing,
            "observed_periods": _periods(rows, payload),
        }
    )
    if target_code:
        result["target_code"] = target_code
        result["target_row_count"] = len(target_rows)
        result["target_present"] = bool(target_rows)
        if not target_rows:
            result["status"] = "FAIL"
    if isinstance(payload, dict) and isinstance(payload.get("paths"), dict):
        result["path_count"] = len(payload["paths"])
    return result


def probe_oas(
    source_id: str,
    url: str,
    *,
    allowed_hosts: set[str],
    timeout: int,
) -> dict[str, Any]:
    response = request_text(url, allowed_hosts=allowed_hosts, timeout=timeout)
    result: dict[str, Any] = {
        "source_id": source_id,
        "url": url,
        "method": "GET",
        "http_status": response.status_code,
        "content_type": response.content_type,
        "body_bytes": response.body_bytes,
        "parser_version": PROBE_VERSION,
    }
    payload, parse_error = _json(response.body) if not response.error_type else (None, response.error_type)
    if parse_error or not isinstance(payload, dict):
        result.update({"status": "PARSE_ERROR" if response.status_code == 200 else "BLOCKED", "error_type": parse_error or response.error_type or "not_object"})
        return result
    paths = payload.get("paths")
    result.update(
        {
            "status": "PASS" if response.status_code == 200 and isinstance(paths, dict) and paths else "FAIL",
            "openapi": payload.get("openapi") or payload.get("swagger"),
            "path_count": len(paths) if isinstance(paths, dict) else 0,
        }
    )
    return result


def probe_dataset(
    source_id: str,
    url: str,
    *,
    allowed_hosts: set[str],
    timeout: int,
) -> dict[str, Any]:
    response = request_text(url, allowed_hosts=allowed_hosts, timeout=timeout)
    result: dict[str, Any] = {
        "source_id": source_id,
        "url": url,
        "method": "GET",
        "http_status": response.status_code,
        "content_type": response.content_type,
        "body_bytes": response.body_bytes,
        "parser_version": PROBE_VERSION,
    }
    payload, parse_error = _json(response.body) if not response.error_type else (None, response.error_type)
    dataset = payload.get("result") if isinstance(payload, dict) else None
    if parse_error or not isinstance(dataset, dict):
        result.update({"status": "PARSE_ERROR" if response.status_code == 200 else "BLOCKED", "error_type": parse_error or response.error_type or "missing_result"})
        return result
    distributions = dataset.get("distribution")
    result.update(
        {
            "status": "PASS" if response.status_code == 200 and dataset.get("datasetId") == 11452 else "FAIL",
            "dataset_id": dataset.get("datasetId"),
            "title": dataset.get("title"),
            "cost": dataset.get("cost"),
            "update_frequency": dataset.get("updateFrequency"),
            "distribution_count": len(distributions) if isinstance(distributions, list) else 0,
        }
    )
    return result


def probe_csv(
    source_id: str,
    url: str,
    *,
    allowed_hosts: set[str],
    required_fields: list[str],
    target_codes: list[str],
    timeout: int,
) -> dict[str, Any]:
    response = request_text(url, allowed_hosts=allowed_hosts, timeout=timeout)
    result: dict[str, Any] = {
        "source_id": source_id,
        "url": url,
        "method": "GET",
        "http_status": response.status_code,
        "content_type": response.content_type,
        "body_bytes": response.body_bytes,
        "parser_version": PROBE_VERSION,
    }
    if response.error_type:
        result.update({"status": "BLOCKED", "error_type": response.error_type})
        return result
    try:
        reader = csv.DictReader(io.StringIO(response.body))
        fieldnames = [str(x).lstrip("\ufeff") for x in (reader.fieldnames or [])]
        rows = []
        for row in reader:
            normalized = {str(k).lstrip("\ufeff"): v for k, v in row.items() if k is not None}
            rows.append(normalized)
        missing = [field for field in required_fields if field not in fieldnames]
        hits = {code: sum(1 for row in rows if str(row.get("證券代號", "")).strip() == code) for code in target_codes}
        result.update(
            {
                "status": "PASS" if response.status_code == 200 and rows and not missing else "FAIL",
                "row_count": len(rows),
                "fieldnames": fieldnames,
                "missing_required_fields": missing,
                "target_row_counts": hits,
            }
        )
    except Exception as exc:
        result.update({"status": "PARSE_ERROR", "error_type": type(exc).__name__})
    return result


def _clean_html(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _mops_form(
    source_id: str,
    url: str,
    *,
    allowed_hosts: set[str],
    market: str,
    code: str,
    year: str,
    season: str | None = None,
    month: str | None = None,
    markers: list[str],
    timeout: int,
) -> dict[str, Any]:
    form = {
        "step": "1",
        "firstin": "ture",
        "off": "1",
        "keyword4": "",
        "code1": "",
        "TYPEK2": "",
        "checkbtn": "",
        "queryName": "co_id",
        "inpuType": "co_id",
        "TYPEK": market,
        "isnew": "false",
        "co_id": code,
        "year": year,
    }
    if season is not None:
        form["season"] = season
    if month is not None:
        form["month"] = month
    response = request_text(url, allowed_hosts=allowed_hosts, method="POST", form=form, timeout=timeout)
    flat = _clean_html(response.body)
    if season is not None:
        try:
            display_season = str(int(season))
        except ValueError:
            display_season = season
        requested_period = f"民國{year}年第{display_season}季"
    elif month is not None:
        requested_period = f"民國{year}年{month}月"
    else:
        raise ValueError("MOPS probe requires season or month")
    marker_hits = {marker: marker in flat for marker in markers}
    period_match = requested_period in flat
    if source_id == "mops.insider_history" and month is not None:
        period_match = f"資料年月:{year}{month}" in flat
    result: dict[str, Any] = {
        "source_id": source_id,
        "url": url,
        "method": "POST",
        "market": market,
        "target_code": code,
        "requested_period": requested_period,
        "http_status": response.status_code,
        "content_type": response.content_type,
        "body_bytes": response.body_bytes,
        "parser_version": PROBE_VERSION,
        "period_match": period_match,
        "marker_hits": marker_hits,
        "status": "PASS" if response.status_code == 200 and period_match and all(marker_hits.values()) else "FAIL",
    }
    if response.error_type:
        result.update({"status": "BLOCKED", "error_type": response.error_type, "period_match": False})
    return result


def _mops_base_url(source_id: str) -> str:
    return {
        "mops.balance_history": "https://mopsov.twse.com.tw/mops/web/ajax_t164sb03",
        "mops.income_history": "https://mopsov.twse.com.tw/mops/web/ajax_t164sb04",
        "mops.cashflow_history": "https://mopsov.twse.com.tw/mops/web/ajax_t164sb05",
        "mops.monthly_revenue_history": "https://mopsov.twse.com.tw/mops/web/ajax_t05st10_ifrs",
        "mops.insider_history": "https://mopsov.twse.com.tw/mops/web/ajax_stapap1",
    }[source_id]


def probe_mops_sources(allowed_hosts: set[str], timeout: int) -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    financial_markers = {
        "mops.balance_history": ["合併資產負債表", "流動資產", "應收帳款", "存貨", "權益總計"],
        "mops.income_history": ["合併綜合損益表", "營業收入合計", "營業利益（損失）", "稅前淨利（淨損）"],
        "mops.cashflow_history": ["合併現金流量表", "營業活動之淨現金流入（流出）", "投資活動之淨現金流入（流出）"],
    }
    for source_id, markers in financial_markers.items():
        for market, code in (("sii", DEFAULT_LISTED_CODE), ("otc", DEFAULT_OTC_CODE)):
            probes.append(
                _mops_form(
                    source_id,
                    _mops_base_url(source_id),
                    allowed_hosts=allowed_hosts,
                    market=market,
                    code=code,
                    year="114",
                    season="04",
                    markers=markers,
                    timeout=timeout,
                )
            )
    for market, code in (("sii", DEFAULT_LISTED_CODE), ("otc", DEFAULT_OTC_CODE)):
        probes.append(
            _mops_form(
                "mops.monthly_revenue_history",
                _mops_base_url("mops.monthly_revenue_history"),
                allowed_hosts=allowed_hosts,
                market=market,
                code=code,
                year="115",
                month="07",
                markers=["營業收入淨額", "去年同期"],
                timeout=timeout,
            )
        )
        probes.append(
            _mops_form(
                "mops.insider_history",
                _mops_base_url("mops.insider_history"),
                allowed_hosts=allowed_hosts,
                market=market,
                code=code,
                year="115",
                month="07",
                markers=["資料年月:11507", "目前持股"],
                timeout=timeout,
            )
        )
    return probes


def probe_tdcc_query(allowed_hosts: set[str], timeout: int) -> dict[str, Any]:
    url = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar), SafeRedirectHandler())
    initial = request_text(url, allowed_hosts=allowed_hosts, timeout=timeout, opener=opener)
    token_match = re.search(r'name="SYNCHRONIZER_TOKEN"\s+value="([^"]+)"', initial.body, re.I)
    dates = re.findall(r'<option\s+value="(\d{8})"', initial.body, re.I)
    result: dict[str, Any] = {
        "source_id": "tdcc.historical_query",
        "url": url,
        "method": "GET+POST",
        "http_status": initial.status_code,
        "content_type": initial.content_type,
        "body_bytes": initial.body_bytes,
        "parser_version": PROBE_VERSION,
        "date_option_count": len(dates),
        "latest_option": dates[0] if dates else None,
        "oldest_option": dates[-1] if dates else None,
        "token_present": bool(token_match),
    }
    if initial.error_type or not token_match or not dates:
        result.update({"status": "BLOCKED", "error_type": initial.error_type or "missing_form_token_or_dates"})
        result.pop("token_present", None)
        return result
    form = {
        "SYNCHRONIZER_TOKEN": token_match.group(1),
        "SYNCHRONIZER_URI": "/portal/zh/smWeb/qryStock",
        "method": "submit",
        "firDate": dates[0],
        "scaDate": dates[0],
        "sqlMethod": "StockNo",
        "stockNo": DEFAULT_LISTED_CODE,
        "stockName": "",
    }
    queried = request_text(url, allowed_hosts=allowed_hosts, method="POST", form=form, timeout=timeout, opener=opener)
    flat = _clean_html(queried.body)
    result.update(
        {
            "post_http_status": queried.status_code,
            "post_body_bytes": queried.body_bytes,
            "target_code": DEFAULT_LISTED_CODE,
            "target_present": DEFAULT_LISTED_CODE in flat,
            "table_marker_present": "持股/單位數分級" in flat,
            "status": "PASS" if queried.status_code == 200 and DEFAULT_LISTED_CODE in flat and "持股/單位數分級" in flat else "FAIL",
        }
    )
    if queried.error_type:
        result.update({"status": "BLOCKED", "error_type": queried.error_type})
    result.pop("token_present", None)
    return result


def _source(registry: dict[str, Any], source_id: str) -> dict[str, Any]:
    for source in registry.get("sources", []):
        if isinstance(source, dict) and source.get("id") == source_id:
            return source
    raise KeyError(source_id)


def run_probe(registry: dict[str, Any], *, timeout: int, enable_free_fallback_smoke: bool, free_fallback_budget: int) -> dict[str, Any]:
    policy = registry["policy"]
    allowed_hosts = set(policy["allowed_hosts"])
    results: list[dict[str, Any]] = []

    def json_source(source_id: str, url: str, target: str | None = None) -> None:
        source = _source(registry, source_id)
        results.append(
            probe_json(
                source_id,
                url,
                allowed_hosts=allowed_hosts,
                required_fields=list(source.get("required_any_fields", [])),
                target_code=target,
                timeout=timeout,
            )
        )

    results.append(probe_oas("twse.swagger", "https://openapi.twse.com.tw/v1/swagger.json", allowed_hosts=allowed_hosts, timeout=timeout))
    for source_id, target in [
        ("twse.company_basic", DEFAULT_LISTED_CODE),
        ("twse.monthly_revenue", DEFAULT_LISTED_CODE),
        ("twse.quarterly_income", DEFAULT_LISTED_CODE),
        ("twse.quarterly_balance", DEFAULT_LISTED_CODE),
        ("twse.dividend", DEFAULT_LISTED_CODE),
        ("twse.valuation_current", DEFAULT_LISTED_CODE),
    ]:
        source = _source(registry, source_id)
        json_source(source_id, source["url"], target)
    results.append(
        probe_json(
            "twse.valuation_history",
            "https://www.twse.com.tw/exchangeReport/BWIBBU_d?response=json&date=20260904&selectType=ALL",
            allowed_hosts=allowed_hosts,
            required_fields=["證券代號", "本益比", "股價淨值比", "殖利率(%)"],
            target_code=DEFAULT_LISTED_CODE,
            timeout=timeout,
        )
    )
    results.append(
        probe_json(
            "twse.price_history",
            "https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=20260901&stockNo=2330",
            allowed_hosts=allowed_hosts,
            required_fields=["日期", "收盤價"],
            timeout=timeout,
        )
    )

    results.append(probe_oas("tpex.swagger", "https://www.tpex.org.tw/openapi/swagger.json", allowed_hosts=allowed_hosts, timeout=timeout))
    for source_id, target in [
        ("tpex.company_basic", DEFAULT_OTC_CODE),
        ("tpex.monthly_revenue", DEFAULT_OTC_CODE),
        ("tpex.quarterly_income", DEFAULT_OTC_CODE),
        ("tpex.quarterly_balance", DEFAULT_OTC_CODE),
        ("tpex.valuation_current", DEFAULT_OTC_CODE),
        ("tpex.market_value", DEFAULT_OTC_CODE),
    ]:
        source = _source(registry, source_id)
        json_source(source_id, source["url"], target)

    results.append(probe_oas("tdcc.openapi_docs", "https://openapi.tdcc.com.tw/tdcc-opendata-api-docs", allowed_hosts=allowed_hosts, timeout=timeout))
    for source_id, target in [("tdcc.listed_shareholders", DEFAULT_LISTED_CODE), ("tdcc.otc_shareholders", DEFAULT_OTC_CODE)]:
        source = _source(registry, source_id)
        json_source(source_id, source["url"], target)
    results.append(probe_dataset("tdcc.dataset_11452", "https://data.gov.tw/api/v2/rest/dataset/11452", allowed_hosts=allowed_hosts, timeout=timeout))
    results.append(
        probe_csv(
            "tdcc.dispersion_csv",
            "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
            allowed_hosts=allowed_hosts,
            required_fields=["資料日期", "證券代號", "持股分級", "人數", "股數"],
            target_codes=[DEFAULT_LISTED_CODE, DEFAULT_OTC_CODE],
            timeout=timeout,
        )
    )
    results.append(probe_tdcc_query(allowed_hosts, timeout))
    results.extend(probe_mops_sources(allowed_hosts, timeout))

    free_policy: dict[str, Any] = {
        "status": "SKIPPED_BY_DEFAULT",
        "providers": policy.get("free_fallbacks", []),
        "budget_required": bool(policy.get("free_quota_budget_required")),
        "budget_allocated": free_fallback_budget,
        "transport_calls": 0,
        "reason": "Phase A probe does not consume fallback quota; use a separately approved adapter smoke.",
    }
    if enable_free_fallback_smoke and free_fallback_budget < 1:
        free_policy.update({"status": "BLOCKED", "reason": "--enable-free-fallback-smoke requires --free-fallback-budget >= 1"})
    elif enable_free_fallback_smoke:
        free_policy.update({"status": "BLOCKED", "reason": "Fallback adapter smoke is not part of Phase A; no unbudgeted transport made."})

    counts: dict[str, int] = {}
    for item in results:
        status = str(item.get("status", "UNKNOWN"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "schema_version": 1,
        "probe_version": PROBE_VERSION,
        "run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scope": "public-official-source-schema-and-history-smoke",
        "policy": {
            "public_only": True,
            "paid_api": False,
            "browser_dependency": False,
            "free_fallbacks": policy.get("free_fallbacks", []),
            "free_fallback_policy": policy.get("free_fallback_policy"),
        },
        "result_counts": counts,
        "results": results,
        "free_fallback": free_policy,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    root = _repo_root()
    parser.add_argument("--sources", type=Path, default=root / "calibration" / "source_registry.json")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--enable-free-fallback-smoke", action="store_true")
    parser.add_argument("--free-fallback-budget", type=int, default=0)
    args = parser.parse_args()
    if args.timeout < 1 or args.free_fallback_budget < 0:
        parser.error("timeout must be positive and free-fallback-budget cannot be negative")
    registry = _load_json(args.sources)
    report = run_probe(
        registry,
        timeout=args.timeout,
        enable_free_fallback_smoke=args.enable_free_fallback_smoke,
        free_fallback_budget=args.free_fallback_budget,
    )
    if args.out:
        write_report(args.out, report)
        print(json.dumps({"out": str(args.out), "result_counts": report["result_counts"], "free_fallback": report["free_fallback"]}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
