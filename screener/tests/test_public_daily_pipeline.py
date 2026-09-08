from __future__ import annotations

from datetime import date

from screener.public_daily_pipeline import build_scored_entries, filter_by_z


def _candidate(code: str, market: str, price: float, z: float | None) -> dict:
    return {
        "code": code,
        "market": market,
        "name": f"name-{code}",
        "cur_price": price,
        "net_shares_10d": 1000,
        "net_amount_10d": 1000 * price,
        "last_date": "2026-09-08",
        "window_dates": ["2026-08-26", "2026-09-08"],
        "window_net_shares": [500, 500],
        "regression_z": z,
    }


def test_build_entries_contains_all_33_criterion_details_and_category_summary():
    candidates = [_candidate("2330", "TWSE", 1000, -0.5), _candidate("6488", "TPEx", 100, -1.0)]
    valuations = {
        "2330": {"pe": 10.0, "pb": 1.0, "dividend_yield": 2.0},
        "6488": {"pe": 20.0, "pb": 4.0, "dividend_yield": 1.0},
    }
    masters = {
        "2330": {"name": "台積電", "listing_date": "1994-09-05", "market": "TWSE"},
        "6488": {"name": "環球晶", "listing_date": "2015-09-25", "market": "TPEx"},
    }
    entries = build_scored_entries(candidates, valuations, masters, as_of=date(2026, 9, 8))
    assert len(entries) == 2
    assert all(len(entry["criteria"]) == 33 for entry in entries)
    assert all(set(entry["categories"]) == {"turnaround", "value", "growth", "chip", "dividend", "continuity", "safety"} for entry in entries)
    assert entries[0]["categories"]["turnaround"]["criteria"]
    assert entries[0]["data_quality"]["unknown_criteria"] >= 0
    assert entries[0]["formula_version"] == "public-data-health-v1"


def test_filter_by_z_default_is_zero_and_unknown_is_not_pass():
    entries = [
        _candidate("2330", "TWSE", 1000, -0.1),
        _candidate("6488", "TPEx", 100, 0.1),
        _candidate("1101", "TWSE", 20, None),
    ]
    assert [row["code"] for row in filter_by_z(entries, 0)] == ["2330"]
    assert [row["code"] for row in filter_by_z(entries, 1)] == ["2330", "6488"]
