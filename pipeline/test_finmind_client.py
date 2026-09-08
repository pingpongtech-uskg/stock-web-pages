import pytest

from pipeline.finmind_client import BudgetExceeded, RequestBudget


def test_budget_uses_lower_of_hard_cap_and_eighty_percent_remaining():
    budget = RequestBudget(account_limit=600, account_used=1, hard_cap=300)
    assert budget.allowed == 300
    budget.consume()
    assert budget.used == 1


def test_budget_stops_before_an_attempt_past_limit():
    budget = RequestBudget(account_limit=10, account_used=0, hard_cap=300)
    # 80% of the remaining account allowance is the effective ceiling.
    for _ in range(8):
        budget.consume()
    with pytest.raises(BudgetExceeded):
        budget.consume()
