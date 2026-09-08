from __future__ import annotations

import pytest

from screener.public_market_facts import (
    parse_company_master,
    parse_tpex_valuation,
    parse_twse_valuation,
)


def test_parse_twse_valuation_skips_invalid_pe_but_keeps_pb_and_yield():
    payload = {
        "stat": "OK",
        "date": "20260908",
        "fields": ["股票代號", "股票名稱", "本益比", "殖利率(%)", "股價淨值比"],
        "data": [["2330", "台積電", "-", "1.23", "2.50"], ["0050", "ETF", "10", "2", "1"]],
    }
    rows = parse_twse_valuation(payload, source_url="https://www.twse.com.tw/exchangeReport/BWIBBU_ALL", requested_date="2026-09-08")
    assert rows["2330"]["name"] == "台積電"
    assert rows["2330"]["market"] == "TWSE"
    assert rows["2330"]["pe"] is None
    assert rows["2330"]["pb"] == 2.5
    assert rows["2330"]["dividend_yield"] == 1.23


def test_parse_tpex_valuation_maps_named_fields():
    payload = [{"Date": "1150908", "SecuritiesCompanyCode": "6488", "CompanyName": "環球晶", "PriceEarningRatio": "46.36", "YieldRatio": "0.81", "PriceBookRatio": "4.72"}]
    rows = parse_tpex_valuation(payload, source_url="https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis", requested_date="2026-09-08")
    assert rows["6488"]["pe"] == 46.36
    assert rows["6488"]["pb"] == 4.72
    assert rows["6488"]["dividend_yield"] == 0.81


def test_parse_company_master_maps_listing_date_and_market():
    twse = [{"出表日期": "1150908", "公司代號": "2330", "公司名稱": "台灣積體電路製造股份有限公司", "公司簡稱": "台積電", "上市日期": "19940905"}]
    tpex = [{"Date": "1150908", "SecuritiesCompanyCode": "6488", "CompanyName": "環球晶圓股份有限公司", "CompanyAbbreviation": "環球晶", "DateOfListing": "20150925"}]
    result = parse_company_master(twse, market="TWSE") | parse_company_master(tpex, market="TPEx")
    assert result["2330"]["listing_date"] == "1994-09-05"
    assert result["6488"]["listing_date"] == "2015-09-25"
    assert result["6488"]["name"] == "環球晶"
