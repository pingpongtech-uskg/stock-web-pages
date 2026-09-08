from __future__ import annotations

import csv
import io
import math

import pytest

from screener.market_sources import parse_tpex_prices, parse_twse_prices, regression_z


def test_parse_twse_daily_csv_keeps_only_four_digit_common_shares():
    csv_text = "日期,證券代號,證券名稱,成交股數,成交金額,開盤價,最高價,最低價,收盤價,漲跌價差,成交筆數\n1150908,2330,台積電,1,2,3,4,5,2470.00,1,1\n1150908,0050,ETF,1,2,3,4,5,100.00,1,1\n1150908,6488A,特別,1,2,3,4,5,1.00,1,1\n"
    result = parse_twse_prices(csv_text, requested_date="2026-09-08")
    assert result == {"2330": 2470.0}


def test_parse_tpex_prices_reads_close():
    payload = [{"Date": "1150908", "SecuritiesCompanyCode": "6488", "CompanyName": "環球晶", "Close": "955.00"}]
    assert parse_tpex_prices(payload, requested_date="2026-09-08") == {"6488": 955.0}


def test_regression_z_is_deterministic_and_uses_last_882_prices():
    prices = [100 + i * 0.1 + (1 if i % 2 else -1) for i in range(1000)]
    first = regression_z(prices)
    second = regression_z(prices)
    assert first == second
    assert isinstance(first, float)


def test_regression_z_needs_history_and_rejects_zero_variance():
    assert regression_z([1, 2, 3]) is None
    assert regression_z([10.0] * 200) is None
