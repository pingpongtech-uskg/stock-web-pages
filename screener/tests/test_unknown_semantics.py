from __future__ import annotations

from datetime import date

from screener.statementdog_like_rules import evaluate_criterion
from screener.statementdog_like_scorer import score_company
from screener.tests.factories import company, fact


def test_missing_required_data_is_unknown_not_fail():
    result = evaluate_criterion(
        "safety.fcf_positive_3_of_5",
        company(facts={}),
        [company(facts={})],
        as_of=date(2025, 3, 1),
    )
    assert result.status.value == "unknown"
    assert result.value is None


def test_proxy_fact_is_marked_on_result():
    result = evaluate_criterion(
        "chip.major_holder_ratio_up_3m",
        company(
            facts={
                "major_holder_ratio": [
                    fact(0.10, "2025-01", "monthly", proxy=True, normalized_field="major_holder_ratio"),
                    fact(0.11, "2025-02", "monthly", proxy=True, normalized_field="major_holder_ratio"),
                    fact(0.12, "2025-03", "monthly", proxy=True, normalized_field="major_holder_ratio"),
                ]
            }
        ),
        [],
        as_of=date(2025, 3, 1),
    )
    assert result.status.value == "pass"
    assert result.proxy is True


def test_same_input_is_deterministic():
    data = company(
        facts={
            "pb": [fact(2.0, "2025-03-01", "daily", announced_at=None, normalized_field="pb")],
        }
    )
    first = score_company(data, [data], as_of=date(2025, 3, 1)).to_dict()
    second = score_company(data, [data], as_of=date(2025, 3, 1)).to_dict()
    assert first == second
