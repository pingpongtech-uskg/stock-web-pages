"""
indicators.py — Technical indicators for Taiwan stock pattern detection.

Computes all indicators needed by Type 1/2/3 pattern detectors.
Uses numpy for vectorised computation. No look-ahead bias:
  - Price MAs:   INCLUSIVE  (close[0..i])
  - Volume MAs:  EXCLUSIVE  (volume[i-N..i-1])
  - OBV:         cumulative sum with direction signs
  - Rolling max: inclusive of current day
"""

from __future__ import annotations

import logging
import sys
from typing import Dict

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from backtest_types import StockData

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════


def _sma(arr: np.ndarray, window: int) -> np.ndarray:
    """Inclusive simple moving average.

    sma[i] = mean(arr[i-window+1 : i+1]).
    First window-1 values are NaN.
    """
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < window:
        return out
    # cumsum approach: cs[k] = sum(arr[0..k-1])
    cs = np.zeros(n + 1, dtype=np.float64)
    cs[1:] = np.cumsum(arr, dtype=np.float64)
    # out[i] = (cs[i+1] - cs[i-window+1]) / window  for i >= window-1
    out[window - 1 : n] = (cs[window:] - cs[: n - window + 1]) / window
    return out


def _vol_sma(volumes: np.ndarray, window: int) -> np.ndarray:
    """EXCLUSIVE volume SMA (look-ahead-safe).

    vol_sma[i] = mean(volumes[max(0, i-window) : i]).
    vol_sma[0] = NaN.
    For 1 <= i < window, use all available prior days (min 1 day).
    """
    n = len(volumes)
    out = np.full(n, np.nan, dtype=np.float64)
    if n <= 1:
        return out

    # Prefix sum: cs[k] = sum(volumes[0..k-1])
    cs = np.zeros(n + 1, dtype=np.float64)
    cs[1:] = np.cumsum(volumes, dtype=np.float64)

    # Early indices (1..min(n,window)-1): divide by exactly i prior days
    early_end = min(n, window)
    for i in range(1, early_end):
        out[i] = cs[i] / i

    # Full window: out[i] = (cs[i] - cs[i-window]) / window  for i >= window
    if n >= window:
        out[window:n] = (cs[window:n] - cs[: n - window]) / window

    return out


def _compute_obv(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """On-Balance Volume.

    obv[0] = volumes[0]
    obv[i] = obv[i-1] + volumes[i]  if close[i] > close[i-1]
    obv[i] = obv[i-1] - volumes[i]  if close[i] < close[i-1]
    obv[i] = obv[i-1]               if close[i] == close[i-1]
    """
    n = len(closes)
    out = np.zeros(n, dtype=np.float64)
    if n == 0:
        return out
    out[0] = float(volumes[0])
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            out[i] = out[i - 1] + volumes[i]
        elif diff < 0:
            out[i] = out[i - 1] - volumes[i]
        else:
            out[i] = out[i - 1]
    return out


def _rolling_max(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling maximum over trailing *window* days (inclusive of current).

    high[i] = max(arr[max(0, i-window+1) : i+1])
    For i < window-1, uses all available data from 0..i.
    """
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)
    if n == 0:
        return out

    # Early indices via running max
    running = arr[0]
    early_end = min(n, window - 1)
    for i in range(early_end):
        if arr[i] > running:
            running = arr[i]
        out[i] = running

    # Full windows via sliding_window_view (vectorised)
    if n >= window:
        sv = sliding_window_view(arr, window_shape=window)
        out[window - 1 : n] = np.max(sv, axis=1)

    return out


def _pct_change(closes: np.ndarray) -> np.ndarray:
    """Percent change from previous close (decimal, not percentage).

    pct[i] = close[i] / close[i-1] - 1.0
    NaN at index 0.
    """
    n = len(closes)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < 2:
        return out
    out[1:] = closes[1:] / closes[:-1] - 1.0
    return out


def _vol_ratio(volumes: np.ndarray, vol_ma5: np.ndarray) -> np.ndarray:
    """Volume ratio vs 5-day volume MA.

    ratio[i] = volumes[i] / vol_ma5[i]
    NaN where vol_ma5 <= 0 or NaN.
    """
    out = np.full(len(volumes), np.nan, dtype=np.float64)
    mask = ~np.isnan(vol_ma5) & (vol_ma5 > 0)
    out[mask] = volumes[mask] / vol_ma5[mask]
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  Main API
# ══════════════════════════════════════════════════════════════════════════════


def compute_indicators(stock: StockData) -> Dict[str, np.ndarray]:
    """Compute all technical indicators for a single stock.

    Parameters
    ----------
    stock : StockData
        Must have .dates, .closes, .volumes of equal length.

    Returns
    -------
    dict
        Keys as numpy float64 arrays, each of length ``len(stock.dates)``:
        ``ma5``, ``ma10``, ``ma20``, ``ma60``, ``vol_ma5``, ``vol_ma60``,
        ``obv``, ``high_60``, ``high_120``, ``close_pct_change``,
        ``vol_ratio_vs_5d``.
    """
    closes = np.asarray(stock.closes, dtype=np.float64)
    volumes = np.asarray(stock.volumes, dtype=np.float64)

    return {
        "ma5":               _sma(closes, 5),
        "ma10":              _sma(closes, 10),
        "ma20":              _sma(closes, 20),
        "ma60":              _sma(closes, 60),
        "vol_ma5":           _vol_sma(volumes, 5),
        "vol_ma60":          _vol_sma(volumes, 60),
        "obv":               _compute_obv(closes, volumes),
        "high_60":           _rolling_max(closes, 60),
        "high_120":          _rolling_max(closes, 120),
        "close_pct_change":  _pct_change(closes),
        "vol_ratio_vs_5d":   _vol_ratio(volumes, _vol_sma(volumes, 5)),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Quick validation (__main__)
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(stream=sys.stderr, level=_logging.WARNING)

    from data_loader import load_stocks

    stocks = load_stocks(
        data_dir="/root/tw-stock-monitor/data",
        start_date="2024-06-01",
        end_date="2026-05-22",
    )

    target = "2330.TW"
    if target not in stocks:
        target = next(iter(stocks.keys()), None)

    if target is None:
        print("No stocks loaded — data directory empty?")
        sys.exit(1)

    stock = stocks[target]
    ind = compute_indicators(stock)
    n = len(stock.dates)

    print(f"Stock: {stock.symbol} ({stock.name})")
    print(f"  Date range: {stock.dates[0]} ~ {stock.dates[-1]} ({n} days)")
    print()

    # First 3 MA20 values
    ma20 = ind["ma20"]
    print("  MA20 — first 3 non-NaN values:")
    count = 0
    for i in range(n):
        if not np.isnan(ma20[i]):
            print(f"    [{stock.dates[i]}] {ma20[i]:.2f}")
            count += 1
            if count >= 3:
                break
    print()

    # Last 3 MA20 values
    print("  MA20 — last 3 non-NaN values:")
    count = 0
    for i in range(n - 1, -1, -1):
        if not np.isnan(ma20[i]):
            print(f"    [{stock.dates[i]}] {ma20[i]:.2f}")
            count += 1
            if count >= 3:
                break
    print()

    # OBV range
    obv = ind["obv"]
    print(f"  OBV range: {obv.min():,.0f} ~ {obv.max():,.0f}")
    print()

    # vol_ma5 sample
    vol_ma5 = ind["vol_ma5"]
    print("  vol_ma5 sample (days 60-64):")
    for i in range(60, min(65, n)):
        print(f"    [{stock.dates[i]}] {vol_ma5[i]:,.0f}")
    print()

    # Sanity checks
    print("  Sanity checks:")
    for key in ["ma5", "ma10", "ma20", "ma60", "vol_ma5", "vol_ma60", "high_120"]:
        arr = ind[key]
        valid = np.sum(~np.isnan(arr))
        print(f"    {key:>12}: {valid:>4} / {n} valid")
