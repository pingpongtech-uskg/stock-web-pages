from __future__ import annotations

from datetime import date

from screener.public_data_models import (
    CompanyData,
    Fact,
    ScoreConfig,
    Status,
)


def test_fact_point_in_time_rejects_future_announcement():
    fact = Fact(
        value=10,
        period="2024-FY",
        period_type="annual",
        announced_at=date(2025, 3, 1),
        observed_at=date(2025, 3, 1),
        source_id="fixture",
        source_url="https://fixture.invalid/source",
        provider="fixture",
        raw_field_name="x",
        normalized_field="x",
        unit="NTD",
        content_sha256="sha256:" + "a" * 64,
    )
    assert fact.is_available_as_of(date(2025, 2, 28)) is False
    assert fact.is_available_as_of(date(2025, 3, 1)) is True


def test_company_preserves_leading_zero_code():
    company = CompanyData(
        company_code="0050",
        market="TWSE",
        company_name="fixture",
        market_date=date(2025, 3, 1),
    )
    assert company.company_code == "0050"


def test_score_config_defaults_are_transparent():
    config = ScoreConfig()
    assert config.formula_version
    assert config.working_days == 365
    assert config.include_special_dividends is False
    assert set(config.category_thresholds) == {
        "turnaround", "value", "growth", "chip", "dividend", "continuity", "safety"
    }
    assert Status.PASS.value == "pass"
    assert Status.UNKNOWN.value == "unknown"
