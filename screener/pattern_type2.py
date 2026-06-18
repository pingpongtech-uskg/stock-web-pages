"""
pattern_type2.py — Detect Type 2: 連續溫和放量 (Continuous Mild Volume Increase)

Smart Money Accumulation pattern:
- 6/10 days with volume 1.5× above short-term average (vol MA5 excluding current day)
- Price above both MA20 and MA60
- OBV at/near 60-day high (within 2%)
- Price still 10%+ below 120-day high (not yet breaking out)

Distinguishes from Type 1 (silence→explosion) and Type 3 (breakout).
"""

from __future__ import annotations

from typing import List, Dict

import numpy as np

from backtest_types import StockData, Signal


def detect_type2(stock: StockData, indicators: dict) -> List[Signal]:
    """
    Detect Type 2 (Continuous Mild Volume) signals.

    For each trading day i starting from index 60:
      1. At least 6 of the last 10 days have volume > 1.5× their own MA5 (excluding the day)
      2. Close is above both MA20 and MA60 (NaN-safe)
      3. OBV is within 2% of its 60-day high
      4. Close is at least 10% below its 120-day high (not yet broken out)

    Parameters
    ----------
    stock : StockData
        OHLCV data with symbol, name, dates, closes, volumes.
    indicators : dict
        Pre-computed indicator arrays (numpy, same length as stock.dates).
        Expected keys: 'ma20', 'ma60', 'obv', 'high_120'.

    Returns
    -------
    list[Signal]
        One Signal per qualifying day, sorted chronologically.
    """
    closes = np.asarray(stock.closes, dtype=float)
    volumes = np.asarray(stock.volumes, dtype=float)
    n = len(stock.dates)

    # Unpack indicators with safe defaults
    ma20: np.ndarray | None = indicators.get("ma20")
    ma60: np.ndarray | None = indicators.get("ma60")
    obv: np.ndarray | None = indicators.get("obv")
    high_120: np.ndarray | None = indicators.get("high_120")

    signals: List[Signal] = []

    # Need at least 60 days of data to have enough history
    if n < 61:
        return signals

    for i in range(60, n):
        # ── Step 1: Continuous mild volume ──────────────────────────
        # Count how many of the last 10 days have volume > 1.5× their
        # own 5-day SMA (SMA computed EXCLUDING the day itself).
        count_mild = 0
        vol_ma5_before_i = 0.0

        for j in range(i - 9, i + 1):
            start = max(0, j - 5)
            # Mean of volumes[start:j] — slices are empty when start==j,
            # which only happens when j==0 (should not reach here since i>=60)
            vol_ma5_before_j = float(np.mean(volumes[start:j]))

            if vol_ma5_before_j > 0 and volumes[j] > vol_ma5_before_j * 1.5:
                count_mild += 1

            if j == i:
                vol_ma5_before_i = vol_ma5_before_j

        if count_mild < 6:
            continue

        # ── Step 2: Price above MAs (NaN-safe) ──────────────────────
        if ma20 is not None:
            if np.isnan(ma20[i]) or closes[i] <= ma20[i]:
                continue
        if ma60 is not None:
            if np.isnan(ma60[i]) or closes[i] <= ma60[i]:
                continue

        # ── Step 3: OBV at/near 60-day high ─────────────────────────
        max_obv_60 = 0.0
        if obv is not None:
            obv_window = obv[max(0, i - 59): i + 1]
            max_obv_60 = float(np.max(obv_window))
            if obv[i] < max_obv_60:
                # Allow 2% tolerance below the 60-day high
                if max_obv_60 > 0:
                    if obv[i] < max_obv_60 * 0.98:
                        continue
                else:
                    # Negative OBV: 2% worse = more negative → ×1.02
                    if obv[i] < max_obv_60 * 1.02:
                        continue

        # ── Step 4: Price not yet broken out (10%+ below 120d high) ─
        if high_120 is not None and not np.isnan(high_120[i]):
            if closes[i] >= high_120[i] * 0.90:
                continue

        # ── All conditions met → emit signal ────────────────────────
        # Re-compute vol ratio for the current day i
        signals.append(
            Signal(
                symbol=stock.symbol,
                name=stock.name,
                signal_date=stock.dates[i],
                pattern_type=2,
                entry_price=float(closes[i]),
                volume_ratio=float(volumes[i] / vol_ma5_before_i)
                if vol_ma5_before_i > 0
                else 0.0,
                metadata={
                    "mild_days_count": count_mild,
                    "ma20": round(float(ma20[i]), 2) if ma20 is not None else 0.0,
                    "ma60": round(float(ma60[i]), 2) if ma60 is not None else 0.0,
                    "obv_60d_ratio": (
                        round(float(obv[i] / max_obv_60), 3)
                        if obv is not None and max_obv_60 != 0
                        else 0.0
                    ),
                    "pct_below_120d_high": (
                        round(
                            (1 - float(closes[i]) / float(high_120[i])) * 100,
                            1,
                        )
                        if high_120 is not None
                        and not np.isnan(high_120[i])
                        and high_120[i] != 0
                        else 0.0
                    ),
                },
            )
        )

    return signals
