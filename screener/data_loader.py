"""📦 Data Loader — load batch JSONs and return unified StockData dict."""

from __future__ import annotations

import glob
import json
import logging
import os
import sys
from typing import Dict

from backtest_types import StockData

logger = logging.getLogger(__name__)


def load_stocks(
    data_dir: str,
    start_date: str,
    end_date: str,
) -> Dict[str, StockData]:
    """Load all batch files in *data_dir* and return ``{symbol: StockData}``.

    Stocks with fewer than 120 trading days in the *[start_date, end_date]*
    range are excluded (MA120 needs ~120 data points).

    Parameters
    ----------
    data_dir:
        Directory containing ``batch_*.json`` files.
    start_date, end_date:
        Inclusive date range filter in ``"YYYY-MM-DD"`` format.
    """
    batch_pattern = os.path.join(data_dir, "batch_*.json")
    batch_paths = sorted(glob.glob(batch_pattern))
    result: Dict[str, StockData] = {}

    if not batch_paths:
        logger.warning("No batch_*.json files found in %s", data_dir)
        return result

    seen_symbols: set[str] = set()

    for path in batch_paths:
        if not os.path.isfile(path):
            continue

        batch: dict = {}
        try:
            with open(path) as f:
                content = f.read()
            if not content.strip():
                logger.warning("Empty batch file: %s — skipping", path)
                continue
            batch = json.loads(content)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Invalid JSON in %s (%s) — skipping", path, exc)
            continue
        except OSError as exc:
            logger.warning("Cannot read %s (%s) — skipping", path, exc)
            continue

        if not isinstance(batch, dict):
            logger.warning("Unexpected content type in %s — skipping", path)
            continue

        for symbol, raw in batch.items():
            # Skip duplicates (first file wins, which is batch_001)
            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)

            if not isinstance(raw, dict):
                continue

            raw_dates: list[str] = raw.get("dates", [])
            raw_closes = raw.get("close", [])
            raw_volumes = raw.get("volume", [])
            raw_name = raw.get("name", symbol)

            # Guard: all three arrays must exist
            if not raw_dates or not raw_closes or not raw_volumes:
                continue

            # Find index range within [start_date, end_date]
            start_idx = _first_ge(raw_dates, start_date)
            end_idx = _last_le(raw_dates, end_date)

            if start_idx is None or end_idx is None or start_idx > end_idx:
                continue

            # Slice
            dates = raw_dates[start_idx : end_idx + 1]
            closes_raw = raw_closes[start_idx : end_idx + 1]
            volumes_raw = raw_volumes[start_idx : end_idx + 1]

            # Minimum history check
            if len(dates) < 120:
                continue

            # Type coercion
            closes = [_to_float(v) for v in closes_raw]
            volumes = [_to_int(v) for v in volumes_raw]

            name = raw_name if isinstance(raw_name, str) else symbol

            sd = StockData(
                symbol=symbol,
                name=name,
                dates=dates,
                closes=closes,
                volumes=volumes,
            )
            result[symbol] = sd

    return result


# ── Helper utilities ────────────────────────────────────────────────────────


def _first_ge(sorted_strings: list[str], target: str) -> int | None:
    """Return the index of the first element >= *target* (binary search)."""
    if not sorted_strings:
        return None
    lo, hi = 0, len(sorted_strings) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_strings[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo if sorted_strings[lo] >= target else None


def _last_le(sorted_strings: list[str], target: str) -> int | None:
    """Return the index of the last element <= *target* (binary search)."""
    if not sorted_strings:
        return None
    lo, hi = 0, len(sorted_strings) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2  # upper mid
        if sorted_strings[mid] <= target:
            lo = mid
        else:
            hi = mid - 1
    return lo if sorted_strings[lo] <= target else None


def _to_float(v: object) -> float:
    """Safely convert a value to float (already float, int, or string)."""
    if isinstance(v, float):
        return v
    if isinstance(v, int):
        return float(v)
    return float(v)  # may raise — let it propagate for invalid data


def _to_int(v: object) -> int:
    """Safely convert a value to int (already int, float, or string)."""
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    return int(float(v))  # string → float → int handles "12345.0"


# ── Quick validation (standalone) ───────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

    stocks = load_stocks(
        data_dir="/root/tw-stock-monitor/data",
        start_date="2024-06-01",
        end_date="2026-05-22",
    )

    twse = sum(1 for s in stocks.values() if s.market == "TWSE")
    otc = sum(1 for s in stocks.values() if s.market == "OTC")

    # Gather global date range
    first_dates = [s.dates[0] for s in stocks.values()]
    last_dates = [s.dates[-1] for s in stocks.values()]

    symbols_sorted = sorted(stocks.keys())

    print(f"Total stocks loaded: {len(stocks)}")
    print(f"  TWSE: {twse}")
    print(f"  OTC:  {otc}")
    print(f"  Date range: {min(first_dates)} ~ {max(last_dates)}")
    print(f"  First 5 symbols: {symbols_sorted[:5]}")
