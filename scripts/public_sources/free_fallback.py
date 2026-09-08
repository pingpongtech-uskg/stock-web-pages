"""Free-quota fallback budget guard for FinMind and yfinance."""
from __future__ import annotations

from dataclasses import dataclass

ALLOWED_PROVIDERS = frozenset({"FinMind", "yfinance"})


@dataclass
class BudgetLedger:
    provider: str
    allocated_requests: int
    reserved_requests: int = 0
    used_requests: int = 0
    status: str = "ready"
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.provider not in ALLOWED_PROVIDERS:
            raise ValueError("provider is not an allowed free fallback")
        if not isinstance(self.allocated_requests, int) or self.allocated_requests < 0:
            raise ValueError("allocated request budget must be a non-negative integer")

    @property
    def remaining_requests(self) -> int:
        return self.allocated_requests - self.used_requests - self.reserved_requests

    def consume(self) -> None:
        if self.status != "ready":
            raise ValueError("budget is blocked")
        if self.reserved_requests <= 0:
            self.status = "blocked"
            self.reason = "transport attempted without a reserved request"
            raise ValueError("request was not reserved")
        self.reserved_requests -= 1
        self.used_requests += 1

    def release(self, count: int = 1) -> None:
        if count < 0 or count > self.reserved_requests:
            raise ValueError("release exceeds reserved requests")
        self.reserved_requests -= count


def reserve_budget(ledger: BudgetLedger, request_count: int) -> None:
    if not isinstance(request_count, int) or request_count < 0:
        raise ValueError("request count must be a non-negative integer")
    if ledger.status != "ready":
        raise ValueError("budget is blocked")
    if request_count > ledger.remaining_requests:
        ledger.status = "blocked"
        ledger.reason = "free request budget exhausted before transport"
        raise ValueError("request budget is insufficient")
    ledger.reserved_requests += request_count


def safe_provider_error(error: BaseException) -> str:
    """Return exception type only; never expose token/URL/provider messages."""
    return type(error).__name__
