from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.collect_public_snapshot import (
    _fetch_json,
    _insider_current_value,
    build_field,
    month_sequence,
    parse_tdcc_shareholder_count,
    validate_collection,
)


ROOT = Path(__file__).resolve().parents[1]


TDCC_HTML = """
<table>
<tr><th>序</th><th>持股/單位數分級</th><th>人數</th><th>股數/單位數</th></tr>
<tr><td>1</td><td>1-999</td><td>10</td><td>100</td></tr>
<tr><td>16</td><td>合 計</td><td>3,058,627</td><td>25,932,370,067</td></tr>
</table>
"""


def test_month_sequence_moves_back_across_roc_year():
    assert month_sequence("115", "02", 4) == [
        ("115", "02"),
        ("115", "01"),
        ("114", "12"),
        ("114", "11"),
    ]


def test_parse_tdcc_shareholder_count_uses_total_row():
    assert parse_tdcc_shareholder_count(TDCC_HTML) == 3058627


def test_parse_tdcc_shareholder_count_rejects_missing_or_duplicate_total():
    with pytest.raises(ValueError, match="total"):
        parse_tdcc_shareholder_count(TDCC_HTML.replace("合 計", "總計"))
    duplicate = TDCC_HTML.replace(
        "</table>",
        '<tr><td>17</td><td>合 計</td><td>4</td><td>5</td></tr></table>',
    )
    with pytest.raises(ValueError, match="duplicate"):
        parse_tdcc_shareholder_count(duplicate)


def test_insider_aggregate_uses_first_numeric_cell():
    row = {"label": "非獨立董事持股合計", "values": ["1,690,007,789", "", "非獨立董事持股設質合計", "1,600,000"]}
    assert _insider_current_value(row) == 1690007789.0


def test_build_field_does_not_turn_missing_into_zero():
    field = build_field(
        canonical_name="annual_cfo",
        source_label="營業活動之淨現金流入（流出）",
        value=None,
        unit="NTD_thousand",
        source_id="mops.cashflow_history",
        source_url="https://mopsov.twse.com.tw/mops/web/ajax_t164sb05",
        period="2025-FY",
        raw_snapshot_id="sha256:" + "a" * 64,
    )
    assert field["status"] == "UNKNOWN"
    assert field["value"] is None
    assert field["reason"]


def test_validate_collection_accepts_two_code_shape_and_rejects_raw_body():
    collection = {
        "schema_version": 1,
        "collector_version": "public-osint-snapshot-v1",
        "run_at_utc": "2026-09-08T06:00:00Z",
        "as_of": "2026-09-08",
        "records": [
            {
                "entity": {"code": "2330", "name": "台積電", "market": "TWSE", "ordinary_share": True},
                "sources": [],
                "fields": {},
                "history": {},
                "coverage": {"status": "UNKNOWN", "reasons": ["fixture"]},
            },
            {
                "entity": {"code": "6488", "name": "環球晶", "market": "TPEx", "ordinary_share": True},
                "sources": [],
                "fields": {},
                "history": {},
                "coverage": {"status": "UNKNOWN", "reasons": ["fixture"]},
            },
        ],
    }
    validate_collection(collection)
    collection["records"][0]["raw_html"] = "should never be present"
    with pytest.raises(ValueError, match="raw"):
        validate_collection(collection)


def test_collector_script_help_works_when_invoked_directly():
    script = ROOT / "scripts" / "collect_public_snapshot.py"
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_fetch_json_retries_one_transient_parse_failure(monkeypatch):
    def probe_response(url, body, size):
        from scripts.probe_public_sources import Response
        return Response(url, "GET", 200, "application/json", body, size)

    responses = iter([
        probe_response("https://example.invalid", "{\"broken\"", 8),
        probe_response("https://example.invalid", '[{"Code":"2330","PEratio":"1","PBratio":"2","DividendYield":"3"}]', 80),
    ])
    calls = []

    def fake_request(url, **kwargs):
        calls.append(url)
        return next(responses)

    monkeypatch.setattr("scripts.collect_public_snapshot.request_text", fake_request)
    payload, meta, _ = _fetch_json(
        "test.source",
        "https://openapi.twse.com.tw/v1/test",
        allowed_hosts={"openapi.twse.com.tw"},
        timeout=5,
        target_code="2330",
    )
    assert payload is not None
    assert meta["status"] == "PASS"
    assert len(calls) == 2
    assert meta["attempts"] == 2
