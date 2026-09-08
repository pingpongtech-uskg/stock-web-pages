"""Normalize public-provider records into :mod:`public_data_models`.

This module accepts the canonical fact-list format and the compact snapshot
format produced by the Phase-B public collector.  It never chooses a value
silently when two providers disagree.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from .public_data_models import (
    CompanyData,
    DividendRecord,
    Fact,
    Status,
    as_date,
    finite_number,
    stable_hash,
)


@dataclass(frozen=True)
class NormalizationResult:
    companies: tuple[CompanyData, ...]
    conflicts: tuple[dict[str, Any], ...] = ()
    errors: tuple[str, ...] = ()


def normalize_code(value: Any) -> str:
    """Keep stock-code leading zeros even when an input parser gave an int."""
    if value is None:
        raise ValueError("company code is required")
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    if not text.isdigit():
        raise ValueError(f"company code is not numeric: {value!r}")
    if len(text) < 4:
        text = text.zfill(4)
    if len(text) > 6:
        raise ValueError(f"company code has too many digits: {value!r}")
    return text


def infer_period_type(period: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    if re.fullmatch(r"\d{4}-FY", period):
        return "annual"
    if re.fullmatch(r"\d{4}-Q[1-4]", period):
        return "quarterly"
    if re.fullmatch(r"\d{4}-\d{2}", period):
        return "monthly"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", period):
        return "daily"
    if period.endswith("-DIV"):
        return "dividend"
    return "point_in_time"


def _clean_status(value: Any, numeric_value: float | None) -> Status:
    if value is None:
        return Status.PASS if numeric_value is not None else Status.UNKNOWN
    text = str(value).strip().lower()
    aliases = {"pass": Status.PASS, "true": Status.PASS, "fail": Status.FAIL, "false": Status.FAIL, "unknown": Status.UNKNOWN, "blocked": Status.UNKNOWN, "not_applicable": Status.NOT_APPLICABLE, "n/a": Status.NOT_APPLICABLE}
    if text not in aliases:
        raise ValueError(f"unknown fact status: {value!r}")
    return aliases[text]


def _date_or_none(value: Any) -> date | None:
    if value in (None, "", "unknown", "Unknown", "null", "None"):
        return None
    return as_date(value)


def _fact_from_mapping(
    mapping: Mapping[str, Any],
    *,
    field_name: str | None = None,
    default_period: str | None = None,
    default_period_type: str | None = None,
    defaults: Mapping[str, Any] | None = None,
) -> tuple[str, Fact]:
    base = dict(defaults or {})
    base.update(mapping)
    normalized_field = str(base.get("normalized_field") or base.get("field") or field_name or "").strip()
    if not normalized_field:
        raise ValueError("fact normalized_field is required")
    period = str(base.get("period") or default_period or "").strip()
    if not period:
        raise ValueError(f"fact period is required for {normalized_field}")
    raw_value = base.get("value")
    value = finite_number(raw_value)
    if raw_value not in (None, "", "-", "—", "－", "N/A", "NA") and value is None:
        raise ValueError(f"fact value is not numeric for {normalized_field}/{period}")
    status = _clean_status(base.get("status"), value)
    if status in {Status.UNKNOWN, Status.NOT_APPLICABLE, Status.FAIL}:
        value = None
    source_payload = dict(base)
    content_sha256 = str(base.get("content_sha256") or base.get("raw_snapshot_id") or stable_hash(source_payload))
    if not content_sha256.startswith("sha256:"):
        content_sha256 = "sha256:" + content_sha256
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", content_sha256):
        content_sha256 = stable_hash(source_payload)
    source_url = str(base.get("source_url") or "https://invalid.local/source")
    fact = Fact(
        value=value,
        period=period,
        period_type=infer_period_type(period, base.get("period_type") or default_period_type),
        announced_at=_date_or_none(base.get("announced_at") or base.get("published_at")),
        observed_at=_date_or_none(base.get("observed_at") or base.get("market_date")),
        source_id=str(base.get("source_id") or "unknown.source"),
        source_url=source_url,
        provider=str(base.get("provider") or "unknown"),
        raw_field_name=str(base.get("raw_field_name") or normalized_field),
        normalized_field=normalized_field,
        unit=str(base.get("unit") or ""),
        content_sha256=content_sha256,
        proxy=bool(base.get("proxy", False) or base.get("formula_type") == "transparent_proxy"),
        statement_scope=str(base.get("statement_scope") or base.get("scope") or "unknown"),
        formula_version=str(base.get("formula_version") or "public-data-health-v1"),
        status=status,
        reason=base.get("reason"),
    )
    return normalized_field, fact


def _iter_fact_mappings(raw: Any, *, default_field: str | None = None) -> Iterable[tuple[str | None, Mapping[str, Any] | Any]]:
    if isinstance(raw, list):
        for item in raw:
            yield default_field, item
        return
    if isinstance(raw, Mapping):
        if any(key in raw for key in ("value", "period", "normalized_field", "field")):
            yield default_field, raw
            return
        for period, value in raw.items():
            if isinstance(value, Mapping) and any(key in value for key in ("value", "period", "normalized_field", "field")):
                item = dict(value)
                item.setdefault("period", period)
                yield default_field, item
            else:
                yield default_field, {"period": period, "value": value}
        return
    yield default_field, raw


def _add_fact_mapping(
    facts: dict[str, list[Fact]],
    raw: Any,
    *,
    default_field: str | None = None,
    defaults: Mapping[str, Any] | None = None,
) -> None:
    for field_name, item in _iter_fact_mappings(raw, default_field=default_field):
        if isinstance(item, Mapping):
            mapping = dict(item)
        else:
            mapping = {"value": item}
        if field_name and "normalized_field" not in mapping and "field" not in mapping:
            mapping["normalized_field"] = field_name
        key, fact = _fact_from_mapping(mapping, defaults=defaults)
        facts.setdefault(key, []).append(fact)


def _legacy_period(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{7}", text):
        return f"{1911 + int(text[:3]):04d}-{text[3:5]}-{text[5:7]}"
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if re.fullmatch(r"\d{6}", text) and int(text[:2]) >= 19:
        return f"{text[:4]}-{text[4:6]}"
    if re.fullmatch(r"\d{5}", text):
        return f"{1911 + int(text[:3]):04d}-{text[3:5]}"
    return text


def _legacy_field_mapping(name: str, field: Mapping[str, Any], root: Mapping[str, Any]) -> tuple[str, str, str] | None:
    """Map Phase-B compact fields into canonical scorer field names."""
    match = re.fullmatch(r"annual\.(\d{4}-FY)\.(.+)", name)
    if match:
        return match.group(2), match.group(1), "annual"
    match = re.fullmatch(r"quarter\.(\d{4}-Q[1-4])\.(.+)", name)
    if match:
        return match.group(2), match.group(1), "quarterly"
    match = re.fullmatch(r"monthly_revenue\.(\d{4}-\d{2})\.(current|prior_year_same_month)", name)
    if match:
        mapped = "monthly_revenue" if match.group(2) == "current" else "prior_year_same_month_revenue"
        return mapped, match.group(1), "monthly"
    match = re.fullmatch(r"tdcc\.shareholder_count\.(\d{4}-\d{2})", name)
    if match:
        return "shareholder_count", match.group(1), "monthly"
    match = re.fullmatch(r"insider\.(\d{4}-\d{2})\.(.+)", name)
    if match:
        label = match.group(2)
        if "大股東" in label:
            return "major_holder_shares", match.group(1), "monthly"
        if "董事" in label or "監察人" in label:
            return "director_supervisor_aggregate_holdings", match.group(1), "monthly"
    current_map = {
        "current_pe": "pe",
        "current_pb": "pb",
        "current_yield": "dividend_yield",
        "latest_monthly_revenue_yoy": "monthly_revenue_yoy",
    }
    if name in current_map:
        period = _legacy_period(field.get("period") or root.get("market_date") or "")
        if not period:
            return None
        if re.fullmatch(r"\d{6}", period):
            period = f"{period[:4]}-{period[4:6]}"
        if re.fullmatch(r"\d{8}", period):
            period = f"{period[:4]}-{period[4:6]}-{period[6:]}"
        return current_map[name], period, "daily" if name.startswith("current_") else "monthly"
    match = re.fullmatch(r"latest_quarter\.(.+)", name)
    if match:
        period = str(field.get("period") or "")
        return match.group(1), period, "quarterly" if period else "quarterly"
    return None


def _legacy_fields(raw: Mapping[str, Any], facts: dict[str, list[Fact]]) -> None:
    fields = raw.get("fields")
    if not isinstance(fields, Mapping):
        return
    root_defaults = {
        "market_date": raw.get("as_of") or raw.get("market_date"),
        "statement_scope": raw.get("statement_scope") or "unknown",
    }
    for legacy_name, field in fields.items():
        if not isinstance(field, Mapping):
            continue
        mapped = _legacy_field_mapping(str(legacy_name), field, raw)
        if mapped is None:
            continue
        normalized_name, period, period_type = mapped
        mapping = {
            "normalized_field": normalized_name,
            "period": period,
            "period_type": period_type,
            "value": field.get("value"),
            "status": str(field.get("status") or "unknown").lower(),
            "reason": field.get("reason"),
            "source_id": field.get("source_id"),
            "source_url": field.get("source_url"),
            "provider": field.get("provider") or "unknown",
            "raw_field_name": field.get("source_label") or legacy_name,
            "unit": field.get("unit"),
            "published_at": field.get("published_at"),
            "observed_at": raw.get("as_of"),
            "statement_scope": raw.get("statement_scope") or "unknown",
        }
        try:
            _add_fact_mapping(facts, mapping)
        except ValueError:
            # A malformed legacy field is reported by the caller through errors;
            # do not turn it into a fabricated numeric fact.
            continue


def _dividend_from_mapping(raw: Mapping[str, Any]) -> DividendRecord:
    value = finite_number(raw.get("cash_per_share", raw.get("value")))
    if value is None:
        raise ValueError("dividend cash_per_share must be numeric")
    year = int(raw.get("attribution_year", raw.get("fiscal_year")))
    content = str(raw.get("content_sha256") or stable_hash(dict(raw)))
    if not content.startswith("sha256:"):
        content = "sha256:" + content
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", content):
        content = stable_hash(dict(raw))
    return DividendRecord(
        attribution_year=year,
        cash_per_share=value,
        ex_date=_date_or_none(raw.get("ex_date")),
        announced_at=_date_or_none(raw.get("announced_at") or raw.get("published_at")),
        special=bool(raw.get("special", False)),
        source_id=str(raw.get("source_id") or "unknown.dividend"),
        source_url=str(raw.get("source_url") or "https://invalid.local/dividend"),
        content_sha256=content,
        proxy=bool(raw.get("proxy", False)),
    )


def normalize_record(raw: Mapping[str, Any]) -> CompanyData:
    if not isinstance(raw, Mapping):
        raise ValueError("company record must be an object")
    entity_raw = raw.get("entity")
    entity: Mapping[str, Any] = entity_raw if isinstance(entity_raw, Mapping) else {}
    code = normalize_code(raw.get("company_code", raw.get("code", entity.get("code"))))
    market = str(raw.get("market", entity.get("market", "")))
    name = str(raw.get("company_name", raw.get("name", entity.get("name", code))))
    facts: dict[str, list[Fact]] = {}
    defaults = {
        "market_date": raw.get("market_date") or raw.get("as_of"),
        "announced_at": raw.get("announced_at"),
        "statement_scope": raw.get("statement_scope") or raw.get("scope") or "unknown",
        "provider": raw.get("provider") or "unknown",
    }
    raw_facts = raw.get("facts")
    if isinstance(raw_facts, list):
        for item in raw_facts:
            if isinstance(item, Mapping):
                _add_fact_mapping(facts, item, defaults=defaults)
    elif isinstance(raw_facts, Mapping):
        for field_name, values in raw_facts.items():
            _add_fact_mapping(facts, values, default_field=str(field_name), defaults=defaults)
    for collection_name, period_type in (("annual", "annual"), ("quarterly", "quarterly"), ("monthly", "monthly"), ("prices", "daily"), ("valuations", "daily")):
        collection = raw.get(collection_name)
        if not isinstance(collection, Mapping):
            continue
        for period, values in collection.items():
            if not isinstance(values, Mapping):
                continue
            for field_name, value in values.items():
                _add_fact_mapping(
                    facts,
                    {"normalized_field": str(field_name), "period": str(period), "period_type": period_type, "value": value},
                    defaults=defaults,
                )
    _legacy_fields(raw, facts)
    dividends: list[DividendRecord] = []
    for item in raw.get("dividends", ()) if isinstance(raw.get("dividends"), list) else ():
        if isinstance(item, Mapping):
            dividends.append(_dividend_from_mapping(item))
    metadata = dict(raw.get("metadata") or {})
    for key in ("industry_group", "industry", "universe_complete", "eligible", "data_quality", "source_status"):
        if key in raw:
            metadata[key] = raw[key]
        if key in entity:
            metadata[key] = entity[key]
    listing_date = raw.get("listing_date", entity.get("listing_date"))
    company_market_date = raw.get("market_date") or raw.get("as_of") or entity.get("market_date")
    return CompanyData(
        company_code=code,
        market=market,
        company_name=name,
        market_date=company_market_date,
        listing_date=listing_date,
        statement_scope=str(raw.get("statement_scope") or raw.get("scope") or "unknown"),
        facts=facts,
        dividends=dividends,
        metadata=metadata,
    )


def _merge_companies(left: CompanyData, right: CompanyData) -> tuple[CompanyData, list[dict[str, Any]]]:
    if (left.company_code, left.market) != (right.company_code, right.market):
        raise ValueError("cannot merge different companies")
    merged: dict[str, list[Fact]] = {key: list(values) for key, values in left.facts.items()}
    conflicts: list[dict[str, Any]] = []
    for field_name, values in right.facts.items():
        for fact in values:
            same = [old for old in merged.get(field_name, []) if old.period == fact.period]
            for old in same:
                if old.value != fact.value:
                    conflicts.append({"company_code": left.company_code, "market": left.market, "normalized_field": field_name, "period": fact.period, "values": [old.value, fact.value], "sources": [old.source_id, fact.source_id], "status": "data_conflict"})
            if not any(old.value == fact.value and old.period == fact.period and old.source_id == fact.source_id for old in same):
                merged.setdefault(field_name, []).append(fact)
    existing_dividend_keys = {(item.attribution_year, item.ex_date, item.cash_per_share) for item in left.dividends}
    dividends = list(left.dividends) + [item for item in right.dividends if (item.attribution_year, item.ex_date, item.cash_per_share) not in existing_dividend_keys]
    metadata = dict(left.metadata)
    metadata.update(right.metadata)
    return CompanyData(
        company_code=left.company_code,
        market=left.market,
        company_name=left.company_name or right.company_name,
        market_date=left.market_date or right.market_date,
        listing_date=left.listing_date or right.listing_date,
        statement_scope=left.statement_scope if left.statement_scope != "unknown" else right.statement_scope,
        facts=merged,
        dividends=dividends,
        metadata=metadata,
    ), conflicts


def normalize_records(records: Iterable[Mapping[str, Any]]) -> NormalizationResult:
    by_key: dict[tuple[str, str], CompanyData] = {}
    conflicts: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw in enumerate(records):
        try:
            company = normalize_record(raw)
        except Exception as exc:
            errors.append(f"record[{index}]: {type(exc).__name__}: {exc}")
            continue
        key = (company.company_code, company.market)
        if key in by_key:
            by_key[key], new_conflicts = _merge_companies(by_key[key], company)
            conflicts.extend(new_conflicts)
        else:
            by_key[key] = company
    companies = tuple(by_key[key] for key in sorted(by_key))
    return NormalizationResult(companies=companies, conflicts=tuple(conflicts), errors=tuple(errors))


def _read_json_file(path: Path) -> list[Mapping[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        result = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, Mapping):
                raise ValueError(f"{path}:{line_number} JSONL row is not object")
            result.append(value)
        return result
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("records", "companies", "data"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, Mapping)]
        return [payload]
    raise ValueError(f"{path} JSON root is not object/list")


def load_records(path: str | Path) -> NormalizationResult:
    root = Path(path)
    raw_records: list[Mapping[str, Any]] = []
    errors: list[str] = []
    if root.is_file():
        try:
            raw_records.extend(_read_json_file(root))
        except Exception as exc:
            return NormalizationResult((), errors=(f"{root}: {type(exc).__name__}: {exc}",))
    elif root.is_dir():
        files = sorted(item for item in root.rglob("*") if item.is_file() and item.suffix.lower() in {".json", ".jsonl"} and not item.name.endswith(".tmp"))
        for file in files:
            try:
                raw_records.extend(_read_json_file(file))
            except Exception as exc:
                errors.append(f"{file}: {type(exc).__name__}: {exc}")
    else:
        return NormalizationResult((), errors=(f"input path does not exist: {root}",))
    result = normalize_records(raw_records)
    return NormalizationResult(result.companies, result.conflicts, tuple(errors) + result.errors)


def company_to_record(company: CompanyData) -> dict[str, Any]:
    facts = [fact.to_dict() for field_name in sorted(company.facts) for fact in company.facts[field_name]]
    for item in facts:
        item["normalized_field"] = item["normalized_field"] or item["raw_field_name"]
    return {
        "market": company.market,
        "company_code": company.company_code,
        "company_name": company.company_name,
        "market_date": company.market_day.isoformat() if company.market_day else None,
        "listing_date": company.listed_day.isoformat() if company.listed_day else None,
        "statement_scope": company.statement_scope,
        "facts": facts,
        "dividends": [item.to_dict() for item in company.dividends],
        "metadata": dict(company.metadata),
    }
