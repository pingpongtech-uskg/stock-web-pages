"""Pure transformation from daily institutional candidates to site records."""
from __future__ import annotations

from datetime import date
import math
from typing import Any, Mapping, Sequence

from .public_data_models import CompanyData, Fact, ScoreConfig, as_date, stable_hash
from .statementdog_like_rules import CRITERION_LABELS
from .statementdog_like_scorer import score_company

MODEL_VERSION = "public-data-health-v1"
FORMULA_VERSION = "public-data-health-v1"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _make_fact(
    field: str,
    value: Any,
    *,
    period: str,
    provider: str,
    source_id: str,
    source_url: str,
    observed_at: date,
    content_sha256: str,
) -> Fact | None:
    number = _number(value)
    if number is None:
        return None
    return Fact(
        value=number,
        period=period,
        period_type="daily",
        announced_at=None,
        observed_at=observed_at,
        source_id=source_id,
        source_url=source_url,
        provider=provider,
        raw_field_name=field,
        normalized_field=field,
        unit="ratio" if field in {"pe", "pb"} else "percent",
        content_sha256=content_sha256,
        formula_version=FORMULA_VERSION,
    )


def _company_from_candidate(
    candidate: Mapping[str, Any],
    valuation: Mapping[str, Any] | None,
    master: Mapping[str, Any] | None,
    *,
    as_of: date,
    source_hash: str,
) -> CompanyData:
    code = str(candidate.get("code", ""))
    market = str(candidate.get("market", ""))
    valuation = valuation or {}
    master = master or {}
    source_url = str(valuation.get("source_url") or "https://invalid.local/valuation")
    source_id = str(valuation.get("source_id") or "official.valuation.current")
    facts: dict[str, list[Fact]] = {}
    for field in ("pe", "pb", "dividend_yield"):
        fact = _make_fact(field, valuation.get(field), period=as_of.isoformat(), provider=str(valuation.get("provider") or "official"), source_id=source_id, source_url=source_url, observed_at=as_of, content_sha256=source_hash)
        if fact is not None:
            facts.setdefault(field, []).append(fact)
    price_fact = _make_fact("price", candidate.get("cur_price"), period=as_of.isoformat(), provider="official_market_price", source_id="official.market.close", source_url=str(candidate.get("price_source_url") or "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL"), observed_at=as_of, content_sha256=str(candidate.get("price_content_sha256") or source_hash))
    if price_fact is not None:
        facts.setdefault("price", []).append(price_fact)
    metadata = {
        "universe_complete": True,
        "rank_scope": "daily_institutional_candidate_universe",
        "institutional_source": candidate.get("institutional_source", "official_twse_t86_or_tpex_3insti"),
    }
    if master.get("industry_group"):
        metadata["industry_group"] = master["industry_group"]
    listing_date = master.get("listing_date")
    return CompanyData(
        company_code=code,
        market=market,
        company_name=str(master.get("name") or candidate.get("name") or code),
        market_date=as_of,
        listing_date=listing_date,
        statement_scope="unknown",
        facts=facts,
        metadata=metadata,
    )


def _score_entry(candidate: Mapping[str, Any], score: Any) -> dict[str, Any]:
    payload = score.to_dict()
    criteria = []
    for item in payload["criteria"]:
        enriched = dict(item)
        enriched["label"] = CRITERION_LABELS.get(enriched["criterion_id"], enriched["criterion_id"])
        criteria.append(enriched)
    categories = {}
    for category, value in payload["categories"].items():
        category_payload = dict(value)
        category_payload["criteria"] = [
            next((item for item in criteria if item["criterion_id"] == child["criterion_id"]), dict(child))
            for child in value.get("criteria", [])
        ]
        categories[category] = category_payload
    return {
        "code": str(candidate["code"]),
        "market": str(candidate.get("market", "")),
        "name_zh": str(candidate.get("name") or candidate["code"]),
        "name_en": str(candidate.get("name") or ""),
        "net_amount_10d": candidate.get("net_amount_10d"),
        "net_amount_10d_k": round(float(candidate.get("net_amount_10d", 0)) / 1000, 2),
        "net_shares_10d": candidate.get("net_shares_10d"),
        "net_shares_10d_zhang": round(float(candidate.get("net_shares_10d", 0)) / 1000, 2),
        "last_date": candidate.get("last_date"),
        "window_dates": candidate.get("window_dates", []),
        "window_net_shares": candidate.get("window_net_shares", []),
        "cur_price": candidate.get("cur_price"),
        "regression_z": candidate.get("regression_z"),
        "z_status": "pass" if candidate.get("regression_z") is not None else "unknown",
        "rank": candidate.get("rank"),
        "screening_date": candidate.get("screening_date") or candidate.get("last_date"),
        "institutional_source": candidate.get("institutional_source"),
        "categories": categories,
        "criteria": criteria,
        "data_quality": payload["data_quality"],
        "model_version": payload["model_version"],
        "formula_version": payload["formula_version"],
        "source_snapshot": payload["data_quality"].get("source_snapshots", []),
    }


def build_scored_entries(
    candidates: Sequence[Mapping[str, Any]],
    valuations: Mapping[str, Mapping[str, Any]],
    masters: Mapping[str, Mapping[str, Any]],
    *,
    as_of: date | str,
    config: ScoreConfig | None = None,
) -> list[dict[str, Any]]:
    cutoff = as_date(as_of)
    if cutoff is None:
        raise ValueError("as_of is required")
    config = config or ScoreConfig(universe_complete=True, min_history_observations=20)
    companies = [
        _company_from_candidate(item, valuations.get(str(item.get("code"))), masters.get(str(item.get("code"))), as_of=cutoff, source_hash=stable_hash({"valuation": valuations.get(str(item.get("code"))), "master": masters.get(str(item.get("code")))}))
        for item in candidates
    ]
    scored: list[dict[str, Any]] = []
    for candidate, company in zip(candidates, companies):
        scored.append(_score_entry(candidate, score_company(company, companies, as_of=cutoff, config=config)))
    return scored


def filter_by_z(entries: Sequence[Mapping[str, Any]], z_max: float = 0.0) -> list[dict[str, Any]]:
    result = []
    for entry in entries:
        z = _number(entry.get("regression_z"))
        if z is not None and z <= z_max:
            result.append(dict(entry))
    return result


def build_site_payload(
    entries: Sequence[Mapping[str, Any]],
    *,
    as_of: date | str,
    z_max: float = 0.0,
    archive: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    cutoff = as_date(as_of)
    if cutoff is None:
        raise ValueError("as_of is required")
    records = [dict(entry) for entry in entries]
    active = filter_by_z(records, z_max)
    return {
        "schema_version": 2,
        "model_version": MODEL_VERSION,
        "formula_version": FORMULA_VERSION,
        "market_date": cutoff.isoformat(),
        "z_default": z_max,
        "z_options": [0, 1, 2],
        "category_filter_options": [
            {"id": "all", "label": "全部"},
            {"id": "turnaround", "label": "轉機股 >50%"},
            {"id": "value", "label": "便宜股 >50%"},
            {"id": "growth", "label": "成長股 >50%"},
            {"id": "chip", "label": "籌碼 >50%"},
            {"id": "dividend", "label": "定存股 >50%"},
            {"id": "continuity", "label": "績優股 >50%"},
            {"id": "safety", "label": "排除地雷股 >50%"},
        ],
        "filter_semantics": {"category_combination": "AND", "category_ratio": "passed / total > 0.5", "all": "no category restriction", "unknown": "not a pass"},
        "records": records,
        "active": active,
        "archive": {key: list(value) for key, value in (archive or {}).items()},
    }
