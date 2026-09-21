import json

from scripts.fetch_ownership import (
    OWNERSHIP_SNAPSHOT_VERSION,
    build_snapshot,
    parse_mops_payload,
    parse_tdcc_csv,
    parse_tdcc_history_html,
)


def test_parse_tdcc_history_table_maps_actual_headers_and_injects_code_date():
    html = "<table><tr><th>序</th><th>持股/單位數分級</th><th>人數</th><th>股數/單位數</th><th>占集保庫存數比例 (%)</th></tr><tr><td>15</td><td>1,000,001以上</td><td>1,000</td><td>10,000</td><td>4.1</td></tr><tr><td>17</td><td>合 計</td><td>12,500</td><td>20,000</td><td>100.00</td></tr></table>"
    rows = parse_tdcc_history_html(html, code="2330", as_of="2026-08-28")
    assert rows[0]["證券代號"] == "2330"
    assert rows[0]["資料日期"] == "2026-08-28"
    assert rows[0]["持股分級"] == "15"
    assert parse_tdcc_csv("資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n2026-08-28,2330,15,1,10,4.1\n2026-08-28,2330,17,12500,0,0\n")[0]["largeHolderPct"] == 4.1

def test_parse_tdcc_csv_uses_class_15_and_ignores_adjustment_class_16():
    csv = "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n2026-08-28,2330,15,1,11,4.1\n2026-08-28,2330,16,2,21,99.9\n2026-08-28,2330,17,12500,0,0\n"
    rows = parse_tdcc_csv(csv)
    assert rows[0]["largeHolderPct"] == 4.1
    assert rows[0]["shareholderCount"] == 12500
    assert rows[0]["asOf"] == "2026-08-28"


def test_parse_mops_payload_keeps_only_approved_titles_and_refuses_aggregate_as_denominator():
    payload = {"parentCompany": {"data": [
        ["董事長本人", "甲", "120", "100", "x"],
        ["董事本人", "乙", "60", "50", "x"],
        ["法人代表人", "丙", "999", "999", "x"],
    ], "total": {"allDirectorSupervisor": "1000"}}}
    rows = parse_mops_payload(payload, code="2330", period="2026-08")
    assert rows[0]["directorSupervisorPct"] is None
    assert rows[0]["directorDenominator"] is None
    assert rows[0]["directorScope"] == ["董事長本人", "董事本人"]


def test_snapshot_marks_source_failure_stale_and_never_fakes_zeroes():
    old = {"schemaVersion": OWNERSHIP_SNAPSHOT_VERSION, "rows": [{"code": "2330", "period": "2026-08", "largeHolderPct": 4.1}]}
    snapshot = build_snapshot(old, [], requested_codes=["2330"], retrieved_at="2026-09-01T00:00:00+08:00")
    assert snapshot["status"] == "stale"
    assert snapshot["rows"] == old["rows"]
    assert snapshot["rows"][0]["shareholderCount"] if "shareholderCount" in snapshot["rows"][0] else True
    assert snapshot["rows"][0].get("largeHolderPct") == 4.1
    assert snapshot["rows"][0].get("shareholderCount") != 0
