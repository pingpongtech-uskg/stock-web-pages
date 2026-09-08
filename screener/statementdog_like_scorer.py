"""Scoring facade for the transparent public-data seven-category model."""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

from .public_data_models import (
    CATEGORY_COUNTS,
    CATEGORY_ORDER,
    CompanyData,
    CompanyScore,
    ScoreConfig,
    Status,
    as_date,
)
from .statementdog_like_rules import CATEGORY_CRITERIA, build_categories, evaluate_all


def _data_quality(company: CompanyData, results: Sequence[Any]) -> dict[str, Any]:
    known = sum(result.status in {Status.PASS, Status.FAIL} for result in results)
    unknown = sum(result.status == Status.UNKNOWN for result in results)
    not_applicable = sum(result.status == Status.NOT_APPLICABLE for result in results)
    proxy = sum(bool(result.proxy) for result in results)
    source_snapshots = sorted({snapshot for result in results for snapshot in result.source_snapshot})
    return {
        "known_criteria": known,
        "unknown_criteria": unknown,
        "not_applicable_criteria": not_applicable,
        "total_criteria": len(results),
        "coverage": known / len(results) if results else 0.0,
        "proxy_criteria": proxy,
        "source_snapshot_count": len(source_snapshots),
        "source_snapshots": source_snapshots,
        "point_in_time": True,
        "unknown_not_removed_from_denominator": True,
        "universe_complete": company.metadata.get("universe_complete") is True,
    }


def score_company(
    company: CompanyData,
    universe: Sequence[CompanyData],
    *,
    as_of: date | str,
    config: ScoreConfig | None = None,
) -> CompanyScore:
    cutoff = as_date(as_of)
    if cutoff is None:
        raise ValueError("as_of is required")
    config = config or ScoreConfig()
    results = evaluate_all(company, tuple(universe), as_of=cutoff, config=config)
    categories = build_categories(results, config)
    market_date = company.market_day.isoformat() if company.market_day and company.market_day <= cutoff else cutoff.isoformat()
    return CompanyScore(
        company_code=company.company_code,
        market=company.market,
        company_name=company.company_name,
        market_date=market_date,
        model_version=config.model_version,
        formula_version=config.formula_version,
        categories=categories,
        criteria=results,
        data_quality=_data_quality(company, results),
    )


def score_universe(
    companies: Sequence[CompanyData],
    *,
    as_of: date | str,
    config: ScoreConfig | None = None,
) -> list[CompanyScore]:
    config = config or ScoreConfig()
    ordered = sorted(companies, key=lambda item: (item.market, item.company_code))
    return [score_company(company, ordered, as_of=as_of, config=config) for company in ordered]


def scores_to_jsonl(scores: Sequence[CompanyScore]) -> str:
    import json

    return "\n".join(json.dumps(score.to_dict(), ensure_ascii=False, sort_keys=True) for score in scores) + ("\n" if scores else "")


def summary(scores: Sequence[CompanyScore]) -> dict[str, Any]:
    result: dict[str, Any] = {"company_count": len(scores), "categories": {}}
    for category in CATEGORY_ORDER:
        result["categories"][category] = {
            "company_count": len(scores),
            "qualified_count": sum(score.categories[category].status == Status.PASS for score in scores),
            "unknown_count": sum(score.categories[category].status == Status.UNKNOWN for score in scores),
            "scores": {score.company_code: score.categories[category].score for score in scores},
        }
    result["status_counts"] = {
        "pass": sum(all(category.status == Status.PASS for category in score.categories.values()) for score in scores),
        "partial_or_unknown": sum(any(category.status != Status.PASS for category in score.categories.values()) for score in scores),
    }
    return result
