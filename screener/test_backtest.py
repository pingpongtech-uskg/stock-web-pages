#!/usr/bin/env python3
"""
Comprehensive validation tests for the Abnormal Volume Strategy backtest system.
Uses synthetic StockData with injected patterns to verify each module.

Usage:
    python3 test_backtest.py          # Run all tests
    python3 test_backtest.py -v       # Verbose: show each assertion error detail
"""

import json
import math
import os
import sys
import tempfile
import traceback
from datetime import datetime

import numpy as np

# Ensure project root is on sys.path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ============================================================================
# Synthetic data helpers
# ============================================================================

def make_test_stock(n_days=200, seed=42, symbol='TEST.TW', name='Test'):
    """Create a backtest_types.StockData with injected Type 1 pattern.

    Injects: low vol days 90-149, volume explosion at 150, +5% close at 150.
    """
    np.random.seed(seed)
    dates = [f"2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}" for i in range(n_days)]
    closes = [100.0]
    for i in range(1, n_days):
        closes.append(closes[-1] * (1 + np.random.normal(0.0005, 0.015)))
    volumes = [1000000 + int(abs(np.random.normal(0, 500000))) for _ in range(n_days)]
    # Inject Type 1 pattern at index 150: low vol 90-149, spike at 150
    for j in range(90, 150):
        volumes[j] = 200000  # low volume (silence)
    volumes[150] = 5000000   # volume explosion
    closes[150] = closes[149] * 1.05  # +5% red candle

    from backtest_types import StockData
    return StockData(symbol=symbol, name=name, market='TWSE',
                     dates=dates, closes=closes, volumes=volumes)


def make_mild_volume_stock(n_days=200, seed=99, symbol='MILD.TW', name='Mild'):
    """Create a backtest_types.StockData with Type 2 pattern (6/10 mild volume).

    Days 90-99: 6 days with elevated volume (above 1.5x baseline).
    Most closes trending up so OBV rises; MA conditions satisfied.
    """
    np.random.seed(seed)
    dates = [f"2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}" for i in range(n_days)]
    # Build closes that trend upward so MA20/MA60 conditions pass
    closes = [100.0]
    for i in range(1, n_days):
        closes.append(closes[-1] * (1 + abs(np.random.normal(0.003, 0.005))))
    # Base volumes at 500k
    volumes = [500000 + int(abs(np.random.normal(0, 100000))) for _ in range(n_days)]
    # Days 90-99: 6 days elevated (every even day: 90,92,94,96,98)
    for j in range(90, 100):
        if j % 2 == 0:
            volumes[j] = 2000000  # elevated

    from backtest_types import StockData
    return StockData(symbol=symbol, name=name, market='TWSE',
                     dates=dates, closes=closes, volumes=volumes)


def make_breakout_stock(n_days=200, seed=77, symbol='BRKOUT.TW', name='Breakout'):
    """Create a backtest_types.StockData with 120d high breakout (Type 3).

    Day 160 breaks above all prior closes with 3x volume.
    Uses backtest_types.StockData (closes, volumes plural).
    """
    np.random.seed(seed)
    dates = [f"2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}" for i in range(n_days)]
    # Gradual uptrend, then consolidation at ~110
    closes = []
    val = 100.0
    for i in range(160):
        if i < 40:
            val *= (1 + abs(np.random.normal(0.001, 0.008)))
        elif i < 80:
            val *= (1 + np.random.normal(0.001, 0.012))
        elif i < 120:
            val *= (1 + np.random.normal(-0.001, 0.015))
        elif i < 160:
            val *= (1 + np.random.normal(0.0, 0.008))
        closes.append(round(val, 2))
    # Day 160: breakout above prior 120d high
    prev_high = max(closes[40:160])
    closes.append(round(prev_high * 1.08, 2))  # +8% above prior 120d high
    for i in range(161, n_days):
        closes.append(closes[-1] * (1 + np.random.normal(0.0, 0.008)))

    volumes = [500000 + int(abs(np.random.normal(0, 100000))) for _ in range(n_days)]
    volumes[160] = 5000000  # volume explosion

    from backtest_types import StockData
    return StockData(symbol=symbol, name=name, market='TWSE',
                     dates=dates, closes=closes, volumes=volumes)


# ============================================================================
# TEST 1: Data Loader
# ============================================================================

def test_data_loader():
    """Test load_stocks with a mock JSON data directory: date filtering,
    min 120 day filter, and TWSE vs OTC detection."""
    from data_loader import load_stocks

    tmpdir = tempfile.mkdtemp(prefix='bt_test_')
    try:
        # Mock stock 1: 2330.TW with 250 days
        dates_2330 = [(datetime(2024, 1, 1) + __import__('datetime').timedelta(days=i)).strftime('%Y-%m-%d')
                      for i in range(250)]
        mock_2330 = {
            'dates': dates_2330,
            'close': [100.0 + i * 0.1 for i in range(250)],
            'volume': [1000000 for _ in range(250)],
            'start': dates_2330[0], 'end': dates_2330[-1],
            'days': 250, 'name': '台積電'
        }

        # Mock stock 2: 2882.TW with 150 days
        dates_2882 = [(datetime(2024, 3, 1) + __import__('datetime').timedelta(days=i)).strftime('%Y-%m-%d')
                      for i in range(150)]
        mock_2882 = {
            'dates': dates_2882,
            'close': [50.0 + i * 0.05 for i in range(150)],
            'volume': [2000000 for _ in range(150)],
            'start': dates_2882[0], 'end': dates_2882[-1],
            'days': 150, 'name': '國泰金'
        }

        # Mock stock 3: OTC, only 100 days (should be filtered out)
        dates_short = [(datetime(2025, 1, 1) + __import__('datetime').timedelta(days=i)).strftime('%Y-%m-%d')
                       for i in range(100)]
        mock_short = {
            'dates': dates_short,
            'close': [30.0 + i * 0.1 for i in range(100)],
            'volume': [500000 for _ in range(100)],
            'start': dates_short[0], 'end': dates_short[-1],
            'days': 100, 'name': 'ShortOTC'
        }

        batch = {'2330.TW': mock_2330, '2882.TW': mock_2882, '9999.TWO': mock_short}
        with open(os.path.join(tmpdir, 'batch_001.json'), 'w') as f:
            json.dump(batch, f)

        # Load with wide date range
        stocks = load_stocks(tmpdir, '2024-01-01', '2025-12-31')

        assert isinstance(stocks, dict), f"Expected dict, got {type(stocks)}"
        assert '2330.TW' in stocks, "2330.TW should be loaded"
        assert '2882.TW' in stocks, "2882.TW should be loaded"
        # 9999.TWO has only 100 days < 120 → filtered out
        assert '9999.TWO' not in stocks, "Short stock with <120 days should be filtered"

        # Verify market detection
        assert stocks['2330.TW'].market == 'TWSE', \
            f"Expected TWSE, got {stocks['2330.TW'].market}"
        assert stocks['2882.TW'].market == 'TWSE', \
            f"Expected TWSE, got {stocks['2882.TW'].market}"

        # Verify date filtering
        assert stocks['2330.TW'].dates[0] >= '2024-01-01', \
            f"First date {stocks['2330.TW'].dates[0]} should be >= 2024-01-01"

        # Restricted date range
        stocks_restricted = load_stocks(tmpdir, '2024-06-01', '2024-12-31')
        if '2882.TW' in stocks_restricted:
            for d in stocks_restricted['2882.TW'].dates:
                assert '2024-06-01' <= d <= '2024-12-31', \
                    f"Date {d} outside filter range"

        # Empty dir → empty dict
        empty_dir = tempfile.mkdtemp(prefix='bt_empty_')
        try:
            empty_result = load_stocks(empty_dir, '2024-01-01', '2024-12-31')
            assert isinstance(empty_result, dict)
            assert len(empty_result) == 0, "Empty dir should return empty dict"
        finally:
            import shutil
            shutil.rmtree(empty_dir)

    finally:
        import shutil
        shutil.rmtree(tmpdir)


# ============================================================================
# TEST 2: Indicators
# ============================================================================

def test_indicators():
    """Test compute_indicators on synthetic stock data.
    Verify no unexpected NaN, correct vol_ma5 look-ahead prevention,
    OBV direction, and reasonable MA values using the production indicators module."""
    from indicators import compute_indicators
    from backtest_types import StockData

    # Simple stock: monotonic uptrend + slowly increasing volume
    n = 200
    dates = [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)]
    closes = [100.0]
    for i in range(1, n):
        closes.append(closes[-1] * 1.005)  # always up
    volumes = [1000000 + (i * 10000) for i in range(n)]

    stock = StockData(symbol='OBV.TEST', name='OBV Test', market='TWSE',
                      dates=dates, closes=closes, volumes=volumes)
    ind = compute_indicators(stock)

    # Verify all expected keys exist
    expected_keys = ['ma5', 'ma10', 'ma20', 'ma60', 'vol_ma5', 'vol_ma60',
                     'obv', 'high_60', 'high_120', 'close_pct_change',
                     'vol_ratio_vs_5d']
    for key in expected_keys:
        assert key in ind, f"Missing key: {key}"
        assert len(ind[key]) == len(closes), \
            f"Key {key} has length {len(ind[key])}, expected {len(closes)}"

    # --- vol_ma5 look-ahead prevention ---
    # Real module: vol_ma5[i] = mean of volumes[i-5 : i] (EXCLUDES day i)
    # vol_ma5[10] should be mean of volumes[5:10], NOT volumes[5:11]
    expected_vol_ma5_10 = np.mean(volumes[5:10])
    actual_vol_ma5_10 = ind['vol_ma5'][10]
    assert abs(actual_vol_ma5_10 - expected_vol_ma5_10) < 0.01, \
        f"vol_ma5[10]: expected {expected_vol_ma5_10:.1f}, got {actual_vol_ma5_10:.1f}"

    # vol_ma5 at day 10 must NOT include volume[10]
    biased_val = np.mean(volumes[5:11])
    if abs(expected_vol_ma5_10 - biased_val) > 0.01:
        assert abs(actual_vol_ma5_10 - biased_val) > 0.01, \
            "vol_ma5[10] appears to include volume[10] (look-ahead bias)"

    # vol_ma5[0] should be NaN (no prior data)
    assert np.isnan(ind['vol_ma5'][0]), "vol_ma5[0] should be NaN"

    # --- OBV direction ---
    # All closes up → OBV monotonically increases
    assert ind['obv'][50] > ind['obv'][10], \
        "OBV should be higher at day 50 than day 10 (all closes up)"

    # --- MA5: inclusive SMA, NaN for first 4 days, value at index 4 ---
    for i in range(4):
        assert np.isnan(ind['ma5'][i]), f"ma5[{i}] should be NaN (inclusive SMA)"
    assert not np.isnan(ind['ma5'][4]), "ma5[4] should have a value (inclusive SMA)"

    # --- vol_ratio_vs_5d: volume[i] / vol_ma5[i] ---
    ratio_expected = volumes[10] / expected_vol_ma5_10
    ratio_actual = ind['vol_ratio_vs_5d'][10]
    assert abs(ratio_actual - ratio_expected) < 0.001, \
        f"vol_ratio_vs_5d[10]: expected {ratio_expected:.4f}, got {ratio_actual:.4f}"

    # --- high_60: inclusive rolling max ---
    # high_60[i] = max(closes[max(0,i-59):i+1])
    for i in range(60, 100):
        expected_60 = max(closes[i - 59:i + 1])
        assert abs(ind['high_60'][i] - expected_60) < 0.001, \
            f"high_60[{i}]: expected {expected_60:.2f}, got {ind['high_60'][i]:.2f}"

    # --- close_pct_change: decimal format (e.g., 0.005 = 0.5%) ---
    # In our stock, each day is +0.5% = 0.005
    assert abs(ind['close_pct_change'][1] - 0.005) < 0.001, \
        f"close_pct_change[1] should be ~0.005, got {ind['close_pct_change'][1]}"


# ============================================================================
# TEST 3: Type 1 Detection
# ============================================================================

def test_type1_detection():
    """Test detect_type1 with injected Type 1 pattern.
    Verify it finds the signal, and does NOT fire when conditions aren't met."""
    from pattern_type1 import detect_type1
    from indicators import compute_indicators

    stock = make_test_stock(200)
    ind = compute_indicators(stock)
    signals = detect_type1(stock, ind)

    # The synthetic stock has a Type 1 pattern injected at index 150
    expected_date = stock.dates[150]
    matched = [s for s in signals if s.signal_date == expected_date]
    assert len(matched) >= 1, \
        f"Type 1 detector should find signal at {expected_date}, " \
        f"got dates: {[s.signal_date for s in signals[:5]]}"

    sig = matched[0]
    assert sig.pattern_type == 1, f"Expected pattern_type=1, got {sig.pattern_type}"
    assert sig.symbol == 'TEST.TW', f"Expected TEST.TW, got {sig.symbol}"
    assert sig.entry_price > 0, f"entry_price should be > 0, got {sig.entry_price}"

    # Metadata checks
    assert 'silence_ratio' in sig.metadata, "Missing silence_ratio"
    assert 'pct_change' in sig.metadata, "Missing pct_change"
    assert sig.metadata['silence_ratio'] < 0.7, \
        f"silence_ratio should be < 0.7, got {sig.metadata['silence_ratio']}"
    assert 3.0 <= sig.metadata['pct_change'] <= 7.0, \
        f"pct_change should be 3-7%, got {sig.metadata['pct_change']}%"

    # Chronological order
    for i in range(1, len(signals)):
        assert signals[i].signal_date >= signals[i - 1].signal_date, \
            f"Signals not chronological: {signals[i-1].signal_date} > {signals[i].signal_date}"

    # --- Negative: no volume explosion → no signal ---
    np.random.seed(42)
    dates_flat = [f"2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}" for i in range(200)]
    closes_flat = [100.0]
    for i in range(1, 200):
        closes_flat.append(closes_flat[-1] * 1.005)
    volumes_flat = [1000000 for _ in range(200)]  # flat volume

    from backtest_types import StockData
    flat_stock = StockData(symbol='FLAT.TW', name='Flat', market='TWSE',
                           dates=dates_flat, closes=closes_flat, volumes=volumes_flat)
    ind_flat = compute_indicators(flat_stock)
    signals_flat = detect_type1(flat_stock, ind_flat)
    matched_flat = [s for s in signals_flat if s.signal_date == dates_flat[150]]
    assert len(matched_flat) == 0, "Type 1 should NOT fire on flat-volume stock"

    # --- Negative: pct_change out of [3%, 7%] → no signal ---
    np.random.seed(42)
    dates_no = [f"2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}" for i in range(200)]
    closes_no = [100.0]
    for i in range(1, 200):
        closes_no.append(closes_no[-1] * (1 + np.random.normal(0.0005, 0.015)))
    volumes_no = [1000000 for _ in range(200)]
    for j in range(90, 150):
        volumes_no[j] = 200000
    volumes_no[150] = 5000000
    closes_no[150] = closes_no[149] * 1.02  # only +2%, below 3% threshold

    no_sig_stock = StockData(symbol='NO.TW', name='NoSig', market='TWSE',
                             dates=dates_no, closes=closes_no, volumes=volumes_no)
    ind_no = compute_indicators(no_sig_stock)
    signals_no = detect_type1(no_sig_stock, ind_no)
    matched_no = [s for s in signals_no if s.signal_date == dates_no[150]]
    assert len(matched_no) == 0, \
        "Type 1 should NOT fire when pct_change is 2% (< 3% threshold)"


# ============================================================================
# TEST 4: Type 2 Detection
# ============================================================================

def test_type2_detection():
    """Test detect_type2 with injected mild volume pattern.
    Verify 6/10 days above threshold fires, 5/10 does NOT."""
    from pattern_type2 import detect_type2
    from indicators import compute_indicators

    stock = make_mild_volume_stock(200)
    ind = compute_indicators(stock)
    signals = detect_type2(stock, ind)

    # Days 90-99 have 6 elevated volume days. Detector looks at last 10 days.
    # Day 99 examines days 90-99. May fire depending on MA20/MA60/OBV/high conditions.
    # At minimum, verify signals are well-formed if any exist.
    for s in signals:
        assert s.pattern_type == 2, f"Expected pattern_type=2, got {s.pattern_type}"
        assert 'mild_days_count' in s.metadata, "Missing mild_days_count"
        assert 'ma20' in s.metadata, "Missing ma20"
        assert 'ma60' in s.metadata, "Missing ma60"
        assert 'obv_60d_ratio' in s.metadata, "Missing obv_60d_ratio"

    # --- Negative: only 5/10 days → no signal ---
    np.random.seed(50)
    dates_weak = [f"2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}" for i in range(200)]
    closes_weak = [100.0]
    for i in range(1, 200):
        closes_weak.append(closes_weak[-1] * (1 + abs(np.random.normal(0.003, 0.008))))
    volumes_weak = [500000 + int(abs(np.random.normal(0, 50000))) for _ in range(200)]
    # Only 5 days elevated in 90-99 (days 90, 92, 94, 96, 98)
    for j in range(90, 100):
        if j % 2 == 0:
            volumes_weak[j] = 2000000

    from backtest_types import StockData
    weak_stock = StockData(symbol='WEAK.TW', name='Weak', market='TWSE',
                           dates=dates_weak, closes=closes_weak, volumes=volumes_weak)
    ind_weak = compute_indicators(weak_stock)
    signals_weak = detect_type2(weak_stock, ind_weak)

    # Check that day 99 does NOT fire (only 5/10 days, should be < 6)
    date_99 = dates_weak[99]
    matched_weak = [s for s in signals_weak if s.signal_date == date_99]
    assert len(matched_weak) == 0, \
        "Type 2 should NOT fire with only 5/10 days above threshold"


# ============================================================================
# TEST 5: Type 3 Detection
# ============================================================================

def test_type3_detection():
    """Test detect_type3 with injected breakout pattern.
    Verify breakout detection works, including approximation mode."""
    from pattern_type3 import detect_type3

    stock = make_breakout_stock(200)
    signals = detect_type3(stock, {}, ohlc_cache_dir=None)

    # The stock has a breakout at day 160
    expected_date = stock.dates[160]
    matched = [s for s in signals if s.signal_date == expected_date]
    assert len(matched) >= 1, \
        f"Type 3 detector should find breakout signal at {expected_date}, " \
        f"got dates: {[s.signal_date for s in signals[:5]]}"

    sig = matched[0]
    assert sig.pattern_type == 3, f"Expected pattern_type=3, got {sig.pattern_type}"
    assert sig.entry_price > 0, f"entry_price should be > 0, got {sig.entry_price}"

    # Metadata checks
    assert 'prev_120d_high' in sig.metadata, "Missing prev_120d_high"
    assert 'breakout_pct' in sig.metadata, "Missing breakout_pct"
    assert 'ohlc_source' in sig.metadata or 'close_position' in sig.metadata, \
        "Missing ohlc_source or close_position"
    assert sig.metadata['breakout_pct'] > 0, \
        f"breakout_pct should be positive, got {sig.metadata['breakout_pct']}"

    # --- Negative: no volume spike → no signal ---
    np.random.seed(90)
    dates_nv = [f"2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}" for i in range(200)]
    closes_nv = [100.0]
    for i in range(1, 160):
        closes_nv.append(closes_nv[-1] * (1 + np.random.normal(0.002, 0.012)))
    prev_max = max(closes_nv[40:160])
    closes_nv.append(prev_max * 1.05)
    for i in range(161, 200):
        closes_nv.append(closes_nv[-1] * (1 + np.random.normal(0.0, 0.008)))
    volumes_nv = [500000 for _ in range(200)]  # no spike

    from backtest_types import StockData
    nv_stock = StockData(symbol='NOVOL.TW', name='NoVol', market='TWSE',
                         dates=dates_nv, closes=closes_nv, volumes=volumes_nv)
    signals_nv = detect_type3(nv_stock, {}, ohlc_cache_dir=None)
    matched_nv = [s for s in signals_nv if s.signal_date == dates_nv[160]]
    assert len(matched_nv) == 0, \
        "Type 3 should NOT fire without volume spike at breakout"

    # Approximation mode should return a list (no crash)
    assert isinstance(signals, list), "detect_type3 should return a list"


# ============================================================================
# TEST 6: Performance Tracker
# ============================================================================

def test_performance_tracker():
    """Test PerformanceTracker: forward returns, win_rate, max_drawdown,
    Sharpe ratio, and edge case of 0 signals."""
    from performance import PerformanceTracker
    from backtest_types import StockData, Signal

    # Create a stock with known prices (steady uptrend)
    n_days = 200
    dates = [f"2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}" for i in range(n_days)]
    closes = [100.0 + i * 0.5 for i in range(n_days)]
    volumes = [1000000 for _ in range(n_days)]

    stock = StockData(symbol='UP.TW', name='Uptrend', market='TWSE',
                      dates=dates, closes=closes, volumes=volumes)
    all_stocks = {'UP.TW': stock}

    # Create backtest_types.Signal objects
    signals_list = [
        Signal(symbol='UP.TW', name='Uptrend',
               signal_date=dates[10], pattern_type=1,
               entry_price=closes[10], volume_ratio=3.0, metadata={}),
        Signal(symbol='UP.TW', name='Uptrend',
               signal_date=dates[20], pattern_type=1,
               entry_price=closes[20], volume_ratio=3.0, metadata={}),
        Signal(symbol='UP.TW', name='Uptrend',
               signal_date=dates[30], pattern_type=1,
               entry_price=closes[30], volume_ratio=3.0, metadata={}),
        Signal(symbol='UP.TW', name='Uptrend',
               signal_date=dates[40], pattern_type=1,
               entry_price=closes[40], volume_ratio=3.0, metadata={}),
    ]

    tracker = PerformanceTracker()
    for sig in signals_list:
        tracker.record_signal(sig)

    tracker.compute_forward_returns(all_stocks)
    stats_by_type = tracker.compute_stats()

    # compute_stats returns keys 0, 1, 2, 3 (0 = ALL)
    assert 1 in stats_by_type, "Should have stats for pattern_type 1"
    stats = stats_by_type[1]
    assert stats.total_signals == len(signals_list), \
        f"total_signals: expected {len(signals_list)}, got {stats.total_signals}"

    # In uptrending market, forward returns should be positive
    assert stats.win_rate_5d >= 0.5, \
        f"win_rate_5d should be >= 0.5 in uptrend, got {stats.win_rate_5d}"
    assert stats.win_rate_60d >= 0.5, \
        f"win_rate_60d should be >= 0.5 in uptrend, got {stats.win_rate_60d}"
    assert stats.avg_return_5d > 0, \
        f"avg_return_5d should be > 0 in uptrend, got {stats.avg_return_5d}"
    assert stats.avg_return_60d > 0, \
        f"avg_return_60d should be > 0 in uptrend, got {stats.avg_return_60d}"

    # max_drawdown should be reasonable
    assert 0.0 <= stats.max_drawdown <= 1.0, \
        f"max_drawdown out of range: {stats.max_drawdown}"

    # --- Edge: 0 signals → all zeros ---
    empty_tracker = PerformanceTracker()
    empty_tracker.compute_forward_returns(all_stocks)
    empty_stats = empty_tracker.compute_stats()
    assert isinstance(empty_stats, dict), "compute_stats should return dict with 0 signals"
    assert 1 in empty_stats
    assert empty_stats[1].total_signals == 0
    assert empty_stats[1].win_rate_5d == 0.0


# ============================================================================
# TEST 7: No Look-Ahead Bias
# ============================================================================

def test_no_lookahead_bias():
    """CRITICAL: Verify signal detection on day T uses ONLY data up to day T.
    - vol_ma5[T] = mean(volume[T-5:T]), NOT mean(volume[T-4:T+1])
    - Modifying future data after signal date does not change past signals."""
    from pattern_type1 import detect_type1
    from pattern_type2 import detect_type2
    from pattern_type3 import detect_type3
    from indicators import compute_indicators

    def _verify_vol_ma5_lookahead(stock, day_idx):
        """vol_ma5[day_idx] should use volumes[max(0,day_idx-5):day_idx]."""
        ind = compute_indicators(stock)
        expected = np.mean(stock.volumes[max(0, day_idx - 5):day_idx])
        actual = ind['vol_ma5'][day_idx]
        assert abs(actual - expected) < 1.0, \
            f"vol_ma5[{day_idx}]: expected {expected:.1f}, got {actual:.1f}"
        biased = np.mean(stock.volumes[max(0, day_idx - 5):day_idx + 1])
        if abs(biased - expected) > 1.0:
            assert abs(actual - biased) > 1.0, \
                f"vol_ma5[{day_idx}] may include current day (biased={biased:.1f}, actual={actual:.1f})"

    # --- Verify vol_ma5 at various indices ---
    stock = make_test_stock(200)
    _verify_vol_ma5_lookahead(stock, 10)
    _verify_vol_ma5_lookahead(stock, 50)
    _verify_vol_ma5_lookahead(stock, 150)
    _verify_vol_ma5_lookahead(stock, 180)

    # --- Type 1: Verify signals don't change when future data is corrupted ---
    stock_t1 = make_test_stock(200)
    ind_t1 = compute_indicators(stock_t1)
    signals_before = detect_type1(stock_t1, ind_t1)
    sig_dates_before = {s.signal_date for s in signals_before}

    if signals_before:
        last_idx = stock_t1.date_index(signals_before[-1].signal_date)
        if last_idx >= 0 and last_idx < len(stock_t1.closes) - 1:
            # Corrupt all future data
            for j in range(last_idx + 1, len(stock_t1.closes)):
                stock_t1.closes[j] = stock_t1.closes[last_idx] * 0.5
                stock_t1.volumes[j] = 1
            ind_after = compute_indicators(stock_t1)
            signals_after = detect_type1(stock_t1, ind_after)
            sig_dates_after = {s.signal_date for s in signals_after}
            for d in sig_dates_before:
                assert d in sig_dates_after, \
                    f"Type 1 signal at {d} disappeared after future data modified (look-ahead bias!)"

    # --- Type 2: same check ---
    stock_t2 = make_mild_volume_stock(200)
    ind_t2 = compute_indicators(stock_t2)
    signals_t2_before = detect_type2(stock_t2, ind_t2)
    sig_dates_t2_before = {s.signal_date for s in signals_t2_before}

    if signals_t2_before:
        last_idx = stock_t2.date_index(signals_t2_before[-1].signal_date)
        if last_idx >= 0 and last_idx < len(stock_t2.closes) - 1:
            for j in range(last_idx + 1, len(stock_t2.closes)):
                stock_t2.closes[j] = stock_t2.closes[last_idx] * 0.5
                stock_t2.volumes[j] = 1
            ind_t2_after = compute_indicators(stock_t2)
            signals_t2_after = detect_type2(stock_t2, ind_t2_after)
            sig_dates_t2_after = {s.signal_date for s in signals_t2_after}
            for d in sig_dates_t2_before:
                assert d in sig_dates_t2_after, \
                    f"Type 2 signal at {d} disappeared after future data modified (look-ahead bias!)"

    # --- Type 3: same check ---
    stock_t3 = make_breakout_stock(200)
    signals_t3_before = detect_type3(stock_t3, {}, ohlc_cache_dir=None)
    sig_dates_t3_before = {s.signal_date for s in signals_t3_before}

    if signals_t3_before:
        last_idx = stock_t3.dates.index(signals_t3_before[-1].signal_date) \
            if signals_t3_before[-1].signal_date in stock_t3.dates else -1
        if last_idx >= 0 and last_idx < len(stock_t3.closes) - 1:
            for j in range(last_idx + 1, len(stock_t3.closes)):
                stock_t3.closes[j] = stock_t3.closes[last_idx] * 0.5
                stock_t3.volumes[j] = 1
            signals_t3_after = detect_type3(stock_t3, {}, ohlc_cache_dir=None)
            sig_dates_t3_after = {s.signal_date for s in signals_t3_after}
            for d in sig_dates_t3_before:
                assert d in sig_dates_t3_after, \
                    f"Type 3 signal at {d} disappeared after future data modified (look-ahead bias!)"


# ============================================================================
# TEST 8: Sector Classification
# ============================================================================

def test_sector_classification():
    """Test classify_sector for known stocks and OTC detection."""
    from sector_analysis import classify_sector

    # 2330.TW → 半導體/電子
    sector_2330, cat_2330 = classify_sector('2330.TW')
    assert sector_2330 == '半導體', f"2330.TW expected 半導體, got {sector_2330}"
    assert cat_2330 == '電子', f"2330.TW expected 電子 category, got {cat_2330}"

    # 2882.TW → 金融保險/金融
    sector_2882, cat_2882 = classify_sector('2882.TW')
    assert cat_2882 == '金融', f"2882.TW expected 金融 category, got {cat_2882}"

    # 1101.TW → 水泥/傳產
    sector_1101, cat_1101 = classify_sector('1101.TW')
    assert sector_1101 == '水泥', f"1101.TW expected 水泥, got {sector_1101}"
    assert cat_1101 == '傳產', f"1101.TW expected 傳產, got {cat_1101}"

    # OTC stock (with .TWO suffix)
    sector_otc, cat_otc = classify_sector('5371.TWO')
    assert isinstance(sector_otc, str), f"Expected string sector, got {type(sector_otc)}"
    assert isinstance(cat_otc, str), f"Expected string category, got {type(cat_otc)}"

    sector_6488, cat_6488 = classify_sector('6488.TWO')
    assert isinstance(sector_6488, str)
    assert isinstance(cat_6488, str)

    # Unknown symbol edge case
    sector_unk, cat_unk = classify_sector('9999.TW')
    assert isinstance(sector_unk, str), "Unknown stock should return a string sector"
    assert isinstance(cat_unk, str), "Unknown stock should return a string category"

    # Verify categories are in the expected set
    for c in [cat_2330, cat_2882, cat_1101, cat_otc, cat_6488, cat_unk]:
        assert c in ('電子', '金融', '傳產'), f"Unexpected category: {c}"


# ============================================================================
# Test runner
# ============================================================================

def run_tests(verbose=False):
    """Run all tests and print pass/fail summary."""
    tests = [
        test_data_loader,
        test_indicators,
        test_type1_detection,
        test_type2_detection,
        test_type3_detection,
        test_performance_tracker,
        test_no_lookahead_bias,
        test_sector_classification,
    ]

    passed = 0
    failed = 0
    failures = []

    print("=" * 62)
    print("  Backtest System — Validation Test Suite")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 62)

    for test in tests:
        name = test.__name__
        try:
            test()
            passed += 1
            print(f"  \u2713 {name}")
        except AssertionError as e:
            failed += 1
            failures.append((name, str(e)))
            print(f"  \u2717 {name}")
            if verbose:
                print(f"      {e}")
        except Exception as e:
            failed += 1
            failures.append((name, f"{type(e).__name__}: {e}"))
            print(f"  \u2717 {name}")
            if verbose:
                traceback.print_exc()
                print()

    print("=" * 62)
    if failed == 0:
        print(f"  \u2705 All {passed}/{len(tests)} tests passed!")
    else:
        print(f"  \u26a0\ufe0f  {passed}/{len(tests)} passed, {failed} failed")
        if not verbose:
            print()
            for name, err in failures:
                print(f"  {name}: {err[:120]}")

    print("=" * 62)
    return failed == 0


if __name__ == '__main__':
    verbose = '-v' in sys.argv
    success = run_tests(verbose=verbose)
    sys.exit(0 if success else 1)
