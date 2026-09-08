import math

from screener.criteria_engine import evaluate_criteria


GROUP_COUNTS = {
    "safety": 6,
    "dividend": 5,
    "growth": 5,
    "value": 6,
    "turnaround": 3,
    "continuity": 5,
    "chip": 3,
}


def complete_canonical():
    return {
        "provenance": {"source": "official", "source_date": "2025-01-31", "parser_version": "p1"},
        "safety": {
            "fcf": [10, 9, 8, -1, -2],
            "cfo_ni": [120, 110, 101, 110, 110],
            "receivable_days": {"latest": 8, "prior": 9},
            "inventory_days": {"latest": 7, "prior": 8},
        },
        "dividend": {
            "yield_1y": 7,
            "yield_5y_avg": 7,
            "dividend_years": [2024, 2023, 2022, 2021, 2020],
            "payout_ratio": [60, 55, 51, 60, 60],
        },
        "growth": {
            "monthly_revenue_yoy": [1, 2, 3],
            "quarter_yoy": {"gross_profit": 1, "operating_income": 2, "pretax_income": 3, "net_income": 4},
        },
        "value": {"pe_current": 5, "pe_5y": [5, 8, 10, 12, 20], "pe_peer_median": 9,
                  "pb_current": 1, "pb_5y": [1, 2, 3, 4, 5], "pb_peer_median": 2,
                  "yield_1y": 7, "yield_5y_avg": 7},
        "turnaround": {"pb_current": 1, "piotroski": {"years": [2024], "tests": [[True] * 8 + [False]]}, "pb_rank": 50},
        "continuity": {"listed_years": 4, "fcf_return": {"latest": 2, "prior": 1},
                       "fcf_return_rank_3y": 20, "operating_income_3y_sum": 1, "composite_rank": 50},
        "chip": {"major_holder_ownership": [11, 10, 9], "director_holder_months": {"latest": 12, "prior": 11},
                 "shareholder_count": [90, 100, 110]},
    }


def test_complete_input_emits_all_33_criteria_and_numeric_group_totals():
    result = evaluate_criteria(complete_canonical())
    assert set(result["groups"]) == set(GROUP_COUNTS)
    assert sum(len(group["criteria"]) for group in result["groups"].values()) == 33
    for name, count in GROUP_COUNTS.items():
        group = result["groups"][name]
        assert group["count"] == count
        assert isinstance(group["passed"], int)
        assert isinstance(group["pass_ratio"], float)
        assert all(c["status"] in {"PASS", "FAIL", "UNKNOWN"} for c in group["criteria"])


def test_unknown_is_not_a_failed_numeric_result_and_provenance_is_passthrough():
    data = complete_canonical()
    data["safety"]["fcf"] = [1, 2, None, 4, 5]
    result = evaluate_criteria(data)
    criterion = result["groups"]["safety"]["criteria"][0]
    assert criterion["status"] == "UNKNOWN"
    assert result["groups"]["safety"]["passed"] is None
    assert result["groups"]["safety"]["count"] is None
    assert result["groups"]["safety"]["pass_ratio"] is None
    assert result["provenance"] == data["provenance"]


def test_malformed_nonfinite_misaligned_duplicate_and_zero_denominator_are_unknown():
    cases = [
        ("fcf", "not-a-series"),
        ("fcf", [1, 2, 3, 4, math.inf]),
        ("fcf", [1, 2, 3, 4, 5, 6]),
    ]
    for key, value in cases:
        data = complete_canonical()
        data["safety"][key] = value
        assert evaluate_criteria(data)["groups"]["safety"]["criteria"][0]["status"] == "UNKNOWN"

    data = complete_canonical()
    data["dividend"]["dividend_years"] = [2024, 2024, 2022, 2021, 2020]
    assert evaluate_criteria(data)["groups"]["dividend"]["criteria"][2]["status"] == "UNKNOWN"

    data = complete_canonical()
    data["safety"]["cfo_ni"] = [{"cfo": 1, "ni": 0}, {"cfo": 110, "ni": 1}, {"cfo": 101, "ni": 1}, {"cfo": 80, "ni": 1}, {"cfo": 70, "ni": 1}]
    assert evaluate_criteria(data)["groups"]["safety"]["criteria"][2]["status"] == "UNKNOWN"


def test_piotroski_requires_nine_aligned_annual_tests_not_just_a_supplied_score():
    data = complete_canonical()
    data["turnaround"]["piotroski"] = {"f_score": 9}
    assert evaluate_criteria(data)["groups"]["turnaround"]["criteria"][1]["status"] == "UNKNOWN"

    data["turnaround"]["piotroski"] = {"years": [2024, 2023], "tests": [[True] * 9, [True] * 8]}
    assert evaluate_criteria(data)["groups"]["turnaround"]["criteria"][1]["status"] == "UNKNOWN"
