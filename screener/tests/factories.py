from __future__ import annotations

from datetime import date
from typing import Any

from screener.public_data_models import CompanyData, DividendRecord, Fact


def fact(
    value: float | None,
    period: str,
    period_type: str,
    *,
    announced_at: date | None = date(2025, 2, 15),
    observed_at: date | None = date(2025, 3, 1),
    proxy: bool = False,
    source_id: str = "fixture.source",
    normalized_field: str | None = None,
) -> Fact:
    return Fact(
        value=value,
        period=period,
        period_type=period_type,
        announced_at=announced_at,
        observed_at=observed_at,
        source_id=source_id,
        source_url="https://fixture.invalid/source",
        provider="fixture",
        raw_field_name=normalized_field or "fixture_field",
        normalized_field=normalized_field or "fixture_field",
        unit="fixture_unit",
        content_sha256="sha256:" + "a" * 64,
        proxy=proxy,
    )


def company(
    code: str = "2330",
    market: str = "TWSE",
    *,
    name: str = "fixture",
    facts: dict[str, list[Fact]] | None = None,
    dividends: list[DividendRecord] | None = None,
    listing_date: date | None = date(2010, 1, 1),
    metadata: dict[str, Any] | None = None,
) -> CompanyData:
    return CompanyData(
        company_code=code,
        market=market,
        company_name=name,
        market_date=date(2025, 3, 1),
        listing_date=listing_date,
        facts=facts or {},
        dividends=dividends or [],
        metadata=metadata or {"universe_complete": True},
    )


def annual_series(
    values: dict[str, dict[str, float | None]],
    *,
    announced_at: date | None = date(2025, 2, 15),
) -> dict[str, list[Fact]]:
    result: dict[str, list[Fact]] = {}
    for period, row in values.items():
        for field, value in row.items():
            result.setdefault(field, []).append(
                fact(value, period, "annual", announced_at=announced_at, normalized_field=field)
            )
    return result


def dividend(
    attribution_year: int,
    cash_per_share: float,
    *,
    ex_date: date,
    announced_at: date = date(2025, 2, 15),
    special: bool = False,
) -> DividendRecord:
    return DividendRecord(
        attribution_year=attribution_year,
        cash_per_share=cash_per_share,
        ex_date=ex_date,
        announced_at=announced_at,
        special=special,
        source_id="fixture.dividend",
        source_url="https://fixture.invalid/dividend",
        content_sha256="sha256:" + "b" * 64,
    )
