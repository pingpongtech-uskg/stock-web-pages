"""Tests for pattern_type2.py — Continuous Mild Volume detection."""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from backtest_types import StockData, Signal

# Import the module under test
from pattern_type2 import detect_type2


def _make_stock(symbol="2330", name="台積電", days=200):
    """Helper to create a StockData with synthetic data."""
    dates = [f"2024-01-{d:02d}" for d in range(1, days + 1)]
    # Closing price: steady uptrend from 100 to 150
    closes = [100.0 + i * 0.25 for i in range(days)]
    # Volume: base of 10,000 with some spikes
    np.random.seed(42)
    volumes = [10000 + int(np.random.normal(0, 2000)) for _ in range(days)]
    return StockData(symbol=symbol, name=name, dates=dates, closes=closes, volumes=volumes)


def _make_indicators(days=200):
    """Helper to create indicator arrays."""
    np.random.seed(42)
    ma20 = np.array([100.0 + i * 0.25 for i in range(days)])  # trends with close
    ma60 = np.array([95.0 + i * 0.25 for i in range(days)])    # slightly below
    # OBV trending up (bullish accumulation)
    obv = np.cumsum(np.random.normal(500, 5000, days))
    # 120-day high — set to be well above current close
    high_120 = np.array([100.0 + i * 0.30 for i in range(days)])  # ~20% above close
    return {'ma20': ma20, 'ma60': ma60, 'obv': obv, 'high_120': high_120}


def _inject_mild_volume(stock, start_idx, num_days=6):
    """Make a stretch of days have volume > 1.5× MA5 (excluding current day).

    Sets each injected day's volume to 2.0× its own 5-day MA (computed
    in sequence from the growing volume list).  This guarantees the
    1.5× threshold is met regardless of overlapping MA5 windows.
    """
    volumes = stock.volumes  # mutable list, modified in place
    for j in range(start_idx, min(start_idx + num_days, len(volumes))):
        if j >= 5:
            ma5 = sum(volumes[max(0, j - 5):j]) / 5.0
            # 2× MA5 > 1.5× MA5 — safe margin above detection threshold
            volumes[j] = int(ma5 * 2.0)
        else:
            volumes[j] = 50000


def test_returns_list():
    """detect_type2 always returns a list."""
    stock = _make_stock(days=100)
    ind = _make_indicators(days=100)
    result = detect_type2(stock, ind)
    assert isinstance(result, list), f"Expected list, got {type(result)}"


def test_no_signals_on_short_data():
    """No signals when data is shorter than 60 days."""
    stock = _make_stock(days=30)
    ind = _make_indicators(days=30)
    result = detect_type2(stock, ind)
    assert len(result) == 0, f"Expected 0 signals for short data, got {len(result)}"


def test_no_signals_without_volume_spike():
    """No signals when volume is completely flat (no mild volume days)."""
    stock = _make_stock(days=200)
    # Flat volume
    for i in range(len(stock.volumes)):
        stock.volumes[i] = 10000
    ind = _make_indicators(days=200)
    result = detect_type2(stock, ind)
    # Even with price above MAs and OBV trending, volume condition should fail
    assert len(result) == 0, f"Expected 0 signals without volume spikes, got {len(result)}"


def test_signal_emitted_when_all_conditions_met():
    """Signal emitted when all 4 conditions are satisfied at day i."""
    stock = _make_stock(days=200)
    ind = _make_indicators(days=200)

    # Inject mild volume: 10 consecutive days at indices 80-89,
    # each set to 2× its own MA5 — guarantees 10/10 qualify
    _inject_mild_volume(stock, 80, 10)

    # Force day 89 (index 89) to clearly pass all non-volume conditions
    i = 89
    # Price above MAs
    ind['ma20'][i] = stock.closes[i] - 1.0
    ind['ma60'][i] = stock.closes[i] - 2.0
    # OBV at 60-day high (set obv[i] slightly above max for a new high)
    obv_vals = ind['obv']
    max_obv_60 = float(np.max(obv_vals[max(0, i - 59):i + 1]))
    ind['obv'][i] = max_obv_60 * 1.01  # above 60-day high, always passes
    # Price 10%+ below 120-day high
    ind['high_120'][i] = stock.closes[i] / 0.85  # ~17.6% above close

    result = detect_type2(stock, ind)
    assert len(result) >= 1, f"Expected at least 1 signal at day {i}, got {len(result)}"

    sig = result[0]
    assert sig.symbol == "2330"
    assert sig.name == "台積電"
    assert sig.pattern_type == 2
    assert isinstance(sig.entry_price, float)
    assert sig.entry_price > 0
    assert isinstance(sig.volume_ratio, float)
    assert "mild_days_count" in sig.metadata
    assert sig.metadata["mild_days_count"] >= 6


def test_signal_metadata_fields():
    """Signal metadata contains all required fields."""
    stock = _make_stock(days=200)
    ind = _make_indicators(days=200)
    _inject_mild_volume(stock, 80, 10)

    i = 89
    ind['ma20'][i] = stock.closes[i] - 1.0
    ind['ma60'][i] = stock.closes[i] - 2.0
    obv_vals = ind['obv']
    max_obv_60 = float(np.max(obv_vals[max(0, i - 59):i + 1]))
    ind['obv'][i] = max_obv_60 * 1.01
    ind['high_120'][i] = stock.closes[i] / 0.85

    result = detect_type2(stock, ind)
    assert len(result) >= 1

    sig = result[0]
    meta = sig.metadata
    assert "mild_days_count" in meta
    assert "ma20" in meta
    assert "ma60" in meta
    assert "obv_60d_ratio" in meta
    assert "pct_below_120d_high" in meta


def test_volume_ratio_correct():
    """volume_ratio is current volume / MA5 before day."""
    stock = _make_stock(days=200)
    ind = _make_indicators(days=200)
    _inject_mild_volume(stock, 80, 10)

    i = 89
    ind['ma20'][i] = stock.closes[i] - 1.0
    ind['ma60'][i] = stock.closes[i] - 2.0
    obv_vals = ind['obv']
    max_obv_60 = float(np.max(obv_vals[max(0, i - 59):i + 1]))
    ind['obv'][i] = max_obv_60 * 1.01
    ind['high_120'][i] = stock.closes[i] / 0.85

    result = detect_type2(stock, ind)
    assert len(result) >= 1

    sig = result[0]
    # volume_ratio should be > 1.5 since we inject at 2× MA5
    assert sig.volume_ratio > 1.5, f"Expected ratio > 1.5, got {sig.volume_ratio}"


def test_nan_ma_skips_day():
    """Days with NaN ma20/ma60 are skipped gracefully."""
    stock = _make_stock(days=200)
    ind = _make_indicators(days=200)
    _inject_mild_volume(stock, 80, 10)

    i = 89
    # Make ma20 NaN at day 89
    ind['ma20'][i] = np.nan
    ind['ma60'][i] = stock.closes[i] - 2.0
    obv_vals = ind['obv']
    max_obv_60 = float(np.max(obv_vals[max(0, i - 59):i + 1]))
    ind['obv'][i] = max_obv_60 * 1.01
    ind['high_120'][i] = stock.closes[i] / 0.85

    result = detect_type2(stock, ind)
    # Should not produce a signal for day 89 because ma20 is NaN
    for sig in result:
        assert stock.dates.index(sig.signal_date) != i, (
            "Shouldn't signal on NaN ma20 day"
        )


def test_obv_negative_works():
    """OBV comparison works correctly when OBV is negative (downtrend)."""
    stock = _make_stock(days=200)
    ind = _make_indicators(days=200)

    # Make OBV negative and trending upward (improving)
    obv_vals = np.linspace(-10000, 0, 200, dtype=float)
    ind['obv'] = obv_vals
    _inject_mild_volume(stock, 80, 10)

    i = 89
    ind['ma20'][i] = stock.closes[i] - 1.0
    ind['ma60'][i] = stock.closes[i] - 2.0
    # obv[i] at new high (above the 60-day max)
    max_obv_60 = float(np.max(obv_vals[max(0, i - 59):i + 1]))
    # Set obv[i] slightly above max → always passes the tolerance check
    ind['obv'][i] = max_obv_60 * 1.01
    ind['high_120'][i] = stock.closes[i] / 0.85

    result = detect_type2(stock, ind)
    assert len(result) >= 1, "Should work with negative OBV at new high"


def test_obv_within_tolerance_negative():
    """OBV within 2% of negative 60-day high also passes."""
    stock = _make_stock(days=200)
    ind = _make_indicators(days=200)

    # Negative OBV, trending up
    obv_vals = np.linspace(-10000, 0, 200, dtype=float)
    ind['obv'] = obv_vals
    _inject_mild_volume(stock, 80, 10)

    i = 89
    ind['ma20'][i] = stock.closes[i] - 1.0
    ind['ma60'][i] = stock.closes[i] - 2.0
    max_obv_60 = float(np.max(obv_vals[max(0, i - 59):i + 1]))
    # obv[i] is 1% below the max → should still pass (within 2% tolerance)
    ind['obv'][i] = max_obv_60 * 0.99
    ind['high_120'][i] = stock.closes[i] / 0.85

    result = detect_type2(stock, ind)
    assert len(result) >= 1, (
        f"Should pass with obv 1% below negative max "
        f"(obv={ind['obv'][i]:.1f}, max={max_obv_60:.1f})"
    )


def test_no_signal_if_price_too_close_to_120d_high():
    """No signal when price is within 10% of 120-day high (not 'not yet broken out')."""
    stock = _make_stock(days=200)
    ind = _make_indicators(days=200)

    # Force OBV really high so step 3 passes
    obv_vals = np.cumsum(np.ones(200) * 1000)
    ind['obv'] = obv_vals
    _inject_mild_volume(stock, 80, 10)

    i = 89
    ind['ma20'][i] = stock.closes[i] - 1.0
    ind['ma60'][i] = stock.closes[i] - 2.0
    # high_120 is only 5% above close → should fail step 4 (< 0.90 rule)
    ind['high_120'][i] = stock.closes[i] / 0.95

    result = detect_type2(stock, ind)
    # Should not signal on day 89
    for sig in result:
        assert stock.dates.index(sig.signal_date) != i


def test_signal_date_matches_correct_day():
    """Signal date is the trigger day, not any earlier day."""
    stock = _make_stock(symbol="0050", name="元大台灣50", days=200)
    ind = _make_indicators(days=200)

    # Create conditions at a specific later day
    _inject_mild_volume(stock, 130, 10)

    i = 139
    ind['ma20'][i] = stock.closes[i] - 1.0
    ind['ma60'][i] = stock.closes[i] - 2.0
    obv_vals = ind['obv']
    max_obv_60 = float(np.max(obv_vals[max(0, i - 59):i + 1]))
    ind['obv'][i] = max_obv_60 * 1.01
    ind['high_120'][i] = stock.closes[i] / 0.85

    result = detect_type2(stock, ind)
    assert len(result) >= 1
    assert result[0].symbol == "0050"
    assert result[0].signal_date == stock.dates[i]


def test_multiple_signals_emitted():
    """Multiple signals emitted when conditions persist across days."""
    stock = _make_stock(days=200)
    ind = _make_indicators(days=200)

    # Inject mild volume for 20 days (80-99)
    _inject_mild_volume(stock, 80, 20)

    # Set up conditions from day 89 through day 99
    for i in range(89, 100):
        ind['ma20'][i] = stock.closes[i] - 1.0
        ind['ma60'][i] = stock.closes[i] - 2.0
        obv_vals = ind['obv']
        max_obv_60 = float(np.max(obv_vals[max(0, i - 59):i + 1]))
        ind['obv'][i] = max_obv_60 * 1.01
        ind['high_120'][i] = stock.closes[i] / 0.85

    result = detect_type2(stock, ind)
    assert len(result) > 1, (
        f"Expected multiple signals, got {len(result)}"
    )


if __name__ == "__main__":
    import inspect
    errors = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✅ {name}")
            except Exception as e:
                print(f"  ❌ {name}: {e}")
                errors += 1
    print(f"\n{errors} failures")
    sys.exit(errors)
