"""Versioned release-contract helpers shared by the publisher and QA.

The funnel stage counts are published by the producer and must conserve.
PEG, growth, trust, and low-position candidates have separate eligibility
rules; the growth route uses its own versioned coverage contract. Deriving
these numbers from an already filtered ranking is impossible here because
the counts come straight from the full enriched universe.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

FUNNEL_VERSION = "funnel-v2-independent-trust-low-position"
INSTRUMENT_POLICY = "peg-strategies-exclude-non-common-codes-v1"

# Common shares never carry a leading zero block; ETF / ETN / warrant codes
# do (0050, 009803, 00980A, 020000, 030398 ...).
NON_COMMON_STOCK_CODE = re.compile(r"^0\d{3,5}[A-Z]?$")

FORMULA_VERSIONS = {
    "regression": "lohas-linear-3.5y-research-v1",
    "valuation": "zulu-peg-eps-growth-v2",
    "growthValuation": "growth-total-return-pe-v1",
    "growthFallback": "growth-proxy-chain-v1",
    "ranking": "three-strategy-tabs-v1",
}
CHIP_REFERENCE_VERSION = "chip-reference-v1"
CHIP_STATUSES = {"pass", "fail", "unknown"}
CHIP_FRESHNESS = {"current", "stale", "unavailable", "unknown"}


def chip_reference_error(value: object, code: str) -> str | None:
    """Validate display-only chip evidence without making it a strategy gate."""
    if not isinstance(value, dict):
        return "chip_reference_missing:" + code
    if value.get("schemaVersion") != CHIP_REFERENCE_VERSION:
        return "chip_reference_schema_version:" + code
    if value.get("displayOnly") is not True:
        return "chip_reference_display_only:" + code
    if value.get("formulaVersion") != CHIP_REFERENCE_VERSION:
        return "chip_reference_formula_version:" + code
    if value.get("dataFreshness") not in CHIP_FRESHNESS:
        return "chip_reference_freshness:" + code
    if value.get("status") not in CHIP_STATUSES:
        return "chip_reference_status:" + code
    for key in ("largeHolderTrend", "directorSupervisor12m", "shareholderCountTrend"):
        child = value.get(key)
        if not isinstance(child, dict) or child.get("status") not in CHIP_STATUSES:
            return f"chip_reference_indicator:{key}:{code}"
        if not isinstance(child.get("value"), str) or not child["value"]:
            return f"chip_reference_indicator_value:{key}:{code}"
        if not isinstance(child.get("period"), str) or not child["period"]:
            return f"chip_reference_indicator_period:{key}:{code}"
        child_refs = child.get("sourceRefs")
        if not isinstance(child_refs, list) or any(not isinstance(ref, str) or not ref for ref in child_refs):
            return f"chip_reference_indicator_source_refs:{key}:{code}"
    refs = value.get("sourceRefs")
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs):
        return "chip_reference_source_refs:" + code
    return None


def is_common_stock_code(code: str) -> bool:
    """Return False for ETF/ETN/warrant-style codes (leading zero block)."""

    return not bool(NON_COMMON_STOCK_CODE.match(str(code).strip()))


def is_proxy_valuation(valuation: dict[str, Any]) -> bool:
    """A valuation is a proxy when its growth input is explicitly labelled."""

    return "proxy" in str(valuation.get("growth_method") or "") or "代理" in str(
        valuation.get("growth_method_label") or ""
    )


def compute_funnel(
    *,
    universe: int,
    price_complete: int,
    instrument_excluded: int,
    valuations: Iterable[dict[str, Any]],
    strategy_counts: dict[str, int],
    growth_candidates: int | None = None,
    growth_valuation_complete: int | None = None,
) -> dict[str, Any]:
    """Build the published funnel and fail loudly when it does not conserve."""

    values = [value for value in valuations if isinstance(value, dict)]
    peg_count = sum(1 for value in values if value.get("below_075"))
    proxy_count = sum(1 for value in values if is_proxy_valuation(value))
    counts = {str(key): int(value) for key, value in strategy_counts.items()}
    if peg_count > len(values) or proxy_count > len(values):
        raise ValueError("funnel stage counts do not conserve")
    if growth_candidates is not None and counts.get("growth", 0) > growth_candidates:
        raise ValueError("growth route exceeds growth valuation pool")
    return {
        "version": FUNNEL_VERSION,
        "universe": int(universe),
        "priceComplete": int(price_complete),
        "valuationComplete": len(values),
        "growthValuationComplete": int(growth_valuation_complete if growth_valuation_complete is not None else 0),
        "pegCandidates": peg_count,
        "growthCandidates": int(growth_candidates if growth_candidates is not None else counts.get("growth", 0)),
        "strategyCandidates": counts,
        "formalValuations": len(values) - proxy_count,
        "proxyValuations": proxy_count,
        "instrumentPolicy": INSTRUMENT_POLICY,
        "instrumentExcluded": int(instrument_excluded),
    }


def growth_coverage_error(
    funnel: Any,
    *,
    required: bool = False,
    expected_universe: int | None = None,
) -> str | None:
    """Validate the independent growth-coverage-v1 contract in a funnel.

    The generic funnel keeps its existing version because it also describes
    trust and low-position. Legacy funnels may omit the entire new diagnostic
    group; a v1 marker requires every field and all cross-count invariants.
    """
    if not isinstance(funnel, dict):
        return "growth_coverage_funnel_type"
    from pipeline.growth_coverage import GROWTH_COVERAGE_VERSION, validate_growth_coverage

    marker = funnel.get("growthCoverageVersion")
    v1_fields = {
        "growthEvaluationState",
        "growthInputComplete",
        "growthThresholdCandidates",
        "growthHealthCandidates",
        "growthMissingReasons",
        "growthTerminalOutcomes",
    }
    present_v1_fields = v1_fields.intersection(funnel)
    if marker is None and not present_v1_fields:
        return "growth_coverage_required" if required else None
    if marker != GROWTH_COVERAGE_VERSION:
        return "growth_coverage_version"
    if expected_universe is None:
        return "growth_coverage_universe_source"
    result = validate_growth_coverage(funnel, expected_universe=expected_universe)
    return result[0] if result else None


def common_share_universe(funnel: Any) -> int | None:
    """Return the generic universe less explicitly excluded instruments."""
    if not isinstance(funnel, dict):
        return None
    universe = funnel.get("universe")
    excluded = funnel.get("instrumentExcluded")
    if (
        not isinstance(universe, int)
        or isinstance(universe, bool)
        or not isinstance(excluded, int)
        or isinstance(excluded, bool)
        or universe < 0
        or excluded < 0
        or excluded > universe
    ):
        return None
    return universe - excluded
