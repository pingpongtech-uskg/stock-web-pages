from __future__ import annotations

from datetime import date

from screener.public_data_normalizer import normalize_code, normalize_record, normalize_records


def test_normalizer_preserves_leading_zero_from_integer_like_input():
    assert normalize_code(50) == "0050"
    assert normalize_code("0050") == "0050"


def test_normalizer_builds_fact_list_and_inferrs_period_type():
    result = normalize_record(
        {
            "market": "TWSE",
            "company_code": 50,
            "company_name": "fixture",
            "market_date": "2025-03-01",
            "facts": [
                {
                    "normalized_field": "cfo",
                    "period": "2024-FY",
                    "value": 100,
                    "announced_at": "2025-02-15",
                    "source_id": "fixture.cfo",
                    "source_url": "https://fixture.invalid/cfo",
                    "provider": "fixture",
                    "content_sha256": "sha256:" + "1" * 64,
                }
            ],
        }
    )
    assert result.company_code == "0050"
    assert result.get_fact("cfo", "2024-FY", as_of=date(2025, 3, 1)).period_type == "annual"


def test_normalizer_reports_conflicting_provider_values_without_overwriting():
    result = normalize_records(
        [
            {
                "market": "TWSE", "company_code": "2330", "company_name": "fixture",
                "facts": [{"normalized_field": "pb", "period": "2025-03-01", "period_type": "daily", "value": 1, "observed_at": "2025-03-01", "source_id": "a", "source_url": "https://fixture.invalid/a", "provider": "a", "content_sha256": "sha256:" + "a" * 64}],
            },
            {
                "market": "TWSE", "company_code": "2330", "company_name": "fixture",
                "facts": [{"normalized_field": "pb", "period": "2025-03-01", "period_type": "daily", "value": 2, "observed_at": "2025-03-01", "source_id": "b", "source_url": "https://fixture.invalid/b", "provider": "b", "content_sha256": "sha256:" + "b" * 64}],
            },
        ]
    )
    assert len(result.conflicts) == 1
    assert result.conflicts[0]["status"] == "data_conflict"
    assert len(result.companies[0].all_facts("pb")) == 2
