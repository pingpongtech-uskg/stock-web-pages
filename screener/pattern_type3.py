#!/usr/bin/env python3
"""
pattern_type3.py — 突破爆量 (Breakout Volume Explosion / Momentum Chase)

Detects Type 3 pattern:
  Step 1: Close breaks 120-day (6-month) consolidation high
  Step 2: Volume ≥ 2.5× MA5 (explosion on breakout day)
  Step 3: Close in top 30% of day's range (strong close)

OHLC data sources (priority):
  1. Local cache at ohlc_cache_dir/{symbol}.json
  2. FinMind API (TaiwanStockPrice) with rate limiting
  3. Approximation: close[i] > close[i−1] and pct_change > 1%
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Optional

from backtest_types import StockData, Signal


# ── OHLC helpers ──


def _ohlc_from_cache(symbol: str, cache_dir: str) -> Optional[dict]:
    """Load OHLC data from local cache file. Returns dict[date → OHLC] or None."""
    path = os.path.join(cache_dir, f"{symbol}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return None
    except (json.JSONDecodeError, IOError):
        return None


def _fetch_ohlc_finmind(symbol: str) -> Optional[dict]:
    """
    Fetch OHLC data from FinMind for a symbol.
    Returns dict[date → {"open": ..., "high": ..., "low": ..., "close": ...}] or None.
    """
    try:
        from FinMind.data import DataLoader
        from _data_fetcher import _fm_wait, _fm_register
    except ImportError:
        return None

    # Strip .TW / .TWO suffix for FinMind
    stock_id = symbol.replace(".TW", "").replace(".TWO", "")

    try:
        api = DataLoader()
        # Token is optional — FinMind works without login for basic data
        wait = _fm_wait()
        if wait > 0:
            time.sleep(wait)
        _fm_register()
        df = api.taiwan_stock_price(stock_id=stock_id, start_date="2000-01-01")
        if df is None or len(df) == 0:
            return None
    except Exception:
        return None

    # Convert to dict[date → OHLC]
    result = {}
    for _, row in df.iterrows():
        d = str(row["date"])[:10]
        try:
            result[d] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        except (ValueError, KeyError):
            continue
    return result if result else None


def _save_ohlc_cache(symbol: str, ohlc_data: dict, cache_dir: str) -> None:
    """Save fetched OHLC data to local cache."""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{symbol}.json")
    payload = {"symbol": symbol, "data": ohlc_data}
    try:
        with open(path, "w") as f:
            json.dump(payload, f, ensure_ascii=False)
    except IOError:
        pass  # cache write is best-effort


def _get_close_position(ohlc: dict, date: str, close_val: float) -> Optional[float]:
    """
    Calculate close's position within the day's range.
    Returns 0–1 or None if data is missing.
    """
    day = ohlc.get(date)
    if day is None:
        return None
    low = day.get("low")
    high = day.get("high")
    if low is None or high is None or high == low:
        return None
    return (close_val - low) / (high - low)


# ── Core detection ──


def detect_type3(
    stock: StockData,
    indicators: dict,        # no indicators needed for Type 3; kept for API compat
    ohlc_cache_dir: str = None,
) -> list[Signal]:
    """
    Detect Type 3 signals on a single stock.

    Args:
        stock: StockData with .symbol, .name, .dates, .closes, .volumes
        indicators: Unused (kept for API consistency with other pattern modules)
        ohlc_cache_dir: Path to OHLC cache directory.
            If None, approximation mode is used when no cache/FinMind available.

    Returns:
        List of Signal objects for each detected breakout.
    """
    signals: list[Signal] = []
    n = len(stock.closes)
    if n < 121:
        return signals  # need at least 121 days for 120d lookback + 1 day of signal

    closes = stock.closes
    volumes = stock.volumes
    dates = stock.dates

    # Lazy OHLC storage: symbol → dict[date → OHLC]
    _ohlc_data: Optional[dict] = None
    _ohlc_source: Optional[str] = None

    def _ensure_ohlc() -> tuple[Optional[dict], Optional[str]]:
        """Fetch OHLC data once per stock (lazy). Returns (ohlc_by_date, source)."""
        nonlocal _ohlc_data, _ohlc_source
        if _ohlc_data is not None:
            return _ohlc_data, _ohlc_source

        # Priority 1: Local cache
        if ohlc_cache_dir and os.path.isdir(ohlc_cache_dir):
            cached = _ohlc_from_cache(stock.symbol, ohlc_cache_dir)
            if cached is not None:
                _ohlc_data = cached
                _ohlc_source = "cache"
                return _ohlc_data, _ohlc_source

        # Priority 2: FinMind API
        fm_data = _fetch_ohlc_finmind(stock.symbol)
        if fm_data is not None:
            _ohlc_data = fm_data
            _ohlc_source = "finmind"
            # Cache the result for future lookups
            if ohlc_cache_dir:
                _save_ohlc_cache(stock.symbol, fm_data, ohlc_cache_dir)
            return _ohlc_data, _ohlc_source

        # Priority 3: Approximation mode (no OHLC data)
        _ohlc_data = None
        _ohlc_source = "approximated"
        return None, "approximated"

    def _check_approximation(i: int) -> bool:
        """
        Approximate check for close in top 30% of range.
        Returns True if close[i] > close[i-1] and pct_change > 1%.
        """
        if i < 1:
            return False
        prev_close = closes[i - 1]
        if prev_close == 0:
            return False
        pct = (closes[i] / prev_close - 1) * 100
        return pct > 1.0

    for i in range(120, n):
        # ── Step 1: Breakout from 120-day consolidation ──
        # previous_120d_high = max(closes[i-120 : i])  — EXCLUDING day i
        prev_120d_high = max(closes[i - 120 : i])

        # Check for NaN
        if math.isnan(closes[i]) or math.isnan(prev_120d_high):
            continue
        if prev_120d_high <= 0:
            continue

        if closes[i] < prev_120d_high:
            continue  # no breakout

        # ── Step 2: Volume explosion ──
        vol_ma5_before = sum(volumes[i - 5 : i]) / 5.0
        if vol_ma5_before <= 0:
            continue
        if volumes[i] < vol_ma5_before * 2.5:
            continue

        # ── Step 3: Close in top 30% of day's range ──
        ohlc, ohlc_source = _ensure_ohlc()

        close_position: Optional[float] = None
        passed_step3 = False

        if ohlc is not None and ohlc_source in ("cache", "finmind"):
            close_position = _get_close_position(ohlc, dates[i], closes[i])
            if close_position is not None and close_position >= 0.70:
                passed_step3 = True
        else:
            # Approximation mode
            ohlc_source = "approximated"
            if _check_approximation(i):
                passed_step3 = True

        if not passed_step3:
            continue

        # ── Create signal ──
        volume_ratio = volumes[i] / vol_ma5_before
        breakout_pct = (closes[i] / prev_120d_high - 1) * 100

        signals.append(Signal(
            symbol=stock.symbol,
            name=stock.name,
            signal_date=dates[i],
            pattern_type=3,
            entry_price=closes[i],
            volume_ratio=round(volume_ratio, 2),
            metadata={
                "prev_120d_high": round(prev_120d_high, 2),
                "breakout_pct": round(breakout_pct, 2),
                "close_position": round(close_position, 2) if close_position is not None else None,
                "ohlc_source": ohlc_source,
            },
        ))

    return signals


# ── Quick validation (__main__) ──


if __name__ == "__main__":
    import json
    import sys

    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    # Find first stock with enough data
    stock_data = None
    symbol_key = None

    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".json") or not fname.startswith("batch_"):
            continue
        fpath = os.path.join(DATA_DIR, fname)
        try:
            with open(fpath) as f:
                batch = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        for sym, sd in batch.items():
            if sd.get("days", 0) >= 200:
                stock_data = sd
                symbol_key = sym
                break
        if stock_data:
            break

    if stock_data is None:
        print("❌ No stock with ≥200 days of data found in data/")
        sys.exit(1)

    stock = StockData(
        symbol=symbol_key,
        name=stock_data.get("name", ""),
        dates=stock_data["dates"],
        closes=stock_data["close"],
        volumes=stock_data["volume"],
    )

    print(f"📊 Testing detection on {symbol_key} ({stock.name}) — {len(stock.dates)} days")
    print(f"   Period: {stock.dates[0]} → {stock.dates[-1]}")
    print(f"   Mode: approximation (no FinMind)")

    signals = detect_type3(stock, {}, ohlc_cache_dir=None)
    print(f"\n✅ Type 3 signals found: {len(signals)}")
    for sig in signals:
        print(f"   📅 {sig.signal_date} | entry={sig.entry_price} "
              f"| vol_ratio={sig.volume_ratio}x "
              f"| prev_120d_high={sig.metadata['prev_120d_high']} "
              f"| breakout={sig.metadata['breakout_pct']}% "
              f"| ohlc={sig.metadata['ohlc_source']}")

    if not signals:
        print("   (no breakouts in this period — this is expected for backtest)")
