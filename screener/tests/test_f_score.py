from __future__ import annotations

from datetime import date

import pytest

from screener.f_score import F_SCORE_ITEM_IDS, calculate_f_score
from screener.tests.factories import annual_series, company


def profitable_annual_facts():
    return annual_series(
        {
            "2022-FY": {
                "net_income": 60,
                "cfo": 70,
                "total_assets": 900,
                "current_assets": 250,
                "current_liabilities": 150,
                "long_term_debt": 350,
                "shares": 100,
                "gross_profit": 330,
                "revenue": 900,
            },
            "2023-FY": {
                "net_income": 80,
                "cfo": 90,
                "total_assets": 1000,
                "current_assets": 300,
                "current_liabilities": 150,
                "long_term_debt": 300,
                "shares": 100,
                "gross_profit": 400,
                "revenue": 1000,
            },
            "2024-FY": {
                "net_income": 120,
                "cfo": 150,
                "total_assets": 1100,
                "current_assets": 400,
                "current_liabilities": 150,
                "long_term_debt": 250,
                "shares": 100,
                "gross_profit": 500,
                "revenue": 1200,
            },
        }
    )


def test_f_score_all_nine_positive():
    result = calculate_f_score(company(facts=profitable_annual_facts()), current_year=2024, as_of=date(2025, 3, 1))
    assert result.score == 9
    assert set(result.items) == set(F_SCORE_ITEM_IDS)
    assert all(item.status.value == "pass" for item in result.items.values())


@pytest.mark.parametrize(
    ("field", "current", "prior", "item_id"),
    [
        ("net_income", -1, 80, "roa_positive"),
        ("cfo", -1, 90, "cfo_positive"),
        ("cfo", 100, 80, "cfo_gt_net_income"),
        ("long_term_debt", 300, 300, "debt_decrease"),
        ("current_assets", 100, 300, "current_ratio_increase"),
        ("shares", 101, 100, "no_new_shares"),
        ("gross_profit", 300, 400, "gross_margin_increase"),
        ("revenue", 800, 1000, "asset_turnover_increase"),
    ],
)
def test_each_f_score_negative_or_boundary_case(
    field: str,
    current: float,
    prior: float,
    item_id: str,
):
    facts = profitable_annual_facts()
    facts[field] = [
        next(item for item in facts[field] if item.period == "2023-FY").__class__(
            **{**next(item for item in facts[field] if item.period == "2023-FY").__dict__, "value": prior}
        ),
        next(item for item in facts[field] if item.period == "2024-FY").__class__(
            **{**next(item for item in facts[field] if item.period == "2024-FY").__dict__, "value": current}
        ),
    ]
    result = calculate_f_score(company(facts=facts), current_year=2024, as_of=date(2025, 3, 1))
    assert result.items[item_id].status.value == "fail"


def test_f_score_zero_denominator_is_unknown_not_fail():
    facts = profitable_annual_facts()
    facts["total_assets"] = [
        facts["total_assets"][0],
        facts["total_assets"][1].__class__(**{**facts["total_assets"][1].__dict__, "value": 0}),
        facts["total_assets"][2].__class__(**{**facts["total_assets"][2].__dict__, "value": 0}),
    ]
    result = calculate_f_score(company(facts=facts), current_year=2024, as_of=date(2025, 3, 1))
    assert result.items["roa_positive"].status.value == "unknown"
    assert result.status.value == "unknown"


def test_financial_company_f_score_is_not_applicable():
    result = calculate_f_score(
        company(facts=profitable_annual_facts(), metadata={"industry_group": "financial"}),
        current_year=2024,
        as_of=date(2025, 3, 1),
    )
    assert result.status.value == "not_applicable"
