"""Pure filtering and public result-shape helpers for the site."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

CATEGORY_FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "全部"),
    ("turnaround", "轉機股 >50%"),
    ("value", "便宜股 >50%"),
    ("growth", "成長股 >50%"),
    ("chip", "籌碼 >50%"),
    ("dividend", "定存股 >50%"),
    ("continuity", "績優股 >50%"),
    ("safety", "排除地雷股 >50%"),
)
CATEGORY_FILTER_IDS = frozenset(key for key, _ in CATEGORY_FILTERS if key != "all")


def category_passes(category: Mapping[str, Any], threshold: float = 0.5) -> bool:
    """Return whether a category has strictly more than threshold pass ratio.

    Unknown/not-applicable criteria remain in the published record and are not
    silently relabelled.  They do not count as pass; therefore a category with
    too much missing data cannot qualify accidentally.
    """
    try:
        passed = int(category.get("passed", 0))
        total = int(category.get("total", 0))
    except (TypeError, ValueError):
        return False
    return total > 0 and passed / total > threshold


def entry_matches_filters(
    entry: Mapping[str, Any],
    *,
    selected_categories: Iterable[str] = (),
    z_max: float = 0.0,
    threshold: float = 0.5,
) -> bool:
    """Apply Z plus AND-combined category filters to one site entry."""
    try:
        z = float(entry.get("regression_z"))
    except (TypeError, ValueError):
        return False
    if z > z_max:
        return False
    selected = {str(value) for value in selected_categories}
    selected.discard("all")
    invalid = selected - CATEGORY_FILTER_IDS
    if invalid:
        raise ValueError(f"unknown category filters: {sorted(invalid)}")
    categories = entry.get("categories") or entry.get("category_scores") or {}
    if not isinstance(categories, Mapping):
        return not selected
    return all(category_passes(categories.get(category, {}), threshold) for category in sorted(selected))


def filter_entries(
    entries: Iterable[Mapping[str, Any]],
    *,
    selected_categories: Iterable[str] = (),
    z_max: float = 0.0,
    threshold: float = 0.5,
) -> list[Mapping[str, Any]]:
    return [entry for entry in entries if entry_matches_filters(entry, selected_categories=selected_categories, z_max=z_max, threshold=threshold)]


def detail_contract(
    *,
    categories: Mapping[str, Any],
    criteria: Iterable[Mapping[str, Any]],
    formula_version: str,
    model_version: str,
    source_snapshot: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the immutable details payload shown on an internal stock page."""
    criteria_list = [dict(item) for item in criteria]
    return {
        "model_version": model_version,
        "formula_version": formula_version,
        "categories": {str(key): dict(value) for key, value in categories.items()},
        "criteria": criteria_list,
        "source_snapshot": sorted({str(value) for value in source_snapshot}),
    }
