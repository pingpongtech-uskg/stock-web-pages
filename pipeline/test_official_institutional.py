import json
import urllib.parse
from datetime import date

from pipeline.official_institutional import (
    aggregate_window,
    parse_tpex_payload,
    parse_twse_payload,
)


def test_tpex_request_matches_official_json_post_contract(monkeypatch):
    from pipeline.official_institutional import fetch_tpex_day, TPEX_ENDPOINT
    requests = []
    payload = {"date": "20261002", "stat": "ok", "tables": [{
        "fields": ["排行", "代號", "名稱", "買進", "賣出", "買賣超(張數)"],
        "data": [["1", "2330", "台積電", "10", "2", "8"]]}]}
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps(payload).encode()
    def respond(request, **kwargs):
        requests.append(request)
        return Response()
    monkeypatch.setattr("urllib.request.urlopen", respond)
    rows = fetch_tpex_day(date(2026, 10, 2))
    assert len(requests) == 1
    request = requests[0]
    assert request.full_url == TPEX_ENDPOINT
    assert request.get_method() == "POST"
    assert urllib.parse.parse_qs(request.data.decode()) == {
        "type": ["Daily"], "date": ["2026/10/02"], "searchType": ["buy"], "response": ["json"]}
    assert rows[0]["netShares"] == 8000


def test_tpex_json_contract_still_rejects_a_different_report_date(monkeypatch):
    import pipeline.official_institutional as official
    monkeypatch.setattr(official, "_get_json", lambda *args, **kwargs: {"date": "20261001"})
    assert official.fetch_tpex_day(date(2026, 10, 2)) == []


def test_parse_twse_report_keeps_share_units():
    payload = {
        "stat": "OK",
        "date": "20260918",
        "fields": ["", "證券代號", "證券名稱", "買進股數", "賣出股數", "買賣超股數"],
        "data": [[" ", "2303  ", "聯電 ", "19,720,456", "6,090,268", "13,630,188"]],
    }

    assert parse_twse_payload(payload) == [
        {
            "code": "2303",
            "name": "聯電",
            "market": "TWSE",
            "buyShares": 19720456,
            "sellShares": 6090268,
            "netShares": 13630188,
        }
    ]


def test_parse_tpex_report_converts_lots_to_shares():
    payload = {
        "date": "20260918",
        "tables": [{
            "fields": ["排行", "代號", "名稱", "買進", "賣出", "買賣超(張數)"],
            "data": [["1", "6147", "頎邦", "2,565", "0", "2,565"]],
        }],
    }

    assert parse_tpex_payload(payload) == [
        {
            "code": "6147",
            "name": "頎邦",
            "market": "TPEx",
            "buyShares": 2565000,
            "sellShares": 0,
            "netShares": 2565000,
        }
    ]


def test_aggregate_window_sums_both_markets_in_shares():
    days = [
        [
            {"code": "2303", "name": "聯電", "market": "TWSE", "netShares": 1000},
            {"code": "6147", "name": "頎邦", "market": "TPEx", "netShares": 2},
        ],
        [
            {"code": "2303", "name": "聯電", "market": "TWSE", "netShares": 3000},
            {"code": "6147", "name": "頎邦", "market": "TPEx", "netShares": 4},
        ],
    ]

    assert aggregate_window(days) == [
        {"rank": 1, "code": "2303", "name": "聯電", "market": "TWSE", "netShares": 4000},
        {"rank": 2, "code": "6147", "name": "頎邦", "market": "TPEx", "netShares": 6},
    ]


def test_aggregate_window_excludes_etf_and_warrant_codes():
    days = [[
        {"code": "0050", "name": "元大台灣50", "market": "TWSE", "netShares": 99999999},
        {"code": "00980A", "name": "主動野村臺灣優選", "market": "TWSE", "netShares": 88888888},
        {"code": "2330", "name": "台積電", "market": "TWSE", "netShares": 100},
    ]]

    assert [row["code"] for row in aggregate_window(days)] == ["2330"]
