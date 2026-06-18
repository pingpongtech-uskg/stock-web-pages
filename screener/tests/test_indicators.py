"""
Unit tests for indicators.py — edge cases and look-ahead bias verification.

Usage:
    pytest tests/test_indicators.py -v
    python3 -m pytest tests/test_indicators.py -v
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backtest_types import StockData
from indicators import compute_indicators, _sma, _vol_sma, _rolling_max


# ── Fixtures ────────────────────────────────────────────────────────────────


def make_stock(n_days: int = 200, seed: int = 42) -> StockData:
    """Create a StockData with predictable prices and volumes."""
    np.random.seed(seed)
    dates = [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n_days)]
    closes = [100.0]
    for i in range(1, n_days):
        closes.append(closes[-1] * (1 + np.random.normal(0.0005, 0.015)))
    volumes = [1_000_000 + int(abs(np.random.normal(0, 500_000))) for _ in range(n_days)]
    return StockData(
        symbol="TEST.TW",
        name="Test",
        dates=dates,
        closes=closes,
        volumes=volumes,
    )


# ── Basic smoke tests ───────────────────────────────────────────────────────


def test_all_keys_present():
    stock = make_stock(200)
    ind = compute_indicators(stock)

    expected = {
        "ma5", "ma10", "ma20", "ma60",
        "vol_ma5", "vol_ma60",
        "obv", "high_60", "high_120",
        "close_pct_change", "vol_ratio_vs_5d",
    }
    assert set(ind.keys()) == expected
    n = len(stock.dates)
    for key in expected:
        assert len(ind[key]) == n, f"{key} length {len(ind[key])} != {n}"


def test_all_arrays_float64():
    stock = make_stock(50)
    ind = compute_indicators(stock)
    for key, arr in ind.items():
        assert arr.dtype == np.float64, f"{key} dtype is {arr.dtype}, not float64"


# ── Look-ahead bias: price MAs (inclusive) ──────────────────────────────────


def test_price_ma_inclusive():
    """Price MAs at index i use close[i] (inclusive)."""
    closes = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    ma5 = _sma(closes, 5)
    # First 4 should be NaN
    for i in range(4):
        assert np.isnan(ma5[i]), f"ma5[{i}] should be NaN, got {ma5[i]}"
    # ma5[4] = mean(close[0:5]) = (100+101+102+103+104)/5 = 102
    assert abs(ma5[4] - 102.0) < 0.001
    # ma5[5] = mean(close[1:6]) = (101+102+103+104+105)/5 = 103
    assert abs(ma5[5] - 103.0) < 0.001


def test_price_ma_10_lookahead():
    """ma10[i] is mean(close[i-9:i+1]), not close[i-9:i+1] shifted."""
    n = 100
    closes = np.full(n, 100.0)
    closes[-1] = 200.0  # spike at last day
    stock = StockData(
        symbol="X.TW", name="X",
        dates=[f"2024-01-{i:02d}" for i in range(1, n + 1)],
        closes=closes.tolist(),
        volumes=[1000] * n,
    )
    ind = compute_indicators(stock)
    # ma10[99] should include close[99]=200.0
    # mean(close[90:100]) = (9*100 + 200)/10 = 110
    assert abs(ind["ma10"][-1] - 110.0) < 0.001


# ── Look-ahead bias: volume MAs (exclusive) ─────────────────────────────────


def test_vol_ma5_excludes_current():
    """vol_ma5[i] uses volume[i-5:i], NOT volume[i]."""
    volumes = np.array([10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
    vol_ma5 = _vol_sma(volumes, 5)

    # vol_ma5[0] = NaN (no prior days)
    assert np.isnan(vol_ma5[0])

    # vol_ma5[1] = mean of volume[0:1] = 10
    assert abs(vol_ma5[1] - 10.0) < 0.01

    # vol_ma5[2] = mean of volume[0:2] = 15
    assert abs(vol_ma5[2] - 15.0) < 0.01

    # vol_ma5[3] = mean of volume[0:3] = 20
    assert abs(vol_ma5[3] - 20.0) < 0.01

    # vol_ma5[4] = mean of volume[0:4] = 25
    assert abs(vol_ma5[4] - 25.0) < 0.01

    # vol_ma5[5] = mean of volume[0:5] = 30
    assert abs(vol_ma5[5] - 30.0) < 0.01

    # vol_ma5[6] = mean of volume[1:6] = (20+30+40+50+60)/5 = 40
    assert abs(vol_ma5[6] - 40.0) < 0.01

    # vol_ma5[7] = mean of volume[2:7] = (30+40+50+60+70)/5 = 50
    assert abs(vol_ma5[7] - 50.0) < 0.01

    # vol_ma5[9] = mean of volume[4:9] = (50+60+70+80+90)/5 = 70
    assert abs(vol_ma5[9] - 70.0) < 0.01


def test_vol_ma5_does_not_include_current_at_exact_day():
    """vol_ma5[10] must NOT include volume[10]."""
    volumes = np.arange(1000000, 1000000 + 200 * 10000, 10000, dtype=float)
    vol_ma5 = _vol_sma(volumes, 5)

    expected = np.mean(volumes[5:10])
    actual = vol_ma5[10]

    # Should match exactly (excluding day 10)
    assert abs(actual - expected) < 0.01, (
        f"vol_ma5[10] = {actual:.1f}, expected {expected:.1f} "
        f"(mean of volume[5:10], excluding volume[10]={volumes[10]:.1f})"
    )

    # If it DID include day 10, it would be different
    biased = np.mean(volumes[5:11])
    assert abs(actual - biased) > 0.01, "vol_ma5[10] appears to include volume[10] (look-ahead bias!)"


def test_vol_ma60_excludes_current():
    """vol_ma60[i] uses volume[i-60:i], NOT volume[i]."""
    n = 200
    volumes = np.random.RandomState(0).randint(100000, 5000000, size=n).astype(float)
    vol_ma60 = _vol_sma(volumes, 60)

    # At i=120, should be mean of volume[60:120]
    expected = np.mean(volumes[60:120])
    assert abs(vol_ma60[120] - expected) / expected < 1e-10

    # At i=120, should NOT include volume[120]
    biased = np.mean(volumes[60:121])
    assert abs(vol_ma60[120] - biased) > 0.01


def test_vol_ma5_zero_at_current():
    """If vol_ma5[i] uses volume up to i-1, vol_ma5[5] = mean(vol[0:5])."""
    volumes = np.array([1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 9999999.0])
    vol_ma5 = _vol_sma(volumes, 5)

    # vol_ma5[5] = mean(1000, 2000, 3000, 4000, 5000) = 3000
    assert abs(vol_ma5[5] - 3000.0) < 0.01
    # vol_ma5[5] should NOT be dragged up by the 9999999 at index 5
    assert vol_ma5[5] < 5000.0, "vol_ma5[5] appears to include volume[5]=9999999"


# ── OBV ─────────────────────────────────────────────────────────────────────


def test_obv_basic_direction():
    """OBV should rise on up days, fall on down days, stay flat on flat days."""
    dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    closes = [100.0, 101.0, 99.0, 99.0, 105.0]
    volumes = [1000, 2000, 3000, 4000, 5000]

    stock = StockData(
        symbol="OBV.TW", name="OBV Test",
        dates=dates, closes=closes, volumes=volumes,
    )
    ind = compute_indicators(stock)

    obv = ind["obv"]
    # Day 0: base = vol[0] = 1000
    assert abs(obv[0] - 1000.0) < 0.01
    # Day 1: close up → +2000 → 3000
    assert abs(obv[1] - 3000.0) < 0.01
    # Day 2: close down → -3000 → 0
    assert abs(obv[2] - 0.0) < 0.01
    # Day 3: flat → unchanged → 0
    assert abs(obv[3] - 0.0) < 0.01
    # Day 4: close up → +5000 → 5000
    assert abs(obv[4] - 5000.0) < 0.01


def test_obv_monotonically_increasing_on_uptrend():
    """All closes up = OBV always increases."""
    n = 100
    dates = [f"2024-01-{i:02d}" for i in range(1, n + 1)]
    closes = [100.0 + i * 1.0 for i in range(n)]  # steady uptrend
    volumes = [1000 + i * 10 for i in range(n)]

    stock = StockData(
        symbol="UP.TW", name="Uptrend",
        dates=dates, closes=closes, volumes=volumes,
    )
    ind = compute_indicators(stock)

    obv = ind["obv"]
    for i in range(1, n):
        assert obv[i] == obv[i - 1] + volumes[i], f"OBV broke at i={i}"
    assert obv[-1] > obv[0] * 10, "OBV should be much higher at end"


def test_obv_single_day():
    """Single day stock: OBV = volume[0]."""
    stock = StockData(
        symbol="SINGLE.TW", name="One",
        dates=["2024-01-01"], closes=[100.0], volumes=[5000],
    )
    ind = compute_indicators(stock)
    assert abs(ind["obv"][0] - 5000.0) < 0.01


# ── Rolling highs ───────────────────────────────────────────────────────────


def test_rolling_max_basic():
    """high_60[i] = max(close[i-59:i+1])."""
    closes = np.full(200, 100.0)
    closes[150] = 150.0  # spike

    high_60 = _rolling_max(closes, 60)

    # Before spike: all max is 100
    for i in range(59, 150):
        assert abs(high_60[i] - 100.0) < 0.01, f"high_60[{i}] = {high_60[i]}"

    # After spike: max is 150 for next 60 days
    for i in range(150, 200):
        assert abs(high_60[i] - 150.0) < 0.01, f"high_60[{i}] = {high_60[i]}"

    # Spike day itself
    assert abs(high_60[150] - 150.0) < 0.01


def test_rolling_max_early_indices():
    """For i < window-1, rolling high uses available data."""
    closes = np.array([5.0, 3.0, 7.0, 2.0, 9.0])
    high_3 = _rolling_max(closes, 3)

    # i=0: max(5) = 5
    assert abs(high_3[0] - 5.0) < 0.01
    # i=1: max(5, 3) = 5
    assert abs(high_3[1] - 5.0) < 0.01
    # i=2: max(5, 3, 7) = 7
    assert abs(high_3[2] - 7.0) < 0.01
    # i=3: max(3, 7, 2) = 7
    assert abs(high_3[3] - 7.0) < 0.01
    # i=4: max(7, 2, 9) = 9
    assert abs(high_3[4] - 9.0) < 0.01


# ── Close % change ──────────────────────────────────────────────────────────


def test_close_pct_change():
    closes = [100.0, 105.0, 99.0]
    stock = StockData(
        symbol="PCT.TW", name="Pct",
        dates=["2024-01-01", "2024-01-02", "2024-01-03"],
        closes=closes, volumes=[1000, 1000, 1000],
    )
    ind = compute_indicators(stock)
    pct = ind["close_pct_change"]

    assert np.isnan(pct[0])  # no prior close
    assert abs(pct[1] - 0.05) < 0.001  # (105/100 - 1) = 0.05
    assert abs(pct[2] - (99.0 / 105.0 - 1)) < 0.001


# ── Volume ratio ────────────────────────────────────────────────────────────


def test_vol_ratio_vs_5d():
    """vol_ratio[i] = volume[i] / vol_ma5[i], NaN when vol_ma5=0."""
    stock = make_stock(200)
    ind = compute_indicators(stock)

    # Check at a few points
    for i in [10, 50, 100, 150]:
        if ind["vol_ma5"][i] > 0:
            expected = stock.volumes[i] / ind["vol_ma5"][i]
            assert abs(ind["vol_ratio_vs_5d"][i] - expected) < 0.001


def test_vol_ratio_nan_when_no_ma():
    """vol_ratio_vs_5d[0] should be NaN (vol_ma5[0] is NaN)."""
    stock = make_stock(10)
    ind = compute_indicators(stock)
    assert np.isnan(ind["vol_ratio_vs_5d"][0])


# ── Edge cases ──────────────────────────────────────────────────────────────


def test_single_day_stock():
    """Single trading day — everything computed without crashing."""
    stock = StockData(
        symbol="ONE.TW", name="OneDay",
        dates=["2024-01-01"], closes=[100.0], volumes=[1000],
    )
    ind = compute_indicators(stock)

    # All MAs should be NaN (not enough data)
    for key in ["ma5", "ma10", "ma20", "ma60"]:
        assert np.isnan(ind[key][0]), f"{key}[0] should be NaN"

    # vol_ma5 should be NaN at day 0
    assert np.isnan(ind["vol_ma5"][0])
    assert np.isnan(ind["vol_ma60"][0])

    # OBV = volume[0]
    assert ind["obv"][0] == 1000.0

    # high_60 and high_120 should be close[0]
    assert ind["high_60"][0] == 100.0
    assert ind["high_120"][0] == 100.0

    # close_pct_change[0] NaN
    assert np.isnan(ind["close_pct_change"][0])

    # vol_ratio NaN
    assert np.isnan(ind["vol_ratio_vs_5d"][0])


def test_two_day_stock():
    """Two trading days."""
    stock = StockData(
        symbol="TWO.TW", name="TwoDay",
        dates=["2024-01-01", "2024-01-02"],
        closes=[100.0, 102.0],
        volumes=[1000, 2000],
    )
    ind = compute_indicators(stock)

    # All MAs NaN (need at least 5/10/20/60)
    for key in ["ma5", "ma10", "ma20", "ma60"]:
        assert np.isnan(ind[key][0])
        assert np.isnan(ind[key][1])

    # vol_ma5: [NaN, 1000.0]
    assert np.isnan(ind["vol_ma5"][0])
    assert ind["vol_ma5"][1] == 1000.0

    # OBV: [1000, 3000] (both up days)
    assert ind["obv"][0] == 1000.0
    assert ind["obv"][1] == 3000.0


def test_short_stock_below_ma_windows():
    """Stock with 30 days — not enough for ma60, but others work."""
    n = 30
    dates = [f"2024-01-{i:02d}" for i in range(1, n + 1)]
    closes = [100.0 + i * 2.0 for i in range(n)]
    volumes = [1000] * n

    stock = StockData(
        symbol="SHORT.TW", name="Short",
        dates=dates, closes=closes, volumes=volumes,
    )
    ind = compute_indicators(stock)

    # ma5 should have values from index 4
    assert np.isnan(ind["ma5"][3])
    assert not np.isnan(ind["ma5"][4])
    assert not np.isnan(ind["ma5"][-1])

    # ma10 from index 9
    assert np.isnan(ind["ma10"][8])
    assert not np.isnan(ind["ma10"][9])

    # ma20 from index 19
    assert np.isnan(ind["ma20"][18])
    assert not np.isnan(ind["ma20"][19])

    # ma60 all NaN (not enough data)
    assert np.all(np.isnan(ind["ma60"]))

    # vol_ma60: with 30 days (< 60), early indices use available days
    # Day 0 = NaN, days 1-29 = mean of all prior (all 1000 in this test)
    assert np.isnan(ind["vol_ma60"][0])
    # Days 1-29 should be 1000 (all available prior days are 1000)
    for i in range(1, 30):
        assert abs(ind["vol_ma60"][i] - 1000.0) < 0.01, f"vol_ma60[{i}] = {ind['vol_ma60'][i]}"
    # vol_ma5: day 0 NaN, days 1-4 use available prior days, 5+ use full window
    assert np.isnan(ind["vol_ma5"][0])
    assert not np.isnan(ind["vol_ma5"][1])  # 1 prior day
    assert not np.isnan(ind["vol_ma5"][5])  # full 5-day window

    # OBV should all be non-NaN
    assert not np.any(np.isnan(ind["obv"]))


def test_empty_stock():
    """Empty stock (0 days) should not crash."""
    stock = StockData(
        symbol="EMPTY.TW", name="Empty",
        dates=[], closes=[], volumes=[],
    )
    ind = compute_indicators(stock)

    for key, arr in ind.items():
        assert len(arr) == 0, f"{key} should be empty array"


def test_ma_values_match_manual_computation():
    """Spot-check MA values against manual computation."""
    closes = [100.0 + i * 5.0 for i in range(100)]  # 100, 105, ..., 595
    volumes = [1000] * 100
    dates = [f"2024-{i:03d}" for i in range(100)]

    stock = StockData(
        symbol="MANUAL.TW", name="Manual",
        dates=dates, closes=closes, volumes=volumes,
    )
    ind = compute_indicators(stock)

    # ma20[19] = mean(close[0:20])
    expected_ma20_19 = sum(closes[0:20]) / 20
    assert abs(ind["ma20"][19] - expected_ma20_19) < 0.01

    # ma20[20] = mean(close[1:21])
    expected_ma20_20 = sum(closes[1:21]) / 20
    assert abs(ind["ma20"][20] - expected_ma20_20) < 0.01

    # ma5[99] = mean(close[95:100])
    expected_ma5_99 = sum(closes[95:100]) / 5
    assert abs(ind["ma5"][99] - expected_ma5_99) < 0.01


# ── Performance / regression ────────────────────────────────────────────────


def test_large_stock_no_crash():
    """500-day stock computes without errors."""
    stock = make_stock(500)
    ind = compute_indicators(stock)
    assert len(ind["ma20"]) == 500
    assert not np.isnan(ind["obv"][-1])


def test_return_value_is_immutable_dict_copy():
    """Each call returns a fresh dict — not shared state."""
    stock1 = make_stock(50)
    stock2 = make_stock(50, seed=99)

    ind1 = compute_indicators(stock1)
    ind2 = compute_indicators(stock2)

    # They should NOT share array references
    assert ind1["ma5"] is not ind2["ma5"]
    # Values should differ (different seeds)
    assert not np.array_equal(ind1["close_pct_change"][1:], ind2["close_pct_change"][1:])
