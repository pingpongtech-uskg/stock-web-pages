from __future__ import annotations

import pytest

from scripts.public_sources.tdcc import (
    build_query_form,
    fetch_query_once,
    normalize_tdcc_rows,
    parse_dispersion_csv,
    select_month_end_rows,
)


JSON_ROWS = [
    {"\ufeff資料年月": "11507", "股票代號": "2330", "集保股東戶數": "100"},
    {"\ufeff資料年月": "11506", "股票代號": "2330", "集保股東戶數": "110"},
    {"\ufeff資料年月": "11506", "股票代號": "6488", "集保股東戶數": "200"},
]


CSV = """資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n20260904,2330,1,10,100,1.00\n20260904,2330,2,20,200,2.00\n20260828,2330,1,11,110,1.10\n"""


def test_normalize_tdcc_rows_removes_actual_bom():
    rows = normalize_tdcc_rows(JSON_ROWS)
    assert rows[0]["資料年月"] == "11507"
    assert "\ufeff資料年月" not in rows[0]


def test_select_month_end_rows_picks_latest_observation_per_month():
    rows = [
        {"資料日期": "20260904", "證券代號": "2330", "集保股東戶數": "100"},
        {"資料日期": "20260828", "證券代號": "2330", "集保股東戶數": "110"},
        {"資料日期": "20260821", "證券代號": "2330", "集保股東戶數": "120"},
    ]
    selected = select_month_end_rows(rows, "2330")
    assert [row["資料日期"] for row in selected] == ["20260828", "20260904"]


def test_select_month_end_rows_rejects_duplicate_same_date():
    rows = [
        {"資料日期": "20260904", "證券代號": "2330", "集保股東戶數": "100"},
        {"資料日期": "20260904", "證券代號": "2330", "集保股東戶數": "101"},
    ]
    with pytest.raises(ValueError, match="duplicate"):
        select_month_end_rows(rows, "2330")


def test_parse_dispersion_csv_normalizes_header_and_target_rows():
    rows = parse_dispersion_csv(CSV)
    assert len(rows) == 3
    assert rows[0]["資料日期"] == "20260904"
    assert rows[0]["證券代號"] == "2330"
    assert rows[0]["人數"] == "10"


def test_query_form_is_explicit_and_token_is_not_saved_by_adapter():
    form = build_query_form("memory-token", "20260904", "2330")
    assert form["SYNCHRONIZER_TOKEN"] == "memory-token"
    assert form["sqlMethod"] == "StockNo"
    assert form["stockNo"] == "2330"
    assert form["scaDate"] == "20260904"


def test_query_once_refreshes_form_session_for_each_date(monkeypatch):
    initial = '<input name="SYNCHRONIZER_TOKEN" value="memory-token"><option value="20260904">最新</option>'
    queried = "<div>2330 台積電</div><div>持股/單位數分級</div>"
    calls = []

    def fake_request(url, **kwargs):
        calls.append(kwargs.get("opener"))
        if kwargs.get("method", "GET") == "POST":
            return probe_response(url, "POST", queried)
        return probe_response(url, "GET", initial)

    def probe_response(url, method, body):
        from scripts.probe_public_sources import Response
        return Response(url, method, 200, "text/html", body, len(body))

    monkeypatch.setattr("scripts.public_sources.tdcc.request_text", fake_request)
    first = fetch_query_once("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", "20260904", "2330", {"www.tdcc.com.tw"}, 5)
    second = fetch_query_once("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", "20260828", "2330", {"www.tdcc.com.tw"}, 5)
    assert first["queried"].body == queried
    assert second["queried"].body == queried
    assert calls[0] is not calls[2]
    assert calls[1] is not calls[3]
