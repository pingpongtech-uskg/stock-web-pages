from __future__ import annotations

from datetime import date

from screener.public_data_models import Fact
from screener.statementdog_like_rules import evaluate_criterion
from screener.tests.factories import company, fact


def test_future_annual_value_cannot_drive_fcf_rule():
    facts = {
        "cfo": [fact(100, "2024-FY", "annual", announced_at=date(2026, 1, 1))],
        "capex": [fact(10, "2024-FY", "annual", announced_at=date(2026, 1, 1))],
    }
    result = evaluate_criterion(
        "safety.fcf_mean_positive",
        company(facts=facts),
        [company(facts=facts)],
        as_of=date(2025, 12, 31),
    )
    assert result.status.value == "unknown"


def test_market_price_uses_observed_date_cutoff():
    future = fact(100, "2026-01-01", "daily", announced_at=None, observed_at=date(2026, 1, 1), normalized_field="price")
    data = company(facts={"price": [future]})
    assert data.get_fact("price", "2026-01-01", as_of=date(2025, 12, 31)) is None
