from __future__ import annotations

from datetime import date

from screener.public_data_models import ScoreConfig
from screener.statementdog_like_rules import evaluate_criterion
from screener.tests.factories import annual_series, company, dividend, fact

AS_OF = date(2025, 3, 1)


def test_five_year_fcf_requires_exact_history():
    facts = annual_series(
        {
            "2021-FY": {"cfo": 10, "capex": 2},
            "2022-FY": {"cfo": 10, "capex": 2},
            "2023-FY": {"cfo": 10, "capex": 2},
            "2024-FY": {"cfo": 10, "capex": 2},
        }
    )
    result = evaluate_criterion("safety.fcf_positive_3_of_5", company(facts=facts), [], as_of=AS_OF)
    assert result.status.value == "unknown"


def test_monthly_revenue_uses_latest_three_chronological_months():
    facts = {
        "monthly_revenue": [fact(value, period, "monthly", normalized_field="monthly_revenue") for period, value in [("2025-01", 110), ("2025-02", 120), ("2025-03", 130)]],
        "prior_year_same_month_revenue": [fact(value, period, "monthly", normalized_field="prior_year_same_month_revenue") for period, value in [("2025-01", 100), ("2025-02", 100), ("2025-03", 100)]],
    }
    result = evaluate_criterion("growth.monthly_revenue_yoy_3_consecutive", company(facts=facts), [], as_of=AS_OF)
    assert result.status.value == "pass"
    assert result.details["chronological_periods"] == ["2025-01", "2025-02", "2025-03"]


def test_quarter_rule_matches_same_fiscal_quarter_not_list_position():
    facts = {
        "gross_profit": [
            fact(100, "2023-Q4", "quarterly", normalized_field="gross_profit"),
            fact(150, "2024-Q3", "quarterly", normalized_field="gross_profit"),
            fact(120, "2024-Q4", "quarterly", normalized_field="gross_profit"),
        ]
    }
    result = evaluate_criterion("growth.gross_profit_yoy_gt_0", company(facts=facts), [], as_of=AS_OF)
    assert result.status.value == "pass"
    assert result.details["current_period"] == "2024-Q4"
    assert result.details["prior_period"] == "2023-Q4"


def _five_year_dividends():
    return [
        dividend(2020, 1.0, ex_date=date(2020, 7, 1), announced_at=date(2020, 6, 1)),
        dividend(2021, 1.0, ex_date=date(2021, 7, 1), announced_at=date(2021, 6, 1)),
        dividend(2022, 1.0, ex_date=date(2022, 7, 1), announced_at=date(2022, 6, 1)),
        dividend(2023, 1.0, ex_date=date(2023, 7, 1), announced_at=date(2023, 6, 1)),
        # Announced in 2025 but attributed to 2024.  It must count as 2024.
        dividend(2024, 1.0, ex_date=date(2025, 2, 20), announced_at=date(2025, 2, 15)),
    ]


def test_dividend_uses_attribution_year_not_announcement_year():
    facts = {"price": [fact(10, f"{year}-12-31", "daily", announced_at=None, observed_at=date(year, 12, 31), normalized_field="price") for year in range(2020, 2025)]}
    data = company(facts=facts, dividends=_five_year_dividends())
    result = evaluate_criterion("dividend.consecutive_5y", data, [], as_of=AS_OF)
    assert result.status.value == "pass"
    assert result.details["attribution_years"] == [2020, 2021, 2022, 2023, 2024]


def test_negative_eps_makes_payout_unknown_not_zero():
    facts = annual_series({f"{year}-FY": {"eps": -1 if year == 2022 else 2} for year in range(2020, 2025)})
    result = evaluate_criterion("dividend.payout_mean_gt_50", company(facts=facts, dividends=_five_year_dividends()), [], as_of=AS_OF)
    assert result.status.value == "unknown"


def test_inventory_turnover_uses_cogs_not_revenue():
    facts = {
        "inventory_begin": [fact(200, "2023-Q4", "quarterly", normalized_field="inventory_begin"), fact(100, "2024-Q4", "quarterly", normalized_field="inventory_begin")],
        "inventory_end": [fact(220, "2023-Q4", "quarterly", normalized_field="inventory_end"), fact(110, "2024-Q4", "quarterly", normalized_field="inventory_end")],
        "revenue": [fact(1000, "2023-Q4", "quarterly", normalized_field="revenue"), fact(1000, "2024-Q4", "quarterly", normalized_field="revenue")],
        "gross_profit": [fact(700, "2023-Q4", "quarterly", normalized_field="gross_profit"), fact(900, "2024-Q4", "quarterly", normalized_field="gross_profit")],
    }
    result = evaluate_criterion("safety.inventory_days_not_worse", company(facts=facts), [], as_of=AS_OF, config=ScoreConfig())
    assert result.status.value == "fail"
    assert result.details["denominator"] == "cost_of_goods_sold"
    assert result.details["current_days"] > result.details["prior_year_same_quarter_days"]


def test_pe_percentile_uses_full_twse_tpex_universe_and_valid_values_only():
    target = company("2330", "TWSE", facts={"pe": [fact(2, "2025-03-01", "daily", announced_at=None, observed_at=date(2025, 3, 1), normalized_field="pe")]})
    otc = company("6488", "TPEx", facts={"pe": [fact(4, "2025-03-01", "daily", announced_at=None, observed_at=date(2025, 3, 1), normalized_field="pe")]})
    high = company("1101", "TWSE", facts={"pe": [fact(8, "2025-03-01", "daily", announced_at=None, observed_at=date(2025, 3, 1), normalized_field="pe")]})
    result = evaluate_criterion("value.pe_below_50pct_universe", target, [target, otc, high], as_of=AS_OF, config=ScoreConfig(universe_complete=True))
    assert result.status.value == "pass"
    assert result.details["universe_count"] == 3


def test_pb_top50_is_deterministic_at_boundary():
    universe = []
    for index in range(1, 52):
        code = f"{index:04d}"
        universe.append(company(code, "TWSE" if index % 2 else "TPEx", facts={"pb": [fact(index, "2025-03-01", "daily", announced_at=None, observed_at=date(2025, 3, 1), normalized_field="pb")] }))
    target = next(item for item in universe if item.company_code == "0050")
    result = evaluate_criterion("turnaround.pb_lowest_top50", target, universe, as_of=AS_OF, config=ScoreConfig(universe_complete=True))
    assert result.status.value == "pass"
    assert result.value == 50
    result_51 = evaluate_criterion("turnaround.pb_lowest_top50", universe[-1], universe, as_of=AS_OF, config=ScoreConfig(universe_complete=True))
    assert result_51.status.value == "fail"
