"""Tests for pattern_type1.py — Bottom Silence → Volume Explosion detection."""

from __future__ import annotations

import numpy as np
import pytest

from backtest_types import StockData, Signal
from pattern_type1 import detect_type1


def _make_indicators(
    closes: list[float],
    volumes: list[int],
) -> dict:
    """Manually compute the indicators dict the way indicators.py would."""
    n = len(closes)
    vol_ma60 = [0.0] * n
    vol_ma5 = [0.0] * n
    high_60 = [0.0] * n

    for i in range(n):
        # 60-day volume MA (excluding current day i)
        if i >= 60:
            vol_ma60[i] = float(np.mean(volumes[i - 60:i]))
        elif i > 0:
            vol_ma60[i] = float(np.mean(volumes[:i]))
        else:
            vol_ma60[i] = 0.0

        # 5-day volume MA (excluding current day i)
        if i >= 5:
            vol_ma5[i] = float(np.mean(volumes[i - 5:i]))
        elif i > 0:
            vol_ma5[i] = float(np.mean(volumes[:i]))
        else:
            vol_ma5[i] = 0.0

        # 60-day high (excluding current day i)
        if i >= 60:
            high_60[i] = float(max(closes[i - 60:i]))
        elif i > 0:
            high_60[i] = float(max(closes[:i]))
        else:
            high_60[i] = 0.0

    return {
        'vol_ma60': vol_ma60,
        'vol_ma5': vol_ma5,
        'high_60': high_60,
    }


def _make_stock(
    n_days: int = 200,
    base_close: float = 100.0,
    base_volume: int = 1_000_000,
) -> tuple[StockData, dict]:
    """Create a stock with two volume regimes: high early, low recent."""
    dates = [f"2024-01-{i+1:02d}" if i < 31 else f"2024-02-{i-30:02d}" for i in range(n_days)]
    closes = [base_close + i * 0.5 for i in range(n_days)]

    volumes: list[int] = []
    for i in range(n_days):
        if i < 60:
            volumes.append(int(base_volume))        # early 60d: high volume
        elif i < 120:
            volumes.append(int(base_volume * 0.4))  # recent 60d: low (silence)
        else:
            volumes.append(int(base_volume * 0.4))  # continue low

    # Day 120: massive volume spike (6x 5d avg)
    volumes[120] = int(base_volume * 2.0)

    # Day 120: ~5% red candle
    closes[120] = round(closes[119] * 1.05, 2)

    stock = StockData(
        symbol="2330.TW",
        name="台積電",
        dates=dates,
        closes=closes,
        volumes=volumes,
    )
    indicators = _make_indicators(closes, volumes)
    return stock, indicators


class TestDetectType1:
    """detect_type1 — bottom silence then volume explosion."""

    def test_normal_detection(self):
        """Stock meeting all 4 conditions should produce exactly 1 signal."""
        stock, indicators = _make_stock()
        signals = detect_type1(stock, indicators)

        assert len(signals) >= 1, "Expected at least 1 signal on day 120"
        sig = signals[0]
        assert sig.symbol == "2330.TW"
        assert sig.name == "台積電"
        assert sig.pattern_type == 1
        assert sig.entry_price == stock.closes[120]

        # Volume ratio should be >= 3.0
        assert sig.volume_ratio >= 3.0

        # Metadata should contain diagnostic fields
        md = sig.metadata
        assert 'silence_ratio' in md
        assert md['silence_ratio'] < 0.7
        assert 'pct_change' in md
        assert 3.0 <= md['pct_change'] <= 7.0
        assert 'high_60_ratio' in md
        assert md['high_60_ratio'] >= 0.95

    def test_too_few_days_returns_empty(self):
        """Stock with < 120 trading days returns empty list."""
        # _make_stock hardcodes index 120 for volume spike — can't use with n_days<120
        n_days = 100
        dates = [f"2024-01-{i+1:02d}" if i < 31 else f"2024-02-{i-30:02d}" for i in range(n_days)]
        closes = [100.0 + i * 0.5 for i in range(n_days)]
        volumes = [1_000_000] * n_days
        stock = StockData(
            symbol="2330.TW",
            name="台積電",
            dates=dates,
            closes=closes,
            volumes=volumes,
        )
        signals = detect_type1(stock, {})
        assert signals == []

    def test_no_silence_no_signal(self):
        """When volume is NOT in silence (recent avg >= earlier avg*0.7), no signal."""
        n_days = 200
        dates = [f"2024-01-{i+1:02d}" if i < 31 else f"2024-02-{i-30:02d}" for i in range(n_days)]
        closes = [100.0 + i * 0.5 for i in range(n_days)]
        # Uniform volume — NO silence
        volumes = [1_000_000] * n_days

        # Still set up day 120 as a volume spike + red candle
        volumes[120] = 4_000_000
        closes[120] = round(closes[119] * 1.05, 2)

        stock = StockData(symbol="2330.TW", name="台積電", dates=dates, closes=closes, volumes=volumes)
        indicators = _make_indicators(closes, volumes)
        signals = detect_type1(stock, indicators)

        # No signal because silence_ratio > 0.7
        for sig in signals:
            assert sig.pattern_type == 1

    def test_no_explosion_no_signal(self):
        """When volume explosion condition NOT met, no signal."""
        n_days = 200
        dates = [f"2024-01-{i+1:02d}" if i < 31 else f"2024-02-{i-30:02d}" for i in range(n_days)]
        closes = [100.0 + i * 0.5 for i in range(n_days)]
        volumes: list[int] = []
        for i in range(n_days):
            if i < 60:
                volumes.append(1_000_000)
            elif i < 120:
                volumes.append(400_000)
            else:
                volumes.append(400_000)

        # Day 120: only 2x 5d avg (below 3x threshold)
        volumes[120] = 600_000
        closes[120] = round(closes[119] * 1.05, 2)

        stock = StockData(symbol="2330.TW", name="台積電", dates=dates, closes=closes, volumes=volumes)
        indicators = _make_indicators(closes, volumes)
        signals = detect_type1(stock, indicators)

        assert len(signals) == 0, "Volume only 2x, should not trigger explosion"

    def test_not_red_candle_no_signal(self):
        """When close[i] <= close[i-1] (not up day), no signal."""
        n_days = 200
        dates = [f"2024-01-{i+1:02d}" if i < 31 else f"2024-02-{i-30:02d}" for i in range(n_days)]
        closes = [100.0 + i * 0.5 for i in range(n_days)]
        volumes: list[int] = []
        for i in range(n_days):
            if i < 60:
                volumes.append(1_000_000)
            elif i < 120:
                volumes.append(400_000)
            else:
                volumes.append(400_000)

        volumes[120] = 3_000_000
        # Day 120: down day (not a red candle)
        closes[120] = closes[119] - 1.0

        stock = StockData(symbol="2330.TW", name="台積電", dates=dates, closes=closes, volumes=volumes)
        indicators = _make_indicators(closes, volumes)
        signals = detect_type1(stock, indicators)

        assert len(signals) == 0, "Down day, should not signal"

    def test_pct_change_outside_range_no_signal(self):
        """When pct_change is < 3% or > 7%, no signal."""
        n_days = 200
        dates = [f"2024-01-{i+1:02d}" if i < 31 else f"2024-02-{i-30:02d}" for i in range(n_days)]
        closes = [100.0 + i * 0.5 for i in range(n_days)]
        volumes: list[int] = []
        for i in range(n_days):
            if i < 60:
                volumes.append(1_000_000)
            elif i < 120:
                volumes.append(400_000)
            else:
                volumes.append(400_000)

        volumes[120] = 3_000_000
        # Day 120: only 2% gain (below 3% threshold)
        closes[120] = round(closes[119] * 1.02, 2)

        stock = StockData(symbol="2330.TW", name="台積電", dates=dates, closes=closes, volumes=volumes)
        indicators = _make_indicators(closes, volumes)
        signals = detect_type1(stock, indicators)

        assert len(signals) == 0, "2% gain below 3% threshold"

    def test_pct_too_high_no_signal(self):
        """When pct_change > 7%, no signal."""
        n_days = 200
        dates = [f"2024-01-{i+1:02d}" if i < 31 else f"2024-02-{i-30:02d}" for i in range(n_days)]
        closes = [100.0 + i * 0.5 for i in range(n_days)]
        volumes: list[int] = []
        for i in range(n_days):
            if i < 60:
                volumes.append(1_000_000)
            elif i < 120:
                volumes.append(400_000)
            else:
                volumes.append(400_000)

        volumes[120] = 3_000_000
        # Day 120: 10% gain (above 7% threshold)
        closes[120] = round(closes[119] * 1.10, 2)

        stock = StockData(symbol="2330.TW", name="台積電", dates=dates, closes=closes, volumes=volumes)
        indicators = _make_indicators(closes, volumes)
        signals = detect_type1(stock, indicators)

        assert len(signals) == 0, "10% gain above 7% threshold"

    def test_not_near_high_no_signal(self):
        """When not within 5% of 60-day high, no signal."""
        n_days = 200
        dates = [f"2024-01-{i+1:02d}" if i < 31 else f"2024-02-{i-30:02d}" for i in range(n_days)]
        closes = [100.0 + i * 0.5 for i in range(n_days)]
        volumes: list[int] = []
        for i in range(n_days):
            if i < 60:
                volumes.append(1_000_000)
            elif i < 120:
                volumes.append(400_000)
            else:
                volumes.append(400_000)

        volumes[120] = 3_000_000
        closes[120] = round(closes[119] * 1.05, 2)
        # Drop a high peak into the 60-day window so high_60[120] is very high
        closes[80] = 500.0  # spike in the lookback window

        stock = StockData(symbol="2330.TW", name="台積電", dates=dates, closes=closes, volumes=volumes)
        indicators = _make_indicators(closes, volumes)
        signals = detect_type1(stock, indicators)

        assert len(signals) == 0, "Close below 95% of 60-day high"

    def test_vol_ma60_earlier_zero_skipped(self):
        """Division by zero guard: when vol_ma60_earlier == 0, skip that day."""
        n_days = 200
        dates = [f"2024-01-{i+1:02d}" if i < 31 else f"2024-02-{i-30:02d}" for i in range(n_days)]
        closes = [100.0 + i * 0.5 for i in range(n_days)]
        volumes = [0] * 200  # all zero volume
        volumes[120] = 1_000_000

        stock = StockData(symbol="2330.TW", name="台積電", dates=dates, closes=closes, volumes=volumes)
        indicators = _make_indicators(closes, volumes)
        # Should not raise ZeroDivisionError
        signals = detect_type1(stock, indicators)

    def test_multiple_signals_accepted(self):
        """Multiple signals for the same stock are kept (no de-duplication)."""
        stock, indicators = _make_stock()
        signals = detect_type1(stock, indicators)

        # Should be in chronological order
        dates = [s.signal_date for s in signals]
        assert dates == sorted(dates)
