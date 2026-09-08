from __future__ import annotations

import pytest

from scripts.public_sources.exchanges import (
    join_eligible_universe,
    normalize_company_rows,
    parse_valuation_payload,
)


TWSE = [
    {"公司代號": "2330", "公司名稱": "台積電", "上市日期": "19940905", "產業別": "24"},
]
OTC = [
    {"SecuritiesCompanyCode": "6488", "CompanyName": "環球晶", "DateOfListing": "20150925", "SecuritiesIndustryCode": "24"},
]


def test_normalize_listed_and_otc_company_rows():
    listed = normalize_company_rows(TWSE, "TWSE")
    otc = normalize_company_rows(OTC, "TPEx")
    assert listed == [{"code": "2330", "name": "台積電", "market": "TWSE", "ordinary_share": True, "listing_date": "19940905", "industry": "24"}]
    assert otc[0]["code"] == "6488"
    assert otc[0]["market"] == "TPEx"
    assert otc[0]["ordinary_share"] is True


def test_join_universe_rejects_code_market_overlap():
    listed = normalize_company_rows(TWSE, "TWSE")
    otc = normalize_company_rows(
        [{"SecuritiesCompanyCode": "2330", "CompanyName": "重複", "DateOfListing": "20100101"}],
        "TPEx",
    )
    with pytest.raises(ValueError, match="overlap"):
        join_eligible_universe(listed, otc)


def test_join_universe_is_sorted_and_deduplicated():
    listed = normalize_company_rows(
        [
            {"公司代號": "2330", "公司名稱": "台積電", "上市日期": "19940905"},
            {"公司代號": "1101", "公司名稱": "台泥", "上市日期": "19620209"},
        ],
        "TWSE",
    )
    result = join_eligible_universe(listed, [])
    assert [row["code"] for row in result] == ["1101", "2330"]


def test_parse_valuation_payload_keeps_blank_as_none():
    payload = [
        {"Code": "2330", "Date": "1150907", "PEratio": "28.52", "DividendYield": "0.89", "PBratio": "9.92"},
        {"Code": "1101", "Date": "1150907", "PEratio": "-", "DividendYield": "3.29", "PBratio": "0.79"},
    ]
    values = parse_valuation_payload(payload, market="TWSE")
    assert values["2330"]["pe"] == 28.52
    assert values["2330"]["pb"] == 9.92
    assert values["1101"]["pe"] is None
    assert values["1101"]["pb"] == 0.79


def test_parse_valuation_object_with_fields_and_data():
    payload = {"fields": ["證券代號", "本益比", "股價淨值比"], "data": [["2330", "28.52", "9.92"]]}
    values = parse_valuation_payload(payload, market="TWSE")
    assert values["2330"]["pe"] == 28.52
    assert values["2330"]["pb"] == 9.92
