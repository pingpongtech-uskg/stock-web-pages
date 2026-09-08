#!/usr/bin/env python3
"""Validate the public-source and 7x33 criterion registries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

EXPECTED_COUNTS = {
    "safety": 6,
    "dividend": 5,
    "growth": 5,
    "value": 6,
    "turnaround": 3,
    "continuity": 5,
    "chip": 3,
}
EXPECTED_MAPPING = {
    "bomb": "safety",
    "cd": "dividend",
    "growth": "growth",
    "cheap": "value",
    "turnaround": "turnaround",
    "quality": "continuity",
    "chip": "chip",
}


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def validate_criteria(registry: dict) -> dict:
    errors: list[str] = []
    groups = registry.get("groups")
    if not isinstance(groups, list):
        errors.append("criteria.groups must be a list")
        groups = []

    seen_ids: set[str] = set()
    seen_groups: set[str] = set()
    counts: dict[str, int] = {}
    for group in groups:
        if not isinstance(group, dict):
            errors.append("criteria group must be an object")
            continue
        group_id = group.get("id")
        if not isinstance(group_id, str) or not group_id:
            errors.append("criteria group has no id")
            continue
        if group_id in seen_groups:
            errors.append(f"duplicate group id: {group_id}")
        seen_groups.add(group_id)
        criteria = group.get("criteria")
        if not isinstance(criteria, list):
            errors.append(f"{group_id}.criteria must be a list")
            criteria = []
        counts[group_id] = len(criteria)
        for criterion in criteria:
            if not isinstance(criterion, dict):
                errors.append(f"{group_id} criterion must be an object")
                continue
            criterion_id = criterion.get("id")
            if not isinstance(criterion_id, str) or not criterion_id:
                errors.append(f"{group_id} criterion has no id")
                continue
            if criterion_id in seen_ids:
                errors.append(f"duplicate criterion id: {criterion_id}")
            seen_ids.add(criterion_id)
            if not criterion_id.startswith(group_id + "."):
                errors.append(f"criterion {criterion_id} is outside group {group_id}")
            for key in ("label", "formula", "source_families", "definition_status"):
                if key not in criterion:
                    errors.append(f"{criterion_id} missing {key}")
            if not isinstance(criterion.get("source_families"), list) or not criterion.get("source_families"):
                errors.append(f"{criterion_id}.source_families must be non-empty")

    if set(counts) != set(EXPECTED_COUNTS):
        errors.append(f"group ids mismatch: got {sorted(counts)}, expected {sorted(EXPECTED_COUNTS)}")
    if counts != EXPECTED_COUNTS:
        errors.append(f"group counts mismatch: got {counts}, expected {EXPECTED_COUNTS}")
    total = sum(counts.values())
    if registry.get("total_criteria") != 33 or total != 33 or len(seen_ids) != 33:
        errors.append(f"total criteria mismatch: registry={registry.get('total_criteria')} counted={total} unique={len(seen_ids)}")
    mapping = registry.get("reference", {}).get("mapping")
    if mapping != EXPECTED_MAPPING:
        errors.append(f"reference mapping mismatch: got {mapping}, expected {EXPECTED_MAPPING}")
    if registry.get("status_model") != ["PASS", "FAIL", "UNKNOWN", "BLOCKED"]:
        errors.append("status_model must be PASS/FAIL/UNKNOWN/BLOCKED")
    return {"ok": not errors, "errors": errors, "group_counts": counts, "total_criteria": len(seen_ids)}


def validate_sources(registry: dict) -> dict:
    errors: list[str] = []
    policy = registry.get("policy")
    if not isinstance(policy, dict):
        errors.append("source.policy must be an object")
        policy = {}
    allowed = set(policy.get("allowed_hosts", []))
    if not allowed:
        errors.append("source.policy.allowed_hosts is empty")
    if policy.get("paid_api") is not False:
        errors.append("paid_api must be false")
    if policy.get("production_browser_dependency") is not False:
        errors.append("production_browser_dependency must be false")
    if not policy.get("free_quota_budget_required"):
        errors.append("free_quota_budget_required must be true")
    if set(policy.get("free_fallbacks", [])) != {"FinMind", "yfinance"}:
        errors.append("free_fallbacks must include exactly FinMind and yfinance")
    sources = registry.get("sources")
    if not isinstance(sources, list):
        errors.append("source.sources must be a list")
        sources = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            errors.append("source entry must be an object")
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id:
            errors.append("source entry has no id")
        elif source_id in seen:
            errors.append(f"duplicate source id: {source_id}")
        else:
            seen.add(source_id)
        url = source.get("url")
        if not isinstance(url, str) or not url:
            errors.append(f"{source_id}: missing url")
            continue
        parsed = urlsplit(url.replace("{code}", "0000").replace("{YYYYMMDD}", "20260101").replace("{YYYYMM01}", "20260101"))
        if parsed.scheme not in {"https"}:
            errors.append(f"{source_id}: URL must use HTTPS")
        if parsed.hostname not in allowed:
            errors.append(f"{source_id}: host {parsed.hostname!r} is not allow-listed")
        if any(secret_word in url.lower() for secret_word in ("password", "token=", "cookie", "authorization")):
            errors.append(f"{source_id}: secret-bearing URL")
        if source.get("probe") == "conditional_free_fallback":
            if not source.get("budget_required"):
                errors.append(f"{source_id}: free fallback lacks budget_required")
            if source.get("authority") != "secondary_free_source":
                errors.append(f"{source_id}: free fallback authority must be secondary_free_source")
    return {"ok": not errors, "errors": errors, "source_count": len(sources), "unique_source_ids": len(seen)}


def validate_files(criteria_path: Path, source_path: Path) -> dict:
    criteria_result = validate_criteria(_load(criteria_path))
    source_result = validate_sources(_load(source_path))
    result = {
        "ok": criteria_result["ok"] and source_result["ok"],
        "criteria": criteria_result,
        "sources": source_result,
    }
    if not result["ok"]:
        raise ValueError(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--criteria", type=Path, default=root / "calibration" / "criteria_registry.json")
    parser.add_argument("--sources", type=Path, default=root / "calibration" / "source_registry.json")
    args = parser.parse_args()
    result = validate_files(args.criteria, args.sources)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
