from pipeline.official_institutional import (
    aggregate_window,
    parse_tpex_payload,
    parse_twse_payload,
)


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
