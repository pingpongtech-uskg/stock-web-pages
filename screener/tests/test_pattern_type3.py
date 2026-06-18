"""Tests for pattern_type3.py — Breakout Volume Explosion"""
import json, os, sys, tempfile
from unittest.mock import patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_types import StockData, Signal
from pattern_type3 import detect_type3


def _make_stock(symbol="2330.TW", name="台積電", close=None, volume=None, dates=None):
    """Helper to create a StockData instance using backtest_types.StockData."""
    n = len(close) if close else 200
    return StockData(
        symbol=symbol,
        name=name,
        dates=dates or [f"2024-{(i//30+1):02d}-{(i%30+1):02d}" for i in range(n)],
        closes=close or [100.0] * n,
        volumes=volume or [1000000] * n,
    )


# ── Step 1: Breakout from 120d consolidation ──


def test_no_breakout_no_signal():
    """No signal when close stays below previous 120d high."""
    close = [100.0] * 200  # flat line, never breaks out
    stock = _make_stock(close=close)
    signals = detect_type3(stock, {})
    assert len(signals) == 0


def test_breakout_at_precisely_threshold():
    """Signal when close == previous_120d_high (barely breaks out)."""
    close = [50.0] * 120 + [100.0] * 80  # last 80 at 100
    volume = [100000] * 200
    volume[120] = 300000  # 3x
    stock = _make_stock(close=close, volume=volume)
    signals = detect_type3(stock, {}, ohlc_cache_dir=None)
    assert len(signals) >= 1
    assert signals[0].pattern_type == 3
    assert signals[0].entry_price == 100.0


def test_below_120d_high_no_signal():
    """No signal when close is below previous 120d high."""
    close = [100.0] * 120 + [99.0] * 80  # never breaks 100
    volume = [100000] * 200
    volume[120] = 300000
    stock = _make_stock(close=close, volume=volume)
    signals = detect_type3(stock, {})
    assert len(signals) == 0


# ── Step 2: Volume explosion ──


def test_volume_too_low_no_signal():
    """No signal when volume is below 2.5x MA5."""
    close = [50.0] * 120 + [100.0] * 80  # breakout at day 120
    volume = [100000] * 200
    volume[120] = 200000  # only 2x, below 2.5x threshold
    stock = _make_stock(close=close, volume=volume)
    signals = detect_type3(stock, {})
    assert len(signals) == 0


def test_volume_exactly_threshold():
    """Signal when volume is exactly 2.5x MA5."""
    close = [50.0] * 120 + [100.0] * 80
    volume = [100000] * 200
    volume[120] = 250000  # exactly 2.5x
    stock = _make_stock(close=close, volume=volume)
    signals = detect_type3(stock, {})
    assert len(signals) >= 1


# ── Step 3: OHLC / approximation ──


@patch("pattern_type3._fetch_ohlc_finmind", return_value=None)
def test_approximation_mode_works(mock_fetch):
    """When ohlc_cache_dir=None and FinMind unavailable, use approximation: close up >1% = pass."""
    close = [50.0] * 120 + [52.0] * 80  # close[120]=52 > close[119]=50, +4% > 1%
    volume = [100000] * 200
    volume[120] = 300000
    stock = _make_stock(close=close, volume=volume)
    signals = detect_type3(stock, {}, ohlc_cache_dir=None)
    assert len(signals) >= 1
    assert signals[0].metadata.get('ohlc_source') == 'approximated'
    # close_position should be None in approximation mode
    assert signals[0].metadata.get('close_position') is None


@patch("pattern_type3._fetch_ohlc_finmind", return_value=None)
def test_approximation_fails_when_close_drops(mock_fetch):
    """Approximation fails when close doesn't rise > 1%."""
    close = [50.0] * 120 + [50.4] * 80  # only +0.8%, not > 1%
    volume = [100000] * 200
    volume[120] = 300000
    stock = _make_stock(close=close, volume=volume)
    signals = detect_type3(stock, {}, ohlc_cache_dir=None)
    assert len(signals) == 0


def test_ohlc_from_cache():
    """Use OHLC cache when available."""
    close = [50.0] * 120 + [100.0] * 80
    volume = [100000] * 200
    volume[120] = 300000

    stock = _make_stock(close=close, volume=volume)
    signal_date = stock.dates[120]

    # Create an OHLC cache entry where close is in top 30%
    ohlc_data = {
        "symbol": "2330.TW",
        "data": {
            signal_date: {"open": 90.0, "high": 105.0, "low": 88.0, "close": 100.0}
        },
    }
    # range = 105 - 88 = 17, close_position = (100-88)/17 = 0.706 ≥ 0.70 ✓

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = os.path.join(tmpdir, "ohlc_cache")
        os.makedirs(cache_dir)
        with open(os.path.join(cache_dir, "2330.TW.json"), "w") as f:
            json.dump(ohlc_data, f)
        signals = detect_type3(stock, {}, ohlc_cache_dir=cache_dir)

    assert len(signals) >= 1
    assert signals[0].metadata.get('ohlc_source') == 'cache'
    assert signals[0].metadata.get('close_position') is not None
    assert signals[0].metadata.get('close_position') >= 0.70


def test_ohlc_close_below_range():
    """No signal when OHLC shows close NOT in top 30%."""
    close = [50.0] * 120 + [100.0] * 80
    volume = [100000] * 200
    volume[120] = 300000

    stock = _make_stock(close=close, volume=volume)
    signal_date = stock.dates[120]

    # close_position = (100-88)/(120-88) = 12/32 = 0.375 < 0.70
    ohlc_data = {
        "symbol": "2330.TW",
        "data": {
            signal_date: {"open": 90.0, "high": 120.0, "low": 88.0, "close": 95.0}
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = os.path.join(tmpdir, "ohlc_cache")
        os.makedirs(cache_dir)
        with open(os.path.join(cache_dir, "2330.TW.json"), "w") as f:
            json.dump(ohlc_data, f)
        signals = detect_type3(stock, {}, ohlc_cache_dir=cache_dir)

    assert len(signals) == 0


# ── Edge cases ──


def test_insufficient_data():
    """No signal when less than 121 data points."""
    close = [100.0] * 100
    stock = _make_stock(close=close)
    signals = detect_type3(stock, {})
    assert len(signals) == 0


def test_nan_handling():
    """Handle NaN values gracefully."""
    close = [50.0] * 120 + [100.0] + [float('nan')] * 79
    volume = [100000] * 200
    volume[120] = 300000
    stock = _make_stock(close=close, volume=volume)
    signals = detect_type3(stock, {}, ohlc_cache_dir=None)
    assert len(signals) >= 1  # day 120 should still work


def test_multiple_signals():
    """Detect multiple breakout signals across time."""
    # Create two breakouts separated by enough days
    n_days = 251  # enough for indices 0-250
    close = [50.0] * n_days
    close[130] = 100.0  # first breakout at index 130
    close[131:250] = [100.0] * (250 - 131)
    close[250] = 150.0  # second breakout at index 250

    volume = [100000] * n_days
    volume[130] = 300000  # first explosion
    volume[250] = 300000  # second explosion

    stock = _make_stock(close=close, volume=volume, dates=[
        f"2024-{(i//30+1):02d}-{(i%30+1):02d}" for i in range(n_days)
    ])
    signals = detect_type3(stock, {}, ohlc_cache_dir=None)
    assert len(signals) == 2


def test_signal_metadata():
    """Signal metadata contains expected fields."""
    close = [50.0] * 120 + [105.0] * 80
    volume = [100000] * 200
    volume[120] = 300000  # 3x
    stock = _make_stock(close=close, volume=volume)
    signals = detect_type3(stock, {}, ohlc_cache_dir=None)
    assert len(signals) >= 1
    sig = signals[0]
    assert sig.symbol == "2330.TW"
    assert sig.pattern_type == 3
    assert sig.entry_price == 105.0
    assert sig.volume_ratio == pytest.approx(3.0, rel=0.01)
    assert 'prev_120d_high' in sig.metadata
    assert 'breakout_pct' in sig.metadata
    assert 'close_position' in sig.metadata
    assert 'ohlc_source' in sig.metadata
    assert sig.metadata['prev_120d_high'] == 50.0
    assert sig.metadata['breakout_pct'] == pytest.approx(110.0, rel=0.01)  # (105/50-1)*100 = 110%
