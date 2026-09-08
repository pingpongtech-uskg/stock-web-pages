from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from scripts.normalized_snapshot import validate_field_record, validate_snapshot_record

ROOT = Path(__file__).resolve().parents[1]


def test_schema_file_declares_lineage_status_and_authority():
    schema = json.loads((ROOT / "calibration" / "normalized_schema.json").read_text(encoding="utf-8"))
    assert schema["schema_version"] == 1
    assert schema["status_enum"] == ["PASS", "FAIL", "UNKNOWN", "BLOCKED"]
    assert schema["authority_enum"] == [
        "official_primary",
        "official_crosscheck",
        "free_secondary",
        "reference_only",
    ]
    assert {"entity", "as_of", "period", "published_at", "retrieved_at_utc", "source_id", "source_url", "parser_version", "formula_version"} <= set(schema["required_snapshot_fields"])


def test_valid_field_and_snapshot_are_accepted():
    field = {
        "canonical_name": "annual_cfo",
        "source_label": "營業活動之淨現金流入（流出）",
        "value": 123.0,
        "unit": "NTD_thousand",
        "status": "PASS",
        "reason": None,
        "source_id": "mops.cashflow_history",
        "source_url": "https://mopsov.twse.com.tw/mops/web/ajax_t164sb05",
        "period": "2025-FY",
        "published_at": "2026-03-01",
    }
    validate_field_record(field)
    snapshot = {
        "entity": {"code": "2330", "name": "台積電", "market": "TWSE", "ordinary_share": True},
        "as_of": "2026-09-08",
        "period": "2025-FY",
        "published_at": "2026-03-01",
        "retrieved_at_utc": "2026-09-08T06:00:00Z",
        "source_id": "mops.cashflow_history",
        "source_url": "https://mopsov.twse.com.tw/mops/web/ajax_t164sb05",
        "http_status": 200,
        "row_count": 1,
        "raw_snapshot_id": "sha256:abc",
        "parser_version": "mops-html-v1",
        "schema_version": 1,
        "formula_version": "public-osint-v1",
        "authority": "official_primary",
        "scope": "consolidated",
        "fields": {"annual_cfo": field},
    }
    validate_snapshot_record(snapshot)


def test_invalid_status_or_nonfinite_field_is_rejected():
    field = {
        "canonical_name": "annual_cfo",
        "source_label": "CFO",
        "value": math.nan,
        "unit": "NTD_thousand",
        "status": "MAYBE",
        "reason": None,
        "source_id": "mops.cashflow_history",
        "source_url": "https://mopsov.twse.com.tw/mops/web/ajax_t164sb05",
        "period": "2025-FY",
        "published_at": "2026-03-01",
    }
    with pytest.raises(ValueError, match="status"):
        validate_field_record(field)
    field["status"] = "PASS"
    with pytest.raises(ValueError, match="finite"):
        validate_field_record(field)


def test_snapshot_rejects_wrong_source_host_and_missing_lineage():
    with pytest.raises(ValueError, match="source_url"):
        validate_snapshot_record({
            "entity": {"code": "2330", "name": "台積電", "market": "TWSE", "ordinary_share": True},
            "as_of": "2026-09-08",
            "period": "2025-FY",
            "published_at": "2026-03-01",
            "retrieved_at_utc": "2026-09-08T06:00:00Z",
            "source_id": "bad",
            "source_url": "https://evil.example/data",
            "http_status": 200,
            "row_count": 1,
            "raw_snapshot_id": "sha256:abc",
            "parser_version": "v1",
            "schema_version": 1,
            "formula_version": "v1",
            "authority": "official_primary",
            "scope": "consolidated",
            "fields": {},
        })
