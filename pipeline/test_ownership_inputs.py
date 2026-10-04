from pipeline.ownership_inputs import normalize_director_rows, normalize_tdcc_rows
from scripts.fetch_ownership import parse_twse_director_rows, parse_twse_issued_shares


def test_normalize_tdcc_rows_uses_last_week_and_frozen_class_mapping():
    rows = [
        {"資料日期": "2026-08-21", "證券代號": "2330", "持股分級": "15", "人數": "1", "股數": "10", "占集保庫存數比例%": "4.0"},
        {"資料日期": "2026-08-21", "證券代號": "2330", "持股分級": "16", "人數": "2", "股數": "20", "占集保庫存數比例%": "5.0"},
        {"資料日期": "2026-08-21", "證券代號": "2330", "持股分級": "17", "人數": "12540", "股數": "0", "占集保庫存數比例%": "0"},
        {"資料日期": "2026-08-28", "證券代號": "2330", "持股分級": "15", "人數": "1", "股數": "11", "占集保庫存數比例%": "4.1"},
        {"資料日期": "2026-08-28", "證券代號": "2330", "持股分級": "16", "人數": "2", "股數": "21", "占集保庫存數比例%": "5.2"},
        {"資料日期": "2026-08-28", "證券代號": "2330", "持股分級": "17", "人數": "12500", "股數": "0", "占集保庫存數比例%": "0"},
    ]

    result = normalize_tdcc_rows(rows, retrieved_at="2026-09-01T00:00:00+08:00", snapshot_id="tdcc-1")

    assert result == [{
        "code": "2330", "market": None, "period": "2026-08", "asOf": "2026-08-28",
        "publishedAt": None, "retrievedAt": "2026-09-01T00:00:00+08:00",
        "largeHolderPct": 4.1, "directorSupervisorPct": None, "shareholderCount": 12500,
        "source": "TDCC", "dataset": "1-5", "snapshotId": "tdcc-1", "schemaVersion": "ownership-v1",
        "sourceRefs": ["TDCC:1-5:2026-08-28"], "sourceDate":"2026-08-28", "observedFields":["largeHolderPct","shareholderCount"],
    }]


def test_normalize_director_rows_excludes_proxies_and_calculates_percentage():
    rows = [
        {"資料年月": "2026-08", "公司代號": "2330", "職稱": "董事長本人", "姓名":"甲", "目前持股": "100", "已發行普通股數": "1000"},
        {"資料年月": "2026-08", "公司代號": "2330", "職稱": "董事本人", "姓名":"乙", "目前持股": "50", "已發行普通股數": "1000"},
        {"資料年月": "2026-08", "公司代號": "2330", "職稱": "法人代表人", "目前持股": "999", "已發行普通股數": "1000"},
    ]

    result = normalize_director_rows(rows, retrieved_at="2026-09-01T00:00:00+08:00", snapshot_id="mops-1")

    assert result[0]["directorSupervisorPct"] == 15.0
    assert result[0]["directorDenominator"] == 1000.0
    assert result[0]["directorScope"] == ["董事長本人", "董事本人"]
    assert result[0]["source"] == "TWSE OpenAPI"


def test_twse_openapi_director_rows_join_same_snapshot_issued_shares():
    issued = parse_twse_issued_shares([
        {"公司代號": "2330", "已發行普通股數或TDR原股發行股數": "1,000"},
    ])
    result = parse_twse_director_rows([
        {"資料年月": "11508", "公司代號": "2330", "職稱": "董事長本人", "姓名":"甲", "目前持股": "100"},
        {"資料年月": "11508", "公司代號": "2330", "職稱": "董事本人", "姓名":"乙", "目前持股": "50"},
        {"資料年月": "11508", "公司代號": "2330", "職稱": "董事之法人代表人", "目前持股": "999"},
    ], issued_shares_by_code=issued, dataset="t187ap11_L")

    assert result[0]["directorSupervisorPct"] is None
    assert result[0]["source"] == "TWSE OpenAPI"
    assert result[0]["dataset"] == "t187ap11_L"
