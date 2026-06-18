"""
pattern_type1.py — Type 1 pattern: 底部沉寂後爆量 (Bottom Silence → Volume Explosion).

Detection logic (per stock, per day):
  1. Silence: recent 60d avg volume < 70% of prior 60d avg volume
  2. Explosion: current volume >= 3x the 5d avg volume
  3. Red candle: close up 3–7%
  4. Near high: close within 5% of 60-day high

Uses pre-computed indicators from indicators.py (already look-ahead-safe).
"""

from __future__ import annotations

from typing import Any, Dict, List

from backtest_types import StockData, Signal


def detect_type1(stock: StockData, indicators: Dict[str, List[float]]) -> List[Signal]:
    """
    Detect Type 1 pattern (bottom silence → volume explosion).

    Parameters
    ----------
    stock : StockData
        OHLCV data with at least 120 trading days.
    indicators : dict
        Pre-computed indicators with keys 'vol_ma60', 'vol_ma5', 'high_60'.
        Each value is a list of floats the same length as stock.dates.
        These already exclude the current day (no look-ahead bias).

    Returns
    -------
    list[Signal]
        Chronologically ordered signals. Empty if no pattern found.
    """
    n = len(stock.dates)

    # Edge case: insufficient data
    if n < 120:
        return []

    vol_ma60 = indicators.get('vol_ma60', [])
    vol_ma5 = indicators.get('vol_ma5', [])
    high_60 = indicators.get('high_60', [])

    signals: List[Signal] = []

    for i in range(120, n):
        # --- Step 1: Silence check ---
        # vol_ma60_before = mean of volume[i-60 : i]  (from indicator, excludes day i)
        # vol_ma60_earlier = mean of volume[i-120 : i-60]  (from indicator at i-60)
        vol_ma60_before = vol_ma60[i]
        vol_ma60_earlier = vol_ma60[i - 60]

        # Skip if earlier period is zero (avoid division by zero)
        if vol_ma60_earlier == 0:
            continue

        silence_ratio = vol_ma60_before / vol_ma60_earlier
        if silence_ratio >= 0.7:
            continue  # not quiet enough

        # --- Step 2: Explosion check ---
        vol_ma5_before = vol_ma5[i]

        # Skip if 5d avg is zero (avoid division by zero)
        if vol_ma5_before == 0:
            continue

        volume_current = stock.volumes[i]
        if volume_current < vol_ma5_before * 3.0:
            continue  # not enough volume

        volume_ratio = volume_current / vol_ma5_before

        # --- Step 3: Red candle ---
        close_current = stock.closes[i]
        close_prev = stock.closes[i - 1]

        if close_current <= close_prev:
            continue  # not an up day

        pct_change = (close_current / close_prev - 1.0) * 100.0
        if pct_change < 3.0 or pct_change > 7.0:
            continue  # outside acceptable range

        # --- Step 4: Position check (near 60-day high) ---
        high_60_val = high_60[i]
        if high_60_val == 0:
            continue

        high_60_ratio = close_current / high_60_val
        if high_60_ratio < 0.95:
            continue  # too far from 60-day high

        # --- All conditions met: create signal ---
        signal = Signal(
            symbol=stock.symbol,
            name=stock.name,
            signal_date=stock.dates[i],
            pattern_type=1,
            entry_price=close_current,
            volume_ratio=volume_ratio,
            metadata={
                'vol_ma60_before': round(vol_ma60_before),
                'vol_ma60_earlier': round(vol_ma60_earlier),
                'silence_ratio': round(silence_ratio, 3),
                'pct_change': round(pct_change, 2),
                'high_60_ratio': round(high_60_ratio, 3),
            },
        )
        signals.append(signal)

    return signals
