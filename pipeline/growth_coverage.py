"""Versioned, conserving diagnostics for the independent growth strategy."""
from __future__ import annotations

import math
from typing import Any, Iterable

from pipeline.growth_health import growth_health_qualifies
from pipeline.release_contract import is_common_stock_code

GROWTH_COVERAGE_VERSION = "growth-coverage-v1"
GROWTH_THRESHOLD = 1.2
TERMINAL_OUTCOMES = (
    "missing",
    "knownInvalid",
    "extreme",
    "belowThreshold",
    "healthBlocked",
    "selected",
)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _growth_health_passes(detail: dict[str, Any]) -> bool:
    """Require the five named checks and count only explicit passes."""
    categories = detail.get("healthCategories")
    if not isinstance(categories, list):
        return False
    category = next(
        (row for row in categories if isinstance(row, dict) and row.get("key") == "growth"),
        None,
    )
    return growth_health_qualifies(category)


def _known_invalid(valuation: dict[str, Any]) -> bool:
    if valuation.get("status") in {"invalid", "known_invalid", "known-invalid"}:
        return True
    for key in ("current_price", "current_pe", "ttm_eps", "earnings_growth"):
        value = _finite_number(valuation.get(key))
        if value is not None and value <= 0:
            return True
    dividend = _finite_number(valuation.get("dividend_yield"))
    if dividend is not None and dividend < 0:
        return True
    audit = valuation.get("inputAudit")
    if isinstance(audit, dict):
        ttm = audit.get("ttmEps")
        growth = audit.get("earningsGrowth")
        if isinstance(ttm, dict) and ttm.get("reason") == "nonpositive_ttm_eps":
            return True
        if isinstance(growth, dict) and growth.get("reason") == "完整年度 EPS 包含非正值":
            return True
    return False


def _reason_counts(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for detail in rows:
        valuation = detail.get("growthValuation")
        if not isinstance(valuation, dict):
            continue
        reasons = valuation.get("missingReasons")
        if not isinstance(reasons, list):
            continue
        excluded: set[str] = set()
        for key, metric in (
            ("price", "current_price"),
            ("pe", "current_pe"),
            ("ttmEps", "ttm_eps"),
            ("earningsGrowth", "earnings_growth"),
        ):
            number = _finite_number(valuation.get(metric))
            if number is not None and number <= 0:
                excluded.add(key)
        dividend = _finite_number(valuation.get("dividend_yield"))
        if dividend is not None and dividend < 0:
            excluded.add("dividendYield")
        audit = valuation.get("inputAudit")
        if isinstance(audit, dict):
            ttm = audit.get("ttmEps")
            growth = audit.get("earningsGrowth")
            if isinstance(ttm, dict) and ttm.get("reason") == "nonpositive_ttm_eps":
                excluded.add("ttmEps")
            if isinstance(growth, dict) and growth.get("reason") == "完整年度 EPS 包含非正值":
                excluded.add("earningsGrowth")
        for reason in {
            reason.strip()
            for reason in reasons
            if isinstance(reason, str) and reason.strip() and reason.strip() not in excluded
        }:
            counts[reason] = counts.get(reason, 0) + 1
    return [{"reason": reason, "count": counts[reason]} for reason in sorted(counts)]


def build_growth_coverage(
    details: list[dict[str, Any]],
    *,
    universe: int | None = None,
    selected_codes: set[str] | None = None,
) -> dict[str, Any]:
    """Summarize full common-share rows and assign one terminal outcome each.

    ``universe`` is the expected number of official common-share members.
    Members absent from details are counted as missing. ``selected_codes`` is
    the final strategy membership; when omitted it is derived from threshold
    and health eligibility.
    """
    if not isinstance(details, list):
        raise ValueError("growth coverage details must be a list")
    if any(not isinstance(row, dict) for row in details):
        raise ValueError("growth coverage details must contain objects")
    rows = [row for row in details if is_common_stock_code(str(row.get("code", "")))]
    codes = [row.get("code", "").strip() if isinstance(row.get("code"), str) else "" for row in rows]
    if any(not code for code in codes) or len(set(codes)) != len(codes):
        raise ValueError("growth coverage common stock codes must be present and unique")
    common_count = len(rows)
    expected = common_count if universe is None else universe
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < common_count:
        raise ValueError("growth coverage universe must be a nonnegative common-share count")

    eligible_codes: set[str] = set()
    outcomes = {key: 0 for key in TERMINAL_OUTCOMES}
    input_complete = valuation_complete = threshold_candidates = health_candidates = 0

    for detail in rows:
        code = str(detail["code"]).strip()
        valuation = detail.get("growthValuation")
        if not isinstance(valuation, dict):
            valuation = {}
        input_complete += valuation.get("inputsComplete") is True
        status = valuation.get("status")
        if status == "extreme":
            outcomes["extreme"] += 1
            continue
        if _known_invalid(valuation):
            if status == "available":
                raise ValueError("available growth valuation contains known-invalid inputs")
            outcomes["knownInvalid"] += 1
            continue
        if status != "available":
            outcomes["missing"] += 1
            continue

        total_return_pe = _finite_number(valuation.get("total_return_pe"))
        if total_return_pe is None:
            raise ValueError("available growth valuation requires finite total_return_pe")
        valuation_complete += 1
        if total_return_pe < GROWTH_THRESHOLD:
            outcomes["belowThreshold"] += 1
            continue
        threshold_candidates += 1
        if not _growth_health_passes(detail):
            outcomes["healthBlocked"] += 1
            continue
        health_candidates += 1
        eligible_codes.add(code)

    if selected_codes is not None and (
        not isinstance(selected_codes, set)
        or any(not isinstance(code, str) or not code.strip() for code in selected_codes)
    ):
        raise ValueError("growth selected_codes must be a set of stock codes")
    selected = eligible_codes if selected_codes is None else {code.strip() for code in selected_codes}
    if selected != eligible_codes:
        raise ValueError("growth selection must equal all threshold and health-qualified rows")
    outcomes["selected"] = len(selected)
    outcomes["missing"] += expected - common_count
    state = (
        "not_evaluable"
        if expected == 0 or outcomes["missing"] == expected
        else "partial"
        if outcomes["missing"] > 0
        else "evaluated"
    )
    result = {
        "growthCoverageVersion": GROWTH_COVERAGE_VERSION,
        "growthEvaluationState": state,
        "growthInputComplete": input_complete,
        "growthValuationComplete": valuation_complete,
        "growthThresholdCandidates": threshold_candidates,
        "growthHealthCandidates": health_candidates,
        "growthCandidates": len(selected),
        "growthMissingReasons": _reason_counts(rows),
        "growthTerminalOutcomes": {"universe": expected, **outcomes},
    }
    errors = validate_growth_coverage(result, expected_universe=expected)
    if errors:
        raise ValueError("invalid growth coverage: " + ",".join(errors))
    return result


def validate_growth_coverage(
    value: Any,
    *,
    expected_universe: int | None = None,
) -> list[str]:
    """Validate required growth coverage fields and conservation rules."""
    if not isinstance(value, dict):
        return ["growth_coverage_type"]
    errors: list[str] = []
    if value.get("growthCoverageVersion") != GROWTH_COVERAGE_VERSION:
        errors.append("growth_coverage_version")
    if value.get("growthEvaluationState") not in {"not_evaluable", "partial", "evaluated"}:
        errors.append("growth_coverage_state")
    count_keys = (
        "growthInputComplete",
        "growthValuationComplete",
        "growthThresholdCandidates",
        "growthHealthCandidates",
        "growthCandidates",
    )
    counts: dict[str, int] = {}
    for key in count_keys:
        count = value.get(key)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append("growth_coverage_count:" + key)
        else:
            counts[key] = count
    reasons = value.get("growthMissingReasons")
    if not isinstance(reasons, list):
        errors.append("growth_coverage_reasons")
    else:
        seen: set[str] = set()
        for reason in reasons:
            if not isinstance(reason, dict) or not isinstance(reason.get("reason"), str) or not reason["reason"]:
                errors.append("growth_coverage_reason_shape")
                continue
            count = reason.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                errors.append("growth_coverage_reason_count")
            if reason["reason"] in seen:
                errors.append("growth_coverage_reason_duplicate")
            seen.add(reason["reason"])

    terminal = value.get("growthTerminalOutcomes")
    terminal_counts: dict[str, int] = {}
    if not isinstance(terminal, dict) or set(terminal) != {"universe", *TERMINAL_OUTCOMES}:
        errors.append("growth_coverage_terminal_shape")
    else:
        for key in ("universe", *TERMINAL_OUTCOMES):
            count = terminal.get(key)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                errors.append("growth_coverage_terminal_count:" + key)
            else:
                terminal_counts[key] = count
        if len(terminal_counts) == len(TERMINAL_OUTCOMES) + 1:
            if any(
                isinstance(reason, dict)
                and isinstance(reason.get("count"), int)
                and not isinstance(reason.get("count"), bool)
                and reason["count"] > terminal_counts["universe"]
                for reason in (reasons if isinstance(reasons, list) else [])
            ):
                errors.append("growth_coverage_reason_exceeds_universe")
            if sum(terminal_counts[key] for key in TERMINAL_OUTCOMES) != terminal_counts["universe"]:
                errors.append("growth_coverage_terminal_conservation")
            if expected_universe is not None and terminal_counts["universe"] != expected_universe:
                errors.append("growth_coverage_universe_mismatch")
            expected_state = (
                "not_evaluable"
                if terminal_counts["universe"] == 0 or terminal_counts["missing"] == terminal_counts["universe"]
                else "partial"
                if terminal_counts["missing"] > 0
                else "evaluated"
            )
            if value.get("growthEvaluationState") != expected_state:
                errors.append("growth_coverage_state_mismatch")
            if terminal_counts["selected"] != counts.get("growthCandidates"):
                errors.append("growth_coverage_selected_mismatch")
            if terminal_counts["selected"] != counts.get("growthHealthCandidates", -1):
                errors.append("growth_coverage_health_mismatch")
            if terminal_counts["healthBlocked"] + terminal_counts["selected"] != counts.get("growthThresholdCandidates", -1):
                errors.append("growth_coverage_threshold_mismatch")
            if terminal_counts["belowThreshold"] + counts.get("growthThresholdCandidates", -1) != counts.get("growthValuationComplete", -1):
                errors.append("growth_coverage_valuation_mismatch")
            if terminal_counts["universe"] < max(counts.values(), default=0):
                errors.append("growth_coverage_count_exceeds_universe")
            if counts.get("growthValuationComplete", -1) > counts.get("growthInputComplete", -1):
                errors.append("growth_coverage_input_mismatch")
    return errors
