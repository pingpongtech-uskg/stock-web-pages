"""Guarded FinMind HTTP client.

The client is deliberately small and stdlib-only so the data boundary can run in
GitHub Actions without a browser or a hidden dependency. It counts every HTTP
attempt, honors the account budget, and stops rather than working around quota
or rate-limit responses.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any

DATA_URL = "https://api.finmindtrade.com/api/v4/data"
USER_INFO_URL = "https://api.web.finmindtrade.com/v2/user_info"
USER_AGENT = "taiwan-stock-screener/0.1 (research snapshot; no browser API access)"


class FinMindError(RuntimeError):
    """Base error for a guarded FinMind operation."""


class BudgetExceeded(FinMindError):
    """The run budget was exhausted before another HTTP attempt."""


class SourceBlocked(FinMindError):
    """FinMind returned a quota/rate-limit response; caller must keep the queue."""


@dataclass
class RequestBudget:
    account_limit: int
    account_used: int
    hard_cap: int = 300
    initial_used: int = 0

    def __post_init__(self) -> None:
        remaining = max(0, self.account_limit - self.account_used)
        account_ceiling = math.floor(remaining * 0.8)
        run_ceiling = max(0, self.hard_cap - self.initial_used)
        self.allowed = min(run_ceiling, account_ceiling)
        self.used = self.initial_used

    allowed: int = 0
    used: int = 0

    def consume(self) -> None:
        if self.used >= self.allowed + self.initial_used:
            raise BudgetExceeded(
                f"FinMind run budget exhausted: {self.used}/{self.allowed + self.initial_used} attempts"
            )
        self.used += 1

    @property
    def remaining(self) -> int:
        return max(0, self.allowed + self.initial_used - self.used)


@dataclass
class FinMindStats:
    attempts: int
    successful_requests: int
    blocked: bool
    blocked_reason: str | None
    account_limit: int
    account_used_at_start: int
    allowed_attempts: int


class FinMindClient:
    def __init__(
        self,
        token: str,
        *,
        hard_cap: int = 300,
        timeout: float = 30.0,
        max_attempts: int = 3,
        min_interval: float = 0.35,
        daily_budget: Any = None,
    ) -> None:
        token = token.strip()
        if not token:
            raise FinMindError("FINMIND_TOKEN is empty")
        self.token = token
        self.hard_cap = hard_cap
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.min_interval = min_interval
        self._last_request_at = 0.0
        self.daily_budget = daily_budget
        self._initial_attempts = daily_budget.used if daily_budget else 0
        self.budget: RequestBudget | None = None
        self.successful_requests = 0
        self.blocked = False
        self.blocked_reason: str | None = None
        self.account_limit: int | None = None
        self.account_used_at_start: int | None = None

    @classmethod
    def from_env(cls) -> "FinMindClient":
        token = os.environ.get("FINMIND_TOKEN", "")
        client = cls(token)
        client.configure_account_budget()
        return client

    def configure_account_budget(self) -> dict[str, Any]:
        """Read account usage before data calls; fail closed if unavailable."""
        checks_started_at = self.daily_budget.used if self.daily_budget else self._initial_attempts
        info = self._request_json(USER_INFO_URL, {}, count_attempt=True)
        try:
            limit = int(info["api_request_limit"])
            used = int(info["user_count"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FinMindError("FinMind user_info did not expose a usable request budget") from exc
        if limit <= 0 or used < 0:
            raise FinMindError("FinMind user_info returned an invalid request budget")
        if self.daily_budget:
            self.daily_budget.configure(limit, used, checks_started_at=checks_started_at)
        self.account_limit = limit
        self.account_used_at_start = used
        self.budget = RequestBudget(
            account_limit=limit,
            account_used=used,
            hard_cap=self.hard_cap,
            initial_used=self._initial_attempts,
        )
        return info

    def stats(self) -> FinMindStats:
        budget = self.budget
        if budget is None or self.account_limit is None or self.account_used_at_start is None:
            raise FinMindError("FinMind budget has not been configured")
        return FinMindStats(
            attempts=self.daily_budget.used if self.daily_budget else budget.used,
            successful_requests=self.successful_requests,
            blocked=self.blocked,
            blocked_reason=self.blocked_reason,
            account_limit=self.account_limit,
            account_used_at_start=self.account_used_at_start,
            allowed_attempts=self.daily_budget.allowance if self.daily_budget else budget.allowed + budget.initial_used,
        )

    def get(
        self,
        dataset: str,
        *,
        data_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.budget is None:
            raise FinMindError("FinMind account budget has not been configured")
        params: dict[str, str] = {"dataset": dataset}
        if data_id:
            params["data_id"] = data_id
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        payload = self._request_json(DATA_URL, params, count_attempt=True)
        status = payload.get("status")
        if status in (402, 429) or str(status) in {"402", "429"}:
            self._block(f"API response status {status}")
        if status not in (200, "200"):
            raise FinMindError(f"FinMind dataset {dataset} failed with status {status}")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise FinMindError(f"FinMind dataset {dataset} returned a non-list data field")
        return [row for row in rows if isinstance(row, dict)]

    def _block(self, reason: str, retry_after: float | None = None) -> None:
        if self.daily_budget:
            self.daily_budget.block(reason, retry_after)
        self.blocked = True
        self.blocked_reason = reason
        raise SourceBlocked(f"FinMind source stopped: {reason}")

    def _wait_for_rate(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def _retry_after(self, headers: Any) -> float | None:
        value = headers.get("Retry-After") if headers is not None else None
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            try:
                parsed = parsedate_to_datetime(value)
                return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                return None

    def _request_json(self, url: str, params: dict[str, str], *, count_attempt: bool) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            if self.blocked:
                raise SourceBlocked(self.blocked_reason or "FinMind source is blocked")
            # Check and checkpoint the budget after waits, immediately before HTTP.
            self._wait_for_rate()
            if count_attempt:
                if self.daily_budget:
                    self.daily_budget.consume(require_known=url == DATA_URL)
                elif self.budget is None and self._initial_attempts >= self.hard_cap:
                    raise BudgetExceeded("FinMind daily request allowance exhausted")
                if self.budget is None:
                    self._initial_attempts += 1
                else:
                    self.budget.consume()
            query = urllib.parse.urlencode(params)
            request = urllib.request.Request(
                f"{url}?{query}" if query else url,
                headers={"Authorization": f"Bearer {self.token}", "User-Agent": USER_AGENT},
                method="GET",
            )
            self._last_request_at = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        raise FinMindError("FinMind returned a non-object JSON response")
                    if str(payload.get("status")) in {"402", "429"}:
                        self._block(f"API response status {payload['status']}", self._retry_after(response.headers))
                    self.successful_requests += 1
                    return payload
            except SourceBlocked:
                raise
            except urllib.error.HTTPError as exc:
                if exc.code in (402, 429):
                    self._block(f"HTTP {exc.code}", self._retry_after(exc.headers))
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                retry_after = self._retry_after(exc.headers)
                if retry_after is not None and retry_after > 60:
                    self._block(f"HTTP {exc.code}; delayed recovery", retry_after)
                time.sleep(retry_after if retry_after is not None else min(2.0 ** (attempt - 1), 8.0))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, FinMindError) as exc:
                last_error = exc
                if isinstance(exc, FinMindError) and not isinstance(exc, (urllib.error.URLError, TimeoutError)):
                    if attempt >= self.max_attempts:
                        break
                if attempt >= self.max_attempts:
                    break
                time.sleep(min(2.0 ** (attempt - 1), 8.0))
        raise FinMindError(f"FinMind request failed after {self.max_attempts} attempts") from last_error
