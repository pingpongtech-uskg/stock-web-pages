"""Data contracts for the public-data, seven-category stock scorer.

The scorer deliberately works on normalized facts rather than provider-specific
payloads.  A missing or non-point-in-time fact is unavailable to calculations;
it is never silently converted to zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


PERIOD_TYPES = frozenset({"annual", "quarterly", "monthly", "daily", "dividend", "point_in_time"})
FINANCIAL_PERIOD_TYPES = frozenset({"annual", "quarterly", "monthly", "dividend"})
MARKET_PERIOD_TYPES = frozenset({"daily", "point_in_time"})
DEFAULT_FORMULA_VERSION = "public-data-health-v1"
CATEGORY_ORDER = ("turnaround", "value", "growth", "chip", "dividend", "continuity", "safety")
CATEGORY_COUNTS = {
    "turnaround": 3,
    "value": 6,
    "growth": 5,
    "chip": 3,
    "dividend": 5,
    "continuity": 5,
    "safety": 6,
}


def as_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "null", "none", "n/a"}:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%Y%m%d", "%Y/%m/%d", "%Y-%m", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date()
        except ValueError:
            continue
    raise ValueError(f"invalid date: {value!r}")


def as_datetime(value: date | datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed_date = as_date(text)
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc) if parsed_date else None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def period_sort_key(period: str, period_type: str | None = None) -> tuple[int, int, int, str]:
    text = str(period)
    annual = re.fullmatch(r"(\d{4})-FY", text)
    quarter = re.fullmatch(r"(\d{4})-Q([1-4])", text)
    month = re.fullmatch(r"(\d{4})-(\d{2})", text)
    day = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if annual:
        return int(annual.group(1)), 12, 31, text
    if quarter:
        return int(quarter.group(1)), int(quarter.group(2)) * 3, 1, text
    if month:
        return int(month.group(1)), int(month.group(2)), 1, text
    if day:
        return int(day.group(1)), int(day.group(2)), int(day.group(3)), text
    return (0, 0, 0, text)


def previous_year_period(period: str) -> str:
    match = re.fullmatch(r"(\d{4})(-.+)", period)
    if not match:
        raise ValueError(f"period has no calendar year: {period!r}")
    return f"{int(match.group(1)) - 1:04d}{match.group(2)}"


def add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


@dataclass(frozen=True)
class Fact:
    value: float | None
    period: str
    period_type: str
    announced_at: date | datetime | str | None = None
    observed_at: date | datetime | str | None = None
    source_id: str = "unknown.source"
    source_url: str = "https://invalid.local/source"
    provider: str = "unknown"
    raw_field_name: str = ""
    normalized_field: str = ""
    unit: str = ""
    content_sha256: str = "sha256:" + "0" * 64
    proxy: bool = False
    statement_scope: str = "consolidated"
    formula_version: str = DEFAULT_FORMULA_VERSION
    status: Status = Status.PASS
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.period_type not in PERIOD_TYPES:
            raise ValueError(f"invalid period_type: {self.period_type}")
        if not isinstance(self.period, str) or not self.period:
            raise ValueError("fact period must be non-empty")
        if self.value is not None and finite_number(self.value) is None:
            raise ValueError("fact value must be finite numeric or null")
        status = self.status if isinstance(self.status, Status) else Status(str(self.status))
        object.__setattr__(self, "status", status)
        if self.value is None and status == Status.PASS:
            object.__setattr__(self, "status", Status.UNKNOWN)
        if self.value is not None and status in {Status.UNKNOWN, Status.NOT_APPLICABLE}:
            raise ValueError("non-pass fact cannot contain a numeric value")
        if self.statement_scope not in {"consolidated", "separate", "standalone", "unknown"}:
            raise ValueError("invalid statement_scope")
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", self.content_sha256):
            raise ValueError("content_sha256 must be sha256:<64 hex>")

    @property
    def announced_date(self) -> date | None:
        return as_date(self.announced_at)

    @property
    def observed_date(self) -> date | None:
        return as_date(self.observed_at)

    def is_available_as_of(self, as_of: date | datetime | str, *, require_announcement: bool | None = None) -> bool:
        cutoff = as_date(as_of)
        if cutoff is None or self.status != Status.PASS or self.value is None:
            return False
        if self.observed_date is not None and self.observed_date > cutoff:
            return False
        announcement_required = self.period_type in FINANCIAL_PERIOD_TYPES if require_announcement is None else require_announcement
        if announcement_required and self.announced_date is None:
            return False
        if self.announced_date is not None and self.announced_date > cutoff:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "period": self.period,
            "period_type": self.period_type,
            "announced_at": self.announced_date.isoformat() if self.announced_date else None,
            "observed_at": self.observed_date.isoformat() if self.observed_date else None,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "provider": self.provider,
            "raw_field_name": self.raw_field_name,
            "normalized_field": self.normalized_field,
            "unit": self.unit,
            "content_sha256": self.content_sha256,
            "proxy": self.proxy,
            "statement_scope": self.statement_scope,
            "formula_version": self.formula_version,
            "status": self.status.value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DividendRecord:
    attribution_year: int
    cash_per_share: float | None
    ex_date: date | datetime | str | None
    announced_at: date | datetime | str | None
    special: bool = False
    source_id: str = "unknown.dividend"
    source_url: str = "https://invalid.local/dividend"
    content_sha256: str = "sha256:" + "0" * 64
    proxy: bool = False

    def is_available_as_of(self, as_of: date | datetime | str) -> bool:
        cutoff = as_date(as_of)
        announcement = as_date(self.announced_at)
        ex_date = as_date(self.ex_date)
        return (
            cutoff is not None
            and finite_number(self.cash_per_share) is not None
            and ex_date is not None
            and ex_date <= cutoff
            and announcement is not None
            and announcement <= cutoff
        )

    def to_dict(self) -> dict[str, Any]:
        ex_date = as_date(self.ex_date)
        announced_at = as_date(self.announced_at)
        return {
            "attribution_year": self.attribution_year,
            "cash_per_share": self.cash_per_share,
            "ex_date": ex_date.isoformat() if ex_date is not None else None,
            "announced_at": announced_at.isoformat() if announced_at is not None else None,
            "special": self.special,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "content_sha256": self.content_sha256,
            "proxy": self.proxy,
        }


@dataclass
class CompanyData:
    company_code: str
    market: str
    company_name: str
    market_date: date | datetime | str | None = None
    listing_date: date | datetime | str | None = None
    statement_scope: str = "consolidated"
    facts: Mapping[str, Sequence[Fact]] = field(default_factory=dict)
    dividends: Sequence[DividendRecord] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"\d{4,6}", str(self.company_code)):
            raise ValueError("company_code must be 4-6 ASCII digits")
        self.company_code = str(self.company_code)
        if self.market not in {"TWSE", "TPEx"}:
            raise ValueError("market must be TWSE or TPEx")
        if not self.company_name:
            raise ValueError("company_name must be non-empty")
        if self.statement_scope not in {"consolidated", "separate", "standalone", "unknown"}:
            raise ValueError("invalid statement_scope")
        converted: dict[str, tuple[Fact, ...]] = {}
        for key, values in self.facts.items():
            if not isinstance(key, str) or not key:
                raise ValueError("fact field key must be non-empty")
            converted[key] = tuple(values)
        self.facts = converted
        self.dividends = tuple(self.dividends)
        self.metadata = dict(self.metadata)

    @property
    def market_day(self) -> date | None:
        return as_date(self.market_date)

    @property
    def listed_day(self) -> date | None:
        return as_date(self.listing_date)

    def all_facts(self, field: str, *, period_type: str | None = None) -> tuple[Fact, ...]:
        values = self.facts.get(field, ())
        if period_type is None:
            return tuple(values)
        return tuple(fact for fact in values if fact.period_type == period_type)

    def get_fact(
        self,
        field: str,
        period: str,
        *,
        as_of: date | datetime | str | None = None,
        require_announcement: bool | None = None,
    ) -> Fact | None:
        matches = [fact for fact in self.all_facts(field) if fact.period == period]
        if as_of is not None:
            matches = [fact for fact in matches if fact.is_available_as_of(as_of, require_announcement=require_announcement)]
        else:
            matches = [fact for fact in matches if fact.status == Status.PASS and fact.value is not None]
        if not matches:
            return None
        values = {float(fact.value) for fact in matches if fact.value is not None}
        if len(values) > 1:
            return None
        return sorted(matches, key=lambda fact: (fact.provider, fact.source_id, fact.content_sha256))[0]

    def periods(
        self,
        field: str,
        *,
        period_type: str | None = None,
        as_of: date | datetime | str | None = None,
    ) -> list[str]:
        facts = self.all_facts(field, period_type=period_type)
        if as_of is not None:
            facts = tuple(fact for fact in facts if fact.is_available_as_of(as_of))
        return sorted({fact.period for fact in facts}, key=period_sort_key)

    def latest_fact(
        self,
        field: str,
        *,
        period_type: str | None = None,
        as_of: date | datetime | str | None = None,
    ) -> Fact | None:
        periods = self.periods(field, period_type=period_type, as_of=as_of)
        for period in reversed(periods):
            fact = self.get_fact(field, period, as_of=as_of)
            if fact is not None:
                return fact
        return None

    def source_snapshot_ids(self, fields: Iterable[str], *, as_of: date | datetime | str | None = None) -> tuple[str, ...]:
        ids: set[str] = set()
        for field_name in fields:
            for fact in self.all_facts(field_name):
                if as_of is None or fact.is_available_as_of(as_of):
                    ids.add(fact.content_sha256)
        return tuple(sorted(ids))


@dataclass(frozen=True)
class ScoreConfig:
    category_thresholds: Mapping[str, float] = field(
        default_factory=lambda: {category: 0.5 for category in CATEGORY_ORDER}
    )
    working_days: int = 365
    include_special_dividends: bool = False
    formula_version: str = DEFAULT_FORMULA_VERSION
    model_version: str = "public-data-health-v1"
    universe_complete: bool = False
    min_history_observations: int = 1
    z_max: int | None = None

    def __post_init__(self) -> None:
        thresholds = dict(self.category_thresholds)
        missing = set(CATEGORY_ORDER) - set(thresholds)
        extra = set(thresholds) - set(CATEGORY_ORDER)
        if missing or extra:
            raise ValueError(f"category thresholds mismatch missing={sorted(missing)} extra={sorted(extra)}")
        if any(not isinstance(value, (float, int)) or not 0 <= float(value) <= 1 for value in thresholds.values()):
            raise ValueError("category thresholds must be between 0 and 1")
        if self.working_days <= 0:
            raise ValueError("working_days must be positive")
        if self.min_history_observations < 1:
            raise ValueError("min_history_observations must be positive")
        if self.z_max not in {None, 0, 1, 2}:
            raise ValueError("z_max must be None, 0, 1, or 2")
        object.__setattr__(self, "category_thresholds", thresholds)


@dataclass(frozen=True)
class CriterionResult:
    criterion_id: str
    status: Status
    value: Any = None
    threshold: Any = None
    period: str | None = None
    as_of: str | None = None
    source_snapshot: tuple[str, ...] = ()
    formula_version: str = DEFAULT_FORMULA_VERSION
    reason: str | None = None
    proxy: bool = False
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = self.status if isinstance(self.status, Status) else Status(str(self.status))
        object.__setattr__(self, "status", status)
        if status in {Status.UNKNOWN, Status.NOT_APPLICABLE} and self.reason is None:
            object.__setattr__(self, "reason", "status has no definitive boolean result")
        if status == Status.PASS and self.value is None:
            object.__setattr__(self, "value", True)
        object.__setattr__(self, "source_snapshot", tuple(sorted(self.source_snapshot)))
        object.__setattr__(self, "details", dict(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "status": self.status.value,
            "value": self.value,
            "threshold": self.threshold,
            "period": self.period,
            "as_of": self.as_of,
            "source_snapshot": list(self.source_snapshot),
            "formula_version": self.formula_version,
            "reason": self.reason,
            "proxy": self.proxy,
            "details": self.details,
        }


@dataclass(frozen=True)
class CategoryScore:
    category: str
    criteria: tuple[CriterionResult, ...]
    threshold: float

    @property
    def passed(self) -> int:
        return sum(item.status == Status.PASS for item in self.criteria)

    @property
    def failed(self) -> int:
        return sum(item.status == Status.FAIL for item in self.criteria)

    @property
    def unknown(self) -> int:
        return sum(item.status == Status.UNKNOWN for item in self.criteria)

    @property
    def not_applicable(self) -> int:
        return sum(item.status == Status.NOT_APPLICABLE for item in self.criteria)

    @property
    def total(self) -> int:
        return len(self.criteria)

    @property
    def score(self) -> str:
        return f"{self.passed}/{self.total}"

    @property
    def status(self) -> Status:
        if self.unknown:
            return Status.UNKNOWN
        active = self.total - self.not_applicable
        if active <= 0:
            return Status.NOT_APPLICABLE
        return Status.PASS if self.passed / active >= self.threshold else Status.FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "unknown": self.unknown,
            "not_applicable": self.not_applicable,
            "total": self.total,
            "score": self.score,
            "threshold": self.threshold,
            "status": self.status.value,
            "criteria": [item.to_dict() for item in self.criteria],
        }


@dataclass(frozen=True)
class CompanyScore:
    company_code: str
    market: str
    company_name: str
    market_date: str
    model_version: str
    formula_version: str
    categories: Mapping[str, CategoryScore]
    criteria: tuple[CriterionResult, ...]
    data_quality: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "company_code": self.company_code,
            "market": self.market,
            "company_name": self.company_name,
            "market_date": self.market_date,
            "model_version": self.model_version,
            "formula_version": self.formula_version,
            "categories": {key: self.categories[key].to_dict() for key in CATEGORY_ORDER if key in self.categories},
            "criteria": [item.to_dict() for item in self.criteria],
            "data_quality": dict(self.data_quality),
        }


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()
