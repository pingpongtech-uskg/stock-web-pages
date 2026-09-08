from __future__ import annotations

from datetime import date
import json

import pytest

from screener.institutional_sources import (
    InstitutionalRow,
    merge_daily_rows,
    parse_tpex_3insti,
    parse_twse_t86,
    ten_day_rank,
)


def test_parse_twse_t86_uses_investment_trust_net_column_and_skips_zero():
    payload = {
        "stat": "OK",
        "date": "20260908",
        "fields": ["證券代號", "證券名稱"] + [f"x{i}" for i in range(8)] + ["投信買賣超股數"],
        "data": [
            ["2330", "台積電", "", "", "", "", "", "", "", "", "1,234"],
            ["1234", "測試", "", "", "", "", "", "", "", "", "0"],
            ["00AA", "ETF", "", "", "", "", "", "", "", "", "5"],
        ],
    }
    rows = parse_twse_t86(payload, source_url="https://www.twse.com.tw/fund/T86")
    assert rows == [
        InstitutionalRow("2330", "台積電", "TWSE", "2026-09-08", 1234),
        InstitutionalRow("1234", "測試", "TWSE", "2026-09-08", 0),
    ]


def test_parse_tpex_uses_named_investment_trust_field_not_array_position():
    payload = {
        "stat": "ok",
        "date": "20260908",
        "tables": [{
            "fields": ["代號", "名稱", "別的買", "別的賣", "別的超"],
            "data": [["6488", "環球晶", "0", "0", "999"]],
        }],
    }
    # Named rows are the production shape. This malformed fixture must fail
    # closed instead of treating column 4 as investment-trust net buy.
    with pytest.raises(ValueError, match="investment trust"):
        parse_tpex_3insti(payload, source_url="https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php")


def test_parse_tpex_named_field_and_japanese_date():
    payload = {
        "stat": "ok",
        "date": "20260908",
        "tables": [{
            "title": "三大法人買賣明細資訊",
            "subtitle": "115年09月08日 三大法人日交易資訊(含普通股、鉅額、零股) 不含綜合帳戶之投信買賣成交量",
            "columnNum": 25,
            "fields": ["代號", "名稱"] + ["買賣超股數" if i % 3 == 2 else "買進股數" if i % 3 == 0 else "賣出股數" for i in range(2, 24)],
            "data": [["6488", "環球晶"] + ["0"] * 11 + ["-1,999,077"] + ["0"] * 10],
        }],
    }
    rows = parse_tpex_3insti(payload, source_url="https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php")
    assert rows == [InstitutionalRow("6488", "環球晶", "TPEx", "2026-09-08", -1999077)]


def test_merge_daily_rows_is_idempotent_and_reports_conflict():
    cache = {}
    row = InstitutionalRow("2330", "台積電", "TWSE", "2026-09-08", 100)
    cache, conflicts = merge_daily_rows(cache, [row])
    cache, conflicts2 = merge_daily_rows(cache, [row])
    assert cache["2330"]["dates"] == ["2026-09-08"]
    assert cache["2330"]["net"] == [100]
    assert conflicts == []
    assert conflicts2 == []
    changed = InstitutionalRow("2330", "台積電", "TWSE", "2026-09-08", 200)
    cache, conflicts = merge_daily_rows(cache, [changed])
    assert cache["2330"]["net"] == [100]
    assert conflicts[0]["status"] == "data_conflict"


def test_ten_day_rank_sums_signed_net_not_only_positive_days_and_uses_price():
    cache = {
        "2330": {"market": "TWSE", "name": "台積電", "dates": [f"2026-09-{i:02d}" for i in range(1, 11)], "net": [100] * 9 + [-50]},
        "6488": {"market": "TPEx", "name": "環球晶", "dates": [f"2026-09-{i:02d}" for i in range(1, 11)], "net": [80] * 10},
    }
    result = ten_day_rank(cache, as_of="2026-09-10", prices={"2330": 1000, "6488": 100})
    assert [row["code"] for row in result] == ["2330", "6488"]
    assert result[0]["net_shares_10d"] == 850
    assert result[0]["net_amount_10d"] == 850000


def test_share_limit_is_applied_before_amount_sort():
    cache = {
        "0001": {"market": "TWSE", "dates": [f"2026-09-{i:02d}" for i in range(1, 11)], "net": [100] * 10},
        "0002": {"market": "TWSE", "dates": [f"2026-09-{i:02d}" for i in range(1, 11)], "net": [90] * 10},
    }
    result = ten_day_rank(cache, as_of="2026-09-10", prices={"0001": 1, "0002": 1000}, share_limit=1, limit=1)
    assert [row["code"] for row in result] == ["0001"]


def test_ten_day_rank_requires_ten_observations():
    cache = {"2330": {"dates": ["2026-09-01"], "net": [100]}}
    assert ten_day_rank(cache, as_of="2026-09-01", prices={"2330": 100}) == []
