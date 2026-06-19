"""
Tests for build_site_data.py — technical indicator calculations.
Key rule: MA uses data[T-N:T] excluding T (verified in previous sessions).
"""
import json
import os
import sys
import math
import tempfile
import pytest

# Add data dir to path so we can import build_site_data
sys.path.insert(0, os.path.dirname(__file__))
import build_site_data as bsd


# ─── MA (Simple Moving Average, excluding T) ───

def test_ma5_basic():
    """MA5 at index 5 averages close[0:5] (indices 0,1,2,3,4 — NOT index 5)."""
    close = [10, 12, 14, 16, 18, 20, 22]
    result = bsd.compute_ma(close, period=5)
    # At index 0-4: not enough data before → None
    assert result[0] is None
    assert result[1] is None
    assert result[2] is None
    assert result[3] is None
    assert result[4] is None
    # At index 5: avg of [10,12,14,16,18] = 14.0
    assert result[5] == pytest.approx(14.0)
    # At index 6: avg of [12,14,16,18,20] = 16.0
    assert result[6] == pytest.approx(16.0)


def test_ma_excludes_current_day():
    """The MA at index T must NOT include close[T]."""
    close = [100, 200]
    result = bsd.compute_ma(close, period=1)
    assert result[0] is None  # not enough history
    assert result[1] == pytest.approx(100.0)  # only close[0], NOT close[1]


def test_ma20_roundtrip():
    """MA20 with known values."""
    close = list(range(1, 31))  # 1..30
    result = bsd.compute_ma(close, period=20)
    # At index 20: avg of close[0:20] = avg(1..20) = 10.5
    assert result[20] == pytest.approx(10.5)
    # At index 29: avg of close[9:29] = avg(10..29) = 19.5
    assert result[29] == pytest.approx(19.5)


# ─── RSI(14) ───

def test_rsi_all_gains():
    """When price only goes up, RSI should approach 100."""
    close = list(range(1, 30))  # 1,2,3,...,29 — daily gain of 1
    result = bsd.compute_rsi(close, period=14)
    # RSI at index 14: first computable point
    assert result[14] is not None
    assert result[14] > 90
    # By the end, RSI should be very close to 100
    assert result[-1] > 99


def test_rsi_all_losses():
    """When price only goes down, RSI should approach 0."""
    close = list(range(30, 0, -1))  # 30,29,...,1 — daily loss of 1
    result = bsd.compute_rsi(close, period=14)
    assert result[14] is not None
    assert result[14] < 10
    assert result[-1] < 1


def test_rsi_flat():
    """When price never changes, RSI should be 50 (equal gain/loss, or special case)."""
    close = [100] * 30
    result = bsd.compute_rsi(close, period=14)
    # With Wilder's smoothing: if avg_gain=0 and avg_loss=0, RS=1 → RSI=50
    # But some implementations return 100 because of division by zero
    # Our implementation: when both are 0, RSI = 50 (neutral)
    assert result[-1] == pytest.approx(50.0)


# ─── KD(9,3) ───

def test_kd_basic():
    """KD using close as proxy for high/low (only close data available)."""
    close = [10, 12, 14, 16, 18, 20, 18, 16, 14, 12, 10, 14, 18, 22, 20, 18, 16]
    k, d = bsd.compute_kd(close, period=9, smooth=3)
    # First computable: after 9 bars for RSV, then 3-period smoothing for K and D
    # K at period=9 requires RSV[9], then K smoothed over 3
    # We need at least 9 + 3 = 12 bars for first valid K/D
    assert k[11] is not None
    assert d[11] is not None
    # K and D should be between 0 and 100
    for val in k:
        if val is not None:
            assert 0 <= val <= 100
    for val in d:
        if val is not None:
            assert 0 <= val <= 100


def test_kd_high_point():
    """At a peak (close = high of period), K should be high."""
    # Build data where last 9 days' max is the current day
    # Need at least 9 + 3 = 12 bars (period + smooth)
    close = [5] * 11 + [10]  # index 11 is the high of the 9-day window
    k, d = bsd.compute_kd(close, period=9, smooth=3)
    # RSV should be 100 (close = high, so (C-L)/(H-L) = 1)
    # K = 2/3 * prev_K + 1/3 * RSV — initial K before smoothing assumed 50
    # After smoothing: values should be high
    valid_k = [v for v in k if v is not None]
    assert len(valid_k) > 0
    # K should be high but not necessarily exactly 100 due to smoothing
    assert valid_k[-1] > 50


# ─── MACD(12,26,9) ───

def test_macd_uptrend():
    """In a steady uptrend, MACD line > 0 (price rising → fast EMA > slow EMA)."""
    close = list(range(1, 101))  # 1..100, steady uptrend
    macd, signal, hist = bsd.compute_macd(close, fast=12, slow=26, signal_period=9)
    # Need at least slow period (26) bars before any MACD
    assert all(v is None for v in macd[:25])
    assert macd[26] is not None
    # In an uptrend, MACD line should be positive (fast EMA > slow EMA)
    last_valid = max(i for i, v in enumerate(macd) if v is not None)
    assert macd[last_valid] > 0
    # Signal line should also be positive in uptrend
    assert signal[last_valid] > 0


def test_macd_downtrend():
    """In a steady downtrend, MACD line < 0 and below signal."""
    close = list(range(100, 0, -1))  # 100..1, steady downtrend
    macd, signal, hist = bsd.compute_macd(close, fast=12, slow=26, signal_period=9)
    last_valid = max(i for i, v in enumerate(macd) if v is not None)
    assert macd[last_valid] < 0


# ─── Change percentages ───

def test_change_1d():
    close = [100, 101, 102, 103, 104, 105]
    result = bsd.compute_change(close)
    # 1d: (105-104)/104 * 100 = 0.9615... → rounded to 0.96
    assert result["1d"] == 0.96


def test_change_1w():
    close = [100] * 5 + [110]  # 5 days at 100, then 110
    result = bsd.compute_change(close)
    # 1w: (110-100)/100 * 100 = 10.0
    assert result["1w"] == pytest.approx(10.0)


def test_change_insufficient_data():
    """When stock has < 2 days, change should be 0 or None."""
    close = [100]
    result = bsd.compute_change(close)
    assert result["1d"] == 0.0


# ─── MA status ───

def test_ma_status_bullish():
    """MA5 > MA20 > MA60 → 多頭排列"""
    assert bsd.compute_ma_status(ma5=120, ma20=110, ma60=100) == "多頭排列"


def test_ma_status_bearish():
    """MA5 < MA20 < MA60 → 空頭排列"""
    assert bsd.compute_ma_status(ma5=100, ma20=110, ma60=120) == "空頭排列"


def test_ma_status_consolidation():
    """Mixed order → 盤整"""
    assert bsd.compute_ma_status(ma5=110, ma20=100, ma60=120) == "盤整"


def test_ma_status_none_value():
    """When any MA is None, return 盤整."""
    assert bsd.compute_ma_status(ma5=None, ma20=110, ma60=120) == "盤整"


# ─── End-to-end: process one stock ───

def test_process_stock():
    """Full processing of a single stock dict → output dict."""
    stock_data = {
        "name": "測試股",
        "start": "2020-01-02",
        "end": "2020-02-28",
        "days": 40,
        "dates": [f"2020-01-{d:02d}" for d in range(2, 32)] + [f"2020-02-{d:02d}" for d in range(1, 29)],
        "close": [100 + i * 0.5 for i in range(58)],  # 58 trading days, uptrend
        "volume": [1000000 + i * 10000 for i in range(58)],
    }
    result = bsd.process_stock("9999", stock_data, max_days=500)

    assert result["code"] == "9999"
    assert result["name"] == "測試股"
    assert result["start"] == "2020-01-02"
    assert result["end"] == "2020-02-28"
    assert result["days"] == 40  # total days, not max_days

    price = result["price"]
    assert "dates" in price
    assert "close" in price
    assert "volume" in price
    assert "ma5" in price
    assert "ma20" in price
    assert "ma60" in price
    assert "rsi14" in price
    assert "kd_k" in price
    assert "kd_d" in price
    assert "macd" in price
    assert "macd_signal" in price
    assert "macd_hist" in price

    # All arrays should have the same length
    n = len(price["dates"])
    for key in ["close", "volume", "ma5", "ma20", "ma60", "rsi14", "kd_k", "kd_d", "macd", "macd_signal", "macd_hist"]:
        assert len(price[key]) == n, f"{key} length mismatch: {len(price[key])} vs {n}"

    # Latest
    assert "latest" in result
    assert "price" in result["latest"]
    assert "change_pct" in result["latest"]
    assert "volume" in result["latest"]

    # Change
    assert "change" in result
    for period in ["1d", "1w", "1m", "3m", "1y"]:
        assert period in result["change"]

    # MA status
    assert result["ma_status"] in ("多頭排列", "空頭排列", "盤整")


# ─── Edge case: stock with < 500 days ───

def test_short_stock():
    """Stock with fewer than max_days: all days included, indicators mostly None."""
    stock_data = {
        "name": "短天期",
        "start": "2020-01-02",
        "end": "2020-01-10",
        "days": 6,
        "dates": ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09"],
        "close": [10, 11, 10.5, 11.5, 12, 11.8],
        "volume": [1000, 1100, 1050, 1200, 1300, 1250],
    }
    result = bsd.process_stock("0001", stock_data, max_days=500)
    # Only 6 days of data, all should be included
    assert len(result["price"]["dates"]) == 6
    # KD requires 9+3-1=11 bars minimum — should be all None
    assert result["price"]["kd_k"] == [None] * 6
    assert result["price"]["kd_d"] == [None] * 6


# ─── Edge case: all-same price ───

def test_flat_price_stock():
    """Stock where close never changes."""
    stock_data = {
        "name": "平盤股",
        "start": "2020-01-02",
        "end": "2020-02-28",
        "days": 40,
        "dates": [f"2020-01-{d:02d}" for d in range(2, 32)] + [f"2020-02-{d:02d}" for d in range(1, 29)],
        "close": [50.0] * 58,
        "volume": [1000] * 58,
    }
    result = bsd.process_stock("0000", stock_data, max_days=500)
    # Should not crash
    assert result["code"] == "0000"
    # Change should be 0
    assert result["change"]["1d"] == 0.0
    # RSI should be neutral
    assert result["price"]["rsi14"][-1] == pytest.approx(50.0)
