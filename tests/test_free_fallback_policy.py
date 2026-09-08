from __future__ import annotations

import pytest

from scripts.public_sources.free_fallback import BudgetLedger, reserve_budget, safe_provider_error


def test_budget_reserve_and_consume_tracks_exact_counts():
    ledger = BudgetLedger(provider="yfinance", allocated_requests=2)
    reserve_budget(ledger, 2)
    assert ledger.reserved_requests == 2
    ledger.consume()
    assert ledger.used_requests == 1
    assert ledger.reserved_requests == 1
    assert ledger.remaining_requests == 0
    ledger.consume()
    assert ledger.status == "ready"
    assert ledger.used_requests == 2


def test_budget_overrun_blocks_before_transport():
    ledger = BudgetLedger(provider="FinMind", allocated_requests=1)
    with pytest.raises(ValueError, match="budget"):
        reserve_budget(ledger, 2)
    assert ledger.status == "blocked"
    assert ledger.used_requests == 0
    assert ledger.reserved_requests == 0


def test_consume_without_reservation_is_blocked():
    ledger = BudgetLedger(provider="yfinance", allocated_requests=1)
    with pytest.raises(ValueError, match="reserved"):
        ledger.consume()
    assert ledger.status == "blocked"
    assert ledger.used_requests == 0


def test_only_named_free_fallback_providers_are_allowed():
    with pytest.raises(ValueError, match="provider"):
        BudgetLedger(provider="paid-api", allocated_requests=1)


def test_provider_errors_are_type_only():
    safe = safe_provider_error(RuntimeError("token=secret-value password=hunter2"))
    assert safe == "RuntimeError"
    assert "secret" not in safe
    assert "hunter2" not in safe
