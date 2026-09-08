from __future__ import annotations

import pytest

from screener.public_filtering import CATEGORY_FILTERS, category_passes, entry_matches_filters, filter_entries


def _entry(code: str, z: float, **passed: int) -> dict:
    categories = {
        name: {"passed": value, "failed": 3 - value, "unknown": 0, "total": 3}
        for name, value in passed.items()
    }
    return {"code": code, "regression_z": z, "categories": categories}


def test_eight_filter_options_are_declared():
    assert len(CATEGORY_FILTERS) == 8
    assert CATEGORY_FILTERS[0] == ("all", "全部")
    assert {key for key, _ in CATEGORY_FILTERS} == {"all", "turnaround", "value", "growth", "chip", "dividend", "continuity", "safety"}


def test_category_requires_strictly_more_than_fifty_percent():
    assert category_passes({"passed": 2, "total": 3}) is True
    assert category_passes({"passed": 1, "total": 2}) is False
    assert category_passes({"passed": 1, "total": 3, "unknown": 2}) is False


def test_multiple_category_filters_use_and_semantics():
    entry = _entry("2330", -0.4, growth=2, safety=2, value=1)
    assert entry_matches_filters(entry, selected_categories=["growth", "safety"], z_max=0) is True
    assert entry_matches_filters(entry, selected_categories=["growth", "value"], z_max=0) is False


def test_all_is_no_category_restriction_but_z_still_applies():
    entry = _entry("2330", -0.4)
    assert entry_matches_filters(entry, selected_categories=["all"], z_max=0) is True
    assert entry_matches_filters(entry, selected_categories=["all"], z_max=-1) is False


def test_unknown_z_is_not_a_pass():
    entry = _entry("2330", None)
    assert entry_matches_filters(entry, selected_categories=["all"], z_max=0) is False


def test_invalid_category_filter_is_diagnostic():
    with pytest.raises(ValueError, match="unknown category"):
        entry_matches_filters(_entry("2330", -1), selected_categories=["bad"], z_max=0)
