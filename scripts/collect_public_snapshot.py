#!/usr/bin/env python3
"""Collect compact, provenance-rich public snapshots for a small stock set.

The collector uses official public TWSE/TPEx/TDCC/MOPS sources only.  FinMind
and yfinance are intentionally not called here; they have a separate budget
policy and may be added later as secondary free-quota fallbacks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import HTTPCookieProcessor, build_opener
from http.cookiejar import CookieJar

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.normalized_snapshot import validate_field_record
from scripts.probe_public_sources import _json, request_text
from scripts.public_sources import exchanges, mops, tdcc

COLLECTOR_VERSION = "public-osint-snapshot-v1"
SCHEMA_VERSION = 1
FORMULA_VERSION = "unscored-public-fields-v1"
DEFAULT_TIMEOUT = 60

SOURCE_URLS = {
    "TWSE": {
        "basic": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
        "monthly": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
        "income": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
        "balance": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci",
        "dividend": "https://openapi.twse.com.tw/v1/opendata/t187ap45_L",
        "valuation": "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL",
        "valuation_history": "https://www.twse.com.tw/exchangeReport/BWIBBU_d?response=json&date={date}&selectType=ALL",
        "price_history": "https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={yyyymm01}&stockNo={code}",
    },
    "TPEx": {
        "basic": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
        "monthly": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
        "income": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci",
        "balance": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ci",
        "valuation": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis",
    },
}

SOURCE_IDS = {
    "TWSE": {
        "basic": "twse.company_basic",
        "monthly": "twse.monthly_revenue",
        "income": "twse.quarterly_income",
        "balance": "twse.quarterly_balance",
        "dividend": "twse.dividend",
        "valuation": "twse.valuation_current",
        "valuation_history": "twse.valuation_history",
        "price_history": "twse.price_history",
    },
    "TPEx": {
        "basic": "tpex.company_basic",
        "monthly": "tpex.monthly_revenue",
        "income": "tpex.quarterly_income",
        "balance": "tpex.quarterly_balance",
        "valuation": "tpex.valuation_current",
    },
}

MOPS_URLS = {
    "balance": "https://mopsov.twse.com.tw/mops/web/ajax_t164sb03",
    "income": "https://mopsov.twse.com.tw/mops/web/ajax_t164sb04",
    "cashflow": "https://mopsov.twse.com.tw/mops/web/ajax_t164sb05",
    "monthly": "https://mopsov.twse.com.tw/mops/web/ajax_t05st10_ifrs",
    "insider": "https://mopsov.twse.com.tw/mops/web/ajax_stapap1",
}
MOPS_IDS = {
    "balance": "mops.balance_history",
    "income": "mops.income_history",
    "cashflow": "mops.cashflow_history",
    "monthly": "mops.monthly_revenue_history",
    "insider": "mops.insider_history",
}


def load_source_registry() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "calibration" / "source_registry.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def month_sequence(year: str, month: str, count: int) -> list[tuple[str, str]]:
    """Return current ROC year/month followed by previous months."""
    if not re.fullmatch(r"\d{3}", str(year)) or not re.fullmatch(r"\d{2}", str(month)):
        raise ValueError("ROC year/month must be three/two digits")
    current_year, current_month = int(year), int(month)
    if not 1 <= current_month <= 12 or count < 1:
        raise ValueError("invalid ROC month or count")
    result = []
    for _ in range(count):
        result.append((f"{current_year:03d}", f"{current_month:02d}"))
        current_month -= 1
        if current_month == 0:
            current_year -= 1
            current_month = 12
    return result


def roc_month_to_period(year: str, month: str) -> str:
    return f"{1911 + int(year):04d}-{int(month):02d}"


def roc_year_to_fiscal(year: str) -> str:
    return f"{1911 + int(year):04d}-FY"


def _body_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if text in {"", "-", "－", "—", "–", "N/A", "NA"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric source value: {value!r}") from exc
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError("source number is not finite")
    return number


def build_field(
    *,
    canonical_name: str,
    source_label: str,
    value: float | None,
    unit: str | None,
    source_id: str,
    source_url: str,
    period: str,
    raw_snapshot_id: str,
    reason: str | None = None,
    published_at: str = "unknown",
) -> dict[str, Any]:
    status = "PASS" if value is not None else "UNKNOWN"
    if value is None and not reason:
        reason = "source value missing or unavailable"
    field = {
        "canonical_name": canonical_name,
        "source_label": source_label,
        "value": value,
        "unit": unit,
        "status": status,
        "reason": reason,
        "source_id": source_id,
        "source_url": source_url,
        "period": period,
        "published_at": published_at,
    }
    validate_field_record(field)
    return field


def _clean_html(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value or "", flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_tdcc_shareholder_count(html_text: str) -> int:
    """Extract one TDCC total-holder row; reject missing/duplicate totals."""
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html_text or "", flags=re.I | re.S)
    matches: list[int] = []
    for row in rows:
        cells = [
            _clean_html(cell)
            for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, flags=re.I | re.S)
        ]
        if len(cells) < 3:
            continue
        if re.sub(r"\s+", "", cells[1]) != "合計":
            continue
        number = _parse_float(cells[2])
        if number is None or number < 0 or number != int(number):
            raise ValueError("TDCC total-holder count is invalid")
        matches.append(int(number))
    if not matches:
        raise ValueError("TDCC total-holder row missing")
    if len(matches) != 1:
        raise ValueError("duplicate TDCC total-holder row")
    return matches[0]


def _source_meta(
    source_id: str,
    url: str,
    response: Any,
    *,
    method: str,
    requested_period: str | None = None,
    parser_version: str = COLLECTOR_VERSION,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_url": url,
        "method": method,
        "http_status": response.status_code,
        "content_type": response.content_type,
        "body_bytes": response.body_bytes,
        "raw_snapshot_id": _body_hash(response.body),
        "parser_version": parser_version,
        "schema_version": SCHEMA_VERSION,
        "requested_period": requested_period,
    }


def _metric_row(
    document: dict[str, Any] | None,
    aliases: tuple[str, ...],
    *,
    value_index: int = 0,
) -> tuple[str, float | None, str | None]:
    if document is None:
        return aliases[0], None, "source document unavailable"
    for alias in aliases:
        try:
            row = mops.select_unique_row(document["rows"], alias)
        except KeyError:
            continue
        except ValueError as exc:
            return alias, None, str(exc)
        values = row.get("values", [])
        if value_index >= len(values):
            return alias, None, "source column missing"
        try:
            value = mops.parse_number(values[value_index])
        except ValueError as exc:
            return alias, None, str(exc)
        return alias, value, None if value is not None else "source value blank"
    return aliases[0], None, "source row missing"


def _add_metric(
    fields: dict[str, dict[str, Any]],
    *,
    canonical_name: str,
    aliases: tuple[str, ...],
    document: dict[str, Any] | None,
    source_meta: dict[str, Any],
    period: str,
    value_index: int = 0,
    unit: str | None = None,
) -> None:
    label, value, reason = _metric_row(document, aliases, value_index=value_index)
    if document is not None and not document.get("period_match", True):
        reason = "response period does not match request"
        value = None
    fields[canonical_name] = build_field(
        canonical_name=canonical_name,
        source_label=label,
        value=value,
        unit=unit or (document or {}).get("unit"),
        source_id=source_meta["source_id"],
        source_url=source_meta["source_url"],
        period=period,
        raw_snapshot_id=source_meta["raw_snapshot_id"],
        reason=reason,
    )


def _code_from_row(row: dict[str, Any]) -> str | None:
    for key in ("公司代號", "證券代號", "SecuritiesCompanyCode", "Code"):
        value = str(row.get(key, "")).strip()
        if re.fullmatch(r"[1-9]\d{3}", value):
            return value
    return None


def _fetch_json(
    source_id: str,
    url: str,
    *,
    allowed_hosts: set[str],
    timeout: int,
    target_code: str | None = None,
) -> tuple[Any | None, dict[str, Any], Any]:
    for attempt in range(1, 3):
        response = request_text(url, allowed_hosts=allowed_hosts, timeout=timeout)
        meta = _source_meta(source_id, url, response, method="GET")
        meta["attempts"] = attempt
        if response.error_type or response.status_code != 200:
            meta["status"] = "BLOCKED"
            meta["error_type"] = response.error_type or "http_status"
            return None, meta, response
        payload, parse_error = _json(response.body)
        if parse_error:
            if attempt == 1:
                continue
            meta["status"] = "PARSE_ERROR"
            meta["error_type"] = parse_error
            return None, meta, response
        rows = exchanges._rows(payload)
        meta["status"] = "PASS" if rows else "FAIL"
        meta["row_count"] = len(rows)
        if target_code:
            hits = [row for row in rows if _code_from_row(row) == target_code]
            meta["target_code"] = target_code
            meta["target_present"] = bool(hits)
            meta["target_row_count"] = len(hits)
            if not hits:
                meta["status"] = "FAIL"
        return payload, meta, response
    # The loop always returns; retain a defensive failure for static analyzers.
    raise RuntimeError("JSON fetch exhausted retries")


def _fetch_mops(
    source_key: str,
    *,
    market_type: str,
    code: str,
    allowed_hosts: set[str],
    timeout: int,
    year: str,
    season: str | None = None,
    month: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any], Any]:
    url = MOPS_URLS[source_key]
    form = mops.build_historical_form(
        market_type,
        code,
        year=year,
        season=season,
        month=month,
        endpoint="insider" if source_key == "insider" else "financial",
    )
    response = request_text(url, allowed_hosts=allowed_hosts, method="POST", form=form, timeout=timeout)
    if season is not None:
        display_season = str(int(season))
        requested_period = f"民國{year}年第{display_season}季"
    else:
        requested_period = f"資料年月:{year}{month}" if source_key == "insider" else f"民國{year}年{month}月"
    meta = _source_meta(MOPS_IDS[source_key], url, response, method="POST", requested_period=requested_period, parser_version="mops-html-v1")
    if response.error_type or response.status_code != 200:
        meta.update({"status": "BLOCKED", "error_type": response.error_type or "http_status"})
        return None, meta, response
    try:
        document = mops.parse_mops_html(
            response.body,
            code=code,
            market=market_type,
            requested_period=requested_period,
        )
    except Exception as exc:
        meta.update({"status": "PARSE_ERROR", "error_type": type(exc).__name__})
        return None, meta, response
    meta.update(
        {
            "status": "PASS" if document["period_match"] else "FAIL",
            "period_match": document["period_match"],
            "observed_periods": document["observed_periods"][:8],
            "row_count": document["table_count"],
        }
    )
    return document, meta, response


def _field_value(fields: dict[str, dict[str, Any]], name: str) -> float | None:
    value = fields.get(name, {}).get("value")
    return float(value) if isinstance(value, (int, float)) else None


def _select_tdcc_month_dates(dates: list[str], count: int) -> list[str]:
    grouped: dict[str, str] = {}
    for value in dates:
        try:
            parsed = datetime.strptime(value, "%Y%m%d")
        except ValueError:
            continue
        month = parsed.strftime("%Y-%m")
        if value > grouped.get(month, ""):
            grouped[month] = value
    return [grouped[key] for key in sorted(grouped)[-count:]]


def _collect_tdcc_history(
    *,
    code: str,
    allowed_hosts: set[str],
    timeout: int,
    fields: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
    count: int = 13,
) -> tuple[list[str], list[str]]:
    url = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
    # One initial request discovers the available weekly dates.  Each actual
    # date query refreshes its own form/session in tdcc.fetch_query_once().
    initial = request_text(url, allowed_hosts=allowed_hosts, timeout=timeout)
    initial_meta = _source_meta("tdcc.historical_query", url, initial, method="GET", parser_version="tdcc-html-v1")
    dates = tdcc.extract_query_dates(initial.body)
    if initial.error_type or initial.status_code != 200 or not dates:
        initial_meta.update({"status": "BLOCKED", "error_type": initial.error_type or "missing_date_options"})
        sources.append(initial_meta)
        return [], ["TDCC historical query form unavailable"]
    initial_meta.update({"status": "PASS", "date_option_count": len(dates), "latest_option": dates[0], "oldest_option": dates[-1]})
    sources.append(initial_meta)
    selected_dates = _select_tdcc_month_dates(dates, count)
    errors: list[str] = []
    periods: list[str] = []
    for snapshot_date in selected_dates:
        try:
            query = tdcc.fetch_query_once(url, snapshot_date, code, allowed_hosts, timeout)
            response = query["queried"]
        except Exception as exc:
            errors.append(f"TDCC {snapshot_date}: {type(exc).__name__}")
            period = f"{snapshot_date[:4]}-{snapshot_date[4:6]}"
            periods.append(period)
            fields[f"tdcc.shareholder_count.{period}"] = build_field(
                canonical_name=f"tdcc.shareholder_count.{period}",
                source_label="合 計／人數",
                value=None,
                unit="shareholders",
                source_id="tdcc.historical_query",
                source_url=url,
                period=period,
                raw_snapshot_id=_body_hash(""),
                reason=f"TDCC fresh query unavailable: {type(exc).__name__}",
                published_at="unknown",
            )
            continue
        meta = _source_meta("tdcc.historical_query", url, response, method="POST", requested_period=snapshot_date, parser_version="tdcc-html-v1")
        if response.error_type or response.status_code != 200:
            meta.update({"status": "BLOCKED", "error_type": response.error_type or "http_status"})
            sources.append(meta)
            errors.append(f"TDCC {snapshot_date}: unavailable")
            continue
        try:
            holder_count = parse_tdcc_shareholder_count(response.body)
            status = "PASS"
            reason = None
        except Exception as exc:
            holder_count = None
            status = "UNKNOWN"
            reason = f"TDCC total-holder parse failed: {type(exc).__name__}"
            errors.append(f"TDCC {snapshot_date}: {type(exc).__name__}")
        meta.update({"status": status, "target_code": code, "snapshot_date": snapshot_date, "fresh_session": True})
        sources.append(meta)
        period = f"{snapshot_date[:4]}-{snapshot_date[4:6]}"
        periods.append(period)
        fields[f"tdcc.shareholder_count.{period}"] = build_field(
            canonical_name=f"tdcc.shareholder_count.{period}",
            source_label="合 計／人數",
            value=holder_count,
            unit="shareholders",
            source_id="tdcc.historical_query",
            source_url=url,
            period=period,
            raw_snapshot_id=meta["raw_snapshot_id"],
            reason=reason,
            published_at="unknown",
        )
    return periods, errors


def _insider_current_value(row: dict[str, Any]) -> float | None:
    values = row.get("values", [])
    if values:
        try:
            aggregate_value = mops.parse_number(values[0])
        except ValueError:
            aggregate_value = None
        if aggregate_value is not None:
            return aggregate_value
    if len(values) >= 3:
        return mops.parse_number(values[2])
    if values:
        return mops.parse_number(values[-1])
    return None


def _collect_insider_history(
    *,
    code: str,
    market_type: str,
    latest_year: str,
    latest_month: str,
    allowed_hosts: set[str],
    timeout: int,
    fields: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
    count: int = 13,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    periods: list[str] = []
    aggregate_labels = (
        "非獨立董事持股合計",
        "獨立董事持股合計",
        "非獨立監察人持股合計",
        "獨立監察人持股合計",
    )
    for year, month in month_sequence(latest_year, latest_month, count):
        document, meta, _ = _fetch_mops(
            "insider",
            market_type=market_type,
            code=code,
            allowed_hosts=allowed_hosts,
            timeout=timeout,
            year=year,
            month=month,
        )
        sources.append(meta)
        period = roc_month_to_period(year, month)
        periods.append(period)
        if document is None or not meta.get("period_match"):
            errors.append(f"MOPS insider {period}: unavailable")
            for label in aggregate_labels:
                canonical = f"insider.{period}.{label}"
                fields[canonical] = build_field(
                    canonical_name=canonical,
                    source_label=label,
                    value=None,
                    unit="shares",
                    source_id=MOPS_IDS["insider"],
                    source_url=MOPS_URLS["insider"],
                    period=period,
                    raw_snapshot_id=meta["raw_snapshot_id"],
                    reason="MOPS insider document unavailable or wrong period",
                )
            continue
        for label in aggregate_labels:
            canonical = f"insider.{period}.{label}"
            try:
                row = mops.select_unique_row(document["rows"], label)
                value = _insider_current_value(row)
                reason = None if value is not None else "aggregate current holding blank"
            except (KeyError, ValueError) as exc:
                value = None
                reason = f"aggregate row unavailable: {type(exc).__name__}"
            fields[canonical] = build_field(
                canonical_name=canonical,
                source_label=label,
                value=value,
                unit="shares",
                source_id=MOPS_IDS["insider"],
                source_url=MOPS_URLS["insider"],
                period=period,
                raw_snapshot_id=meta["raw_snapshot_id"],
                reason=reason,
            )
        # Keep major-holder scope unresolved.  Do not sum repeated individuals.
        major_matches = [row for row in document["rows"] if re.sub(r"\s+", "", str(row.get("label", ""))) == "大股東本人"]
        major_key = f"insider.{period}.大股東本人"
        fields[major_key] = build_field(
            canonical_name=major_key,
            source_label="大股東本人",
            value=None,
            unit="shares",
            source_id=MOPS_IDS["insider"],
            source_url=MOPS_URLS["insider"],
            period=period,
            raw_snapshot_id=meta["raw_snapshot_id"],
            reason=f"major-holder scope unresolved; observed_rows={len(major_matches)}",
        )
    return periods, errors


def _collect_financial_history(
    *,
    code: str,
    market_type: str,
    annual_years: list[str],
    latest_quarter: tuple[str, str],
    allowed_hosts: set[str],
    timeout: int,
    fields: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    annual_periods: list[str] = []
    income_aliases = {
        "revenue": ("營業收入合計", "營業收入"),
        "gross_profit": ("營業毛利（毛損）淨額", "營業毛利（毛損）"),
        "operating_income": ("營業利益（損失）",),
        "pretax_income": ("稅前淨利（淨損）",),
        "after_tax_income": ("本期淨利（淨損）", "繼續營業單位本期淨利（淨損）"),
        "eps": ("基本每股盈餘（元）", "基本每股盈餘"),
    }
    balance_aliases = {
        "receivables": ("應收帳款淨額",),
        "inventory": ("存貨",),
        "current_assets": ("流動資產合計", "流動資產"),
        "current_liabilities": ("流動負債合計", "流動負債"),
        "equity": ("權益總額", "權益總計", "歸屬於母公司業主之權益合計"),
        "noncurrent_liabilities": ("非流動負債合計", "非流動負債"),
        "total_assets": ("資產總額", "資產總計"),
        "capital": ("股本合計", "普通股股本", "股本"),
    }
    cashflow_aliases = {
        "cfo": ("營業活動之淨現金流入（流出）",),
        "cfi": ("投資活動之淨現金流入（流出）",),
    }
    for roc_year in annual_years:
        period = roc_year_to_fiscal(roc_year)
        annual_periods.append(period)
        docs: dict[str, tuple[dict[str, Any] | None, dict[str, Any]]] = {}
        for key, aliases in (("income", income_aliases), ("balance", balance_aliases), ("cashflow", cashflow_aliases)):
            document, meta, _ = _fetch_mops(
                "cashflow" if key == "cashflow" else key,
                market_type=market_type,
                code=code,
                allowed_hosts=allowed_hosts,
                timeout=timeout,
                year=roc_year,
                season="04",
            )
            docs[key] = (document, meta)
            sources.append(meta)
            if meta.get("status") != "PASS":
                errors.append(f"MOPS {key} {period}: {meta.get('status')}")
            for metric, metric_aliases in aliases.items():
                _add_metric(
                    fields,
                    canonical_name=f"annual.{period}.{metric}",
                    aliases=metric_aliases,
                    document=document,
                    source_meta=meta,
                    period=period,
                    unit=(document or {}).get("unit"),
                )
    latest_roc, latest_season = latest_quarter
    prior_roc = f"{int(latest_roc) - 1:03d}"
    for roc_year in (latest_roc, prior_roc):
        period = f"{1911 + int(roc_year):04d}-Q{int(latest_season)}"
        for key, aliases in (("income", income_aliases), ("balance", balance_aliases), ("cashflow", cashflow_aliases)):
            document, meta, _ = _fetch_mops(
                "cashflow" if key == "cashflow" else key,
                market_type=market_type,
                code=code,
                allowed_hosts=allowed_hosts,
                timeout=timeout,
                year=roc_year,
                season=latest_season,
            )
            sources.append(meta)
            if meta.get("status") != "PASS":
                errors.append(f"MOPS {key} {period}: {meta.get('status')}")
            for metric, metric_aliases in aliases.items():
                _add_metric(
                    fields,
                    canonical_name=f"quarter.{period}.{metric}",
                    aliases=metric_aliases,
                    document=document,
                    source_meta=meta,
                    period=period,
                    unit=(document or {}).get("unit"),
                )
    return annual_periods, errors


def _collect_monthly_revenue(
    *,
    code: str,
    market_type: str,
    latest_year: str,
    latest_month: str,
    allowed_hosts: set[str],
    timeout: int,
    fields: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
    count: int = 3,
) -> tuple[list[str], list[str]]:
    periods: list[str] = []
    errors: list[str] = []
    for year, month in reversed(month_sequence(latest_year, latest_month, count)):
        period = roc_month_to_period(year, month)
        periods.append(period)
        document, meta, _ = _fetch_mops(
            "monthly",
            market_type=market_type,
            code=code,
            allowed_hosts=allowed_hosts,
            timeout=timeout,
            year=year,
            month=month,
        )
        sources.append(meta)
        if document is None or not meta.get("period_match"):
            errors.append(f"MOPS monthly revenue {period}: unavailable")
        _add_metric(
            fields,
            canonical_name=f"monthly_revenue.{period}.current",
            aliases=("本月", "營業收入淨額"),
            document=document,
            source_meta=meta,
            period=period,
            unit=(document or {}).get("unit"),
        )
        _add_metric(
            fields,
            canonical_name=f"monthly_revenue.{period}.prior_year_same_month",
            aliases=("去年同期",),
            document=document,
            source_meta=meta,
            period=period,
            value_index=0,
            unit=(document or {}).get("unit"),
        )
    return periods, errors


def _latest_period_from_row(row: dict[str, Any], field_names: tuple[str, ...]) -> str | None:
    value = next((row.get(key) for key in field_names if row.get(key) not in (None, "")), None)
    text = str(value).strip() if value is not None else ""
    return text if text else None


def _record_for_code(
    *,
    code: str,
    entity: dict[str, Any],
    as_of: str,
    allowed_hosts: set[str],
    timeout: int,
) -> dict[str, Any]:
    market = entity["market"]
    market_type = "sii" if market == "TWSE" else "otc"
    fields: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    errors: list[str] = []

    valuation_payload, valuation_meta, _ = _fetch_json(
        SOURCE_IDS[market]["valuation"],
        SOURCE_URLS[market]["valuation"],
        allowed_hosts=allowed_hosts,
        timeout=timeout,
        target_code=code,
    )
    sources.append(valuation_meta)
    valuation = exchanges.parse_valuation_payload(valuation_payload or [], market=market) if valuation_payload is not None else {}
    valuation_row = valuation.get(code, {})
    for canonical, label, value, unit in [
        ("current_pe", "PEratio/PriceEarningRatio", valuation_row.get("pe"), "倍"),
        ("current_pb", "PBratio/PriceBookRatio", valuation_row.get("pb"), "倍"),
        ("current_yield", "DividendYield/YieldRatio", valuation_row.get("yield"), "percent"),
    ]:
        fields[canonical] = build_field(
            canonical_name=canonical,
            source_label=label,
            value=value,
            unit=unit,
            source_id=valuation_meta["source_id"],
            source_url=valuation_meta["source_url"],
            period=str(valuation_row.get("date") or as_of),
            raw_snapshot_id=valuation_meta["raw_snapshot_id"],
            reason=None if value is not None else "current valuation field missing",
        )

    monthly_payload, monthly_meta, _ = _fetch_json(
        SOURCE_IDS[market]["monthly"],
        SOURCE_URLS[market]["monthly"],
        allowed_hosts=allowed_hosts,
        timeout=timeout,
        target_code=code,
    )
    sources.append(monthly_meta)
    monthly_rows = exchanges._rows(monthly_payload) if monthly_payload is not None else []
    monthly_row = next((row for row in monthly_rows if _code_from_row(row) == code), {})
    latest_month_raw = _latest_period_from_row(monthly_row, ("資料年月",)) or ""
    if not re.fullmatch(r"\d{5}", latest_month_raw):
        latest_month_raw = "11507"
        errors.append("latest monthly period unavailable; default period not used for scoring")
    latest_year, latest_month = latest_month_raw[:3], latest_month_raw[3:]
    monthly_yoy = None
    try:
        monthly_yoy = _parse_float(monthly_row.get("營業收入-去年同月增減(%)"))
    except ValueError:
        errors.append("current monthly revenue YoY malformed")
    fields["latest_monthly_revenue_yoy"] = build_field(
        canonical_name="latest_monthly_revenue_yoy",
        source_label="營業收入-去年同月增減(%)",
        value=monthly_yoy,
        unit="percent",
        source_id=monthly_meta["source_id"],
        source_url=monthly_meta["source_url"],
        period=roc_month_to_period(latest_year, latest_month),
        raw_snapshot_id=monthly_meta["raw_snapshot_id"],
        reason=None if monthly_yoy is not None else "current monthly revenue YoY missing",
    )

    income_payload, income_meta, _ = _fetch_json(
        SOURCE_IDS[market]["income"],
        SOURCE_URLS[market]["income"],
        allowed_hosts=allowed_hosts,
        timeout=timeout,
        target_code=code,
    )
    sources.append(income_meta)
    income_rows = exchanges._rows(income_payload) if income_payload is not None else []
    income_row = next((row for row in income_rows if _code_from_row(row) == code), {})
    quarter_year = str(income_row.get("年度") or income_row.get("Year") or "115")
    quarter_no = str(income_row.get("季別") or income_row.get("Season") or "2").zfill(2)
    latest_quarter = (quarter_year, quarter_no)
    current_quarter_period = f"{1911 + int(quarter_year):04d}-Q{int(quarter_no)}"
    for metric, label_keys in {
        "gross_profit": ("營業毛利（毛損）淨額", "營業毛利（毛損）"),
        "operating_income": ("營業利益（損失）",),
        "pretax_income": ("稅前淨利（淨損）",),
        "after_tax_income": ("本期淨利（淨損）",),
    }.items():
        raw = next((income_row.get(key) for key in label_keys if key in income_row), None)
        try:
            value = _parse_float(raw)
            reason = None if value is not None else "latest quarter income field missing"
        except ValueError as exc:
            value, reason = None, str(exc)
        fields[f"latest_quarter.{metric}"] = build_field(
            canonical_name=f"latest_quarter.{metric}",
            source_label=label_keys[0],
            value=value,
            unit="NTD_thousand",
            source_id=income_meta["source_id"],
            source_url=income_meta["source_url"],
            period=current_quarter_period,
            raw_snapshot_id=income_meta["raw_snapshot_id"],
            reason=reason,
        )

    # Current balance gives a dated cross-check; historical balance is collected below.
    balance_payload, balance_meta, _ = _fetch_json(
        SOURCE_IDS[market]["balance"],
        SOURCE_URLS[market]["balance"],
        allowed_hosts=allowed_hosts,
        timeout=timeout,
        target_code=code,
    )
    sources.append(balance_meta)
    balance_rows = exchanges._rows(balance_payload) if balance_payload is not None else []
    balance_row = next((row for row in balance_rows if _code_from_row(row) == code), {})
    for canonical, label_keys in {
        "current_equity": ("權益總計",),
        "current_receivables": ("應收帳款淨額",),
        "current_inventory": ("存貨",),
        "current_noncurrent_liabilities": ("非流動負債",),
    }.items():
        raw = next((balance_row.get(key) for key in label_keys if key in balance_row), None)
        try:
            value = _parse_float(raw)
            reason = None if value is not None else "current balance field missing"
        except ValueError as exc:
            value, reason = None, str(exc)
        fields[canonical] = build_field(
            canonical_name=canonical,
            source_label=label_keys[0],
            value=value,
            unit="NTD_thousand",
            source_id=balance_meta["source_id"],
            source_url=balance_meta["source_url"],
            period=current_quarter_period,
            raw_snapshot_id=balance_meta["raw_snapshot_id"],
            reason=reason,
        )

    annual_start = max(1, int(quarter_year) - 5)
    annual_years = [f"{year:03d}" for year in range(int(quarter_year) - 1, annual_start - 1, -1)]
    annual_years.sort()
    annual_periods, financial_errors = _collect_financial_history(
        code=code,
        market_type=market_type,
        annual_years=annual_years,
        latest_quarter=latest_quarter,
        allowed_hosts=allowed_hosts,
        timeout=timeout,
        fields=fields,
        sources=sources,
    )
    errors.extend(financial_errors)
    monthly_periods, monthly_errors = _collect_monthly_revenue(
        code=code,
        market_type=market_type,
        latest_year=latest_year,
        latest_month=latest_month,
        allowed_hosts=allowed_hosts,
        timeout=timeout,
        fields=fields,
        sources=sources,
    )
    errors.extend(monthly_errors)
    insider_periods, insider_errors = _collect_insider_history(
        code=code,
        market_type=market_type,
        latest_year=latest_year,
        latest_month=latest_month,
        allowed_hosts=allowed_hosts,
        timeout=timeout,
        fields=fields,
        sources=sources,
    )
    errors.extend(insider_errors)
    tdcc_periods, tdcc_errors = _collect_tdcc_history(
        code=code,
        allowed_hosts=allowed_hosts,
        timeout=timeout,
        fields=fields,
        sources=sources,
    )
    errors.extend(tdcc_errors)

    if market == "TWSE":
        valuation_history_url = SOURCE_URLS[market]["valuation_history"].format(date="20260904")
        _, valuation_history_meta, _ = _fetch_json(
            SOURCE_IDS[market]["valuation_history"],
            valuation_history_url,
            allowed_hosts=allowed_hosts,
            timeout=timeout,
            target_code=code,
        )
        sources.append(valuation_history_meta)
        price_url = SOURCE_URLS[market]["price_history"].format(yyyymm01="20260901", code=code)
        _, price_meta, _ = _fetch_json(
            SOURCE_IDS[market]["price_history"],
            price_url,
            allowed_hosts=allowed_hosts,
            timeout=timeout,
        )
        sources.append(price_meta)

    for source in sources:
        source.setdefault("status", "UNKNOWN")
    source_failures = sum(1 for source in sources if source.get("status") not in {"PASS"})
    source_reasons = [
        f"{source.get('source_id')}: {source.get('status')} ({source.get('error_type', 'no error type')})"
        for source in sources
        if source.get("status") not in {"PASS"}
    ]
    errors.extend(source_reasons)
    unknown_fields = sorted(key for key, field in fields.items() if field.get("status") != "PASS")
    coverage_status = "PASS" if not errors and source_failures == 0 else "UNKNOWN"
    return {
        "entity": entity,
        "as_of": as_of,
        "sources": sources,
        "fields": fields,
        "history": {
            "annual_periods": annual_periods,
            "latest_quarter_period": current_quarter_period,
            "monthly_revenue_periods": monthly_periods,
            "insider_periods": insider_periods,
            "tdcc_shareholder_periods": tdcc_periods,
        },
        "coverage": {
            "status": coverage_status,
            "source_count": len(sources),
            "field_count": len(fields),
            "source_failures": source_failures,
            "unknown_field_count": len(unknown_fields),
            "unknown_field_sample": unknown_fields[:20],
            "reasons": sorted(set(errors)),
        },
    }


def validate_collection(collection: Any) -> None:
    if not isinstance(collection, dict):
        raise ValueError("collection must be an object")
    required = {"schema_version", "collector_version", "run_at_utc", "as_of", "records"}
    missing = required - collection.keys()
    if missing:
        raise ValueError(f"collection missing keys: {', '.join(sorted(missing))}")
    if collection["schema_version"] != SCHEMA_VERSION:
        raise ValueError("unsupported collection schema")
    if not str(collection["run_at_utc"]).endswith("Z"):
        raise ValueError("run_at_utc must end in Z")
    records = collection["records"]
    if not isinstance(records, list):
        raise ValueError("collection.records must be a list")
    seen: set[str] = set()
    forbidden_keys = {"raw_html", "raw_body", "cookie", "cookies", "token", "password", "authorization"}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("record must be an object")
        entity = record.get("entity")
        if not isinstance(entity, dict):
            raise ValueError("record.entity must be an object")
        code = str(entity.get("code", ""))
        if code in seen:
            raise ValueError(f"duplicate record code: {code}")
        seen.add(code)
        if entity.get("ordinary_share") is not True:
            raise ValueError("record entity must be ordinary share")
        for key in record:
            if key.lower() in forbidden_keys:
                raise ValueError(f"raw/secret field is forbidden: {key}")
        fields = record.get("fields")
        if not isinstance(fields, dict):
            raise ValueError("record.fields must be an object")
        for key, field in fields.items():
            if not isinstance(field, dict) or field.get("canonical_name") != key:
                raise ValueError(f"field key mismatch: {key}")
            validate_field_record(field)
        if not isinstance(record.get("sources"), list):
            raise ValueError("record.sources must be a list")
        if not isinstance(record.get("coverage"), dict):
            raise ValueError("record.coverage must be an object")


def _load_entities(
    codes: list[str], *, allowed_hosts: set[str], timeout: int
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    entities: dict[str, dict[str, Any]] = {}
    source_meta: list[dict[str, Any]] = []
    for market in ("TWSE", "TPEx"):
        source_id = SOURCE_IDS[market]["basic"]
        payload, meta, _ = _fetch_json(
            source_id,
            SOURCE_URLS[market]["basic"],
            allowed_hosts=allowed_hosts,
            timeout=timeout,
        )
        source_meta.append(meta)
        rows = exchanges._rows(payload) if payload is not None else []
        normalized = exchanges.normalize_company_rows(rows, market)
        for row in normalized:
            if row["code"] in codes:
                if row["code"] in entities:
                    raise ValueError(f"market overlap for code {row['code']}")
                entities[row["code"]] = row
    missing = sorted(set(codes) - set(entities))
    if missing:
        raise ValueError(f"requested codes absent from official universe: {','.join(missing)}")
    return entities, source_meta


def collect_public_snapshot(codes: list[str], *, as_of: str, timeout: int) -> dict[str, Any]:
    if not codes:
        raise ValueError("at least one code is required")
    if any(not re.fullmatch(r"[1-9]\d{3}", code) for code in codes):
        raise ValueError("codes must be four-digit ordinary-share codes")
    if len(set(codes)) != len(codes):
        raise ValueError("codes must be unique")
    registry = load_source_registry()
    allowed_hosts = set(registry["policy"]["allowed_hosts"])
    entities, basic_sources = _load_entities(codes, allowed_hosts=allowed_hosts, timeout=timeout)
    records = []
    for code in codes:
        record = _record_for_code(
            code=code,
            entity=entities[code],
            as_of=as_of,
            allowed_hosts=allowed_hosts,
            timeout=timeout,
        )
        record["sources"] = [
            {
                **source,
                "role": "entity_universe",
            }
            for source in basic_sources
            if source.get("status") == "PASS"
        ] + record["sources"]
        records.append(record)
    collection = {
        "schema_version": SCHEMA_VERSION,
        "collector_version": COLLECTOR_VERSION,
        "formula_version": FORMULA_VERSION,
        "run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "as_of": as_of,
        "scope": "two-code-public-source-smoke",
        "free_fallback_transport_calls": 0,
        "records": records,
    }
    validate_collection(collection)
    return collection


def write_collection(path: Path, collection: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, path)
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codes", default="2330,6488")
    parser.add_argument("--as-of", default=datetime.now(timezone.utc).date().isoformat())
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    codes = [code.strip() for code in args.codes.split(",") if code.strip()]
    collection = collect_public_snapshot(codes, as_of=args.as_of, timeout=args.timeout)
    write_collection(args.out, collection)
    summary = {
        "out": str(args.out),
        "records": len(collection["records"]),
        "field_counts": {r["entity"]["code"]: len(r["fields"]) for r in collection["records"]},
        "coverage": {r["entity"]["code"]: r["coverage"] for r in collection["records"]},
        "free_fallback_transport_calls": collection["free_fallback_transport_calls"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
