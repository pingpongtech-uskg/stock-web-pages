#!/usr/bin/env python3
"""
10-year multi-scenario backtest runner for Taiwan stock abnormal volume strategy.

Runs Layer 1 (existing pattern detectors) over 2016/06 ~ 2026/05, then
applies Layer 2/3 scoring and runs 8 filter scenarios, producing raw
results for the report generator.

Usage:
    python ten_year_backtest.py           # Run full backtest
    from ten_year_backtest import run     # Import and run programmatically
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from dataclasses import asdict
from typing import Callable, Dict, List, Optional

import numpy as np

from backtest_types import Signal, StockData

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "ten_year")
START_DATE = "2016-06-01"
END_DATE = "2026-05-22"

# ──────────────────────────────────────────────
#  8 Scenario Definitions
# ──────────────────────────────────────────────

SCENARIOS: list[dict] = [
    {
        "num": 1,
        "name": "Pure L1 (baseline)",
        "filter": "none",
        "filter_desc": "No filter, use all signals",
    },
    {
        "num": 2,
        "name": "L1 + price ≥100",
        "filter": "price_ge_100",
        "filter_desc": "Close ≥ 100",
    },
    {
        "num": 3,
        "name": "L1 + price ≥200",
        "filter": "price_ge_200",
        "filter_desc": "Close ≥ 200",
    },
    {
        "num": 4,
        "name": "L1 + price ≥500",
        "filter": "price_ge_500",
        "filter_desc": "Close ≥ 500",
    },
    {
        "num": 5,
        "name": "L1 + L2≥60",
        "filter": "l2_ge_60",
        "filter_desc": "Layer 2 fundamental score ≥ 60",
    },
    {
        "num": 6,
        "name": "L1 + L3≥30",
        "filter": "l3_ge_30",
        "filter_desc": "Layer 3 chip score ≥ 30",
    },
    {
        "num": 7,
        "name": "Full three-layer",
        "filter": "full_three_layer",
        "filter_desc": "Full three-layer, total_score ≥ 40",
    },
    {
        "num": 8,
        "name": "Full three-layer + price ≥200",
        "filter": "full_three_layer_price_ge_200",
        "filter_desc": "Full three-layer + price ≥ 200 (strictest)",
    },
]

# ──────────────────────────────────────────────
#  Layer 1 Score Calculation
# ──────────────────────────────────────────────


def compute_l1_score(volume_ratio: float, pattern_type: int) -> float:
    """Compute Layer 1 technical score from volume_ratio and pattern_type.

    Base score = min(volume_ratio * 20, 100)  # cap at 100
    Pattern multiplier: Type 1 ×1.0, Type 2 ×0.8, Type 3 ×1.2
    l1_score = min(base * multiplier, 100)
    """
    base = min(volume_ratio * 20.0, 100.0)
    multiplier = {1: 1.0, 2: 0.8, 3: 1.2}.get(pattern_type, 1.0)
    return min(base * multiplier, 100.0)


# ──────────────────────────────────────────────
#  Cost Deduction
# ──────────────────────────────────────────────

COST_PER_TRADE = 0.6   # 0.3% buy + 0.3% sell
SLIPPAGE_PER_TRADE = 0.5  # 0.5% slippage
TOTAL_ROUND_TRIP_COST = COST_PER_TRADE + SLIPPAGE_PER_TRADE  # 1.1%


def apply_cost(return_pct: float) -> float:
    """Deduct round-trip cost (1.1%) from a return percentage."""
    return return_pct - TOTAL_ROUND_TRIP_COST


# ──────────────────────────────────────────────
#  Layer 2/3 Scorers — Graceful Import
# ──────────────────────────────────────────────


def _try_import_scorer(module_name: str, func_name: str) -> Optional[Callable]:
    """Try to import a scorer function. Returns None if module not found."""
    try:
        mod = __import__(module_name, fromlist=[func_name])
        return getattr(mod, func_name, None)
    except ImportError:
        logger.warning("Module %s not available — scoring disabled", module_name)
        return None
    except Exception as exc:
        logger.warning("Failed to load %s.%s: %s", module_name, func_name, exc)
        return None


def _load_scorers() -> tuple[Optional[Callable], Optional[Callable]]:
    """Load fundamental and chip scorer functions.

    Returns (score_fundamentals_fn, score_chip_fn) — either may be None
    if the corresponding module isn't available.
    """
    score_fundamentals = _try_import_scorer("fundamental_scorer", "score_fundamentals")
    score_chip = _try_import_scorer("chip_scorer", "score_chip")
    return score_fundamentals, score_chip


# ──────────────────────────────────────────────
#  Signal Scoring
# ──────────────────────────────────────────────


def score_signal(
    sig: Signal,
    score_fundamentals_fn: Optional[Callable] = None,
    score_chip_fn: Optional[Callable] = None,
) -> Signal:
    """Compute all layer scores for a single signal.

    1. Compute l1_score from volume_ratio and pattern_type
    2. Call fundamental scorer → l2_score (default 0 on failure)
    3. Call chip scorer → l3_score (default 0 on failure)
    4. Compute total_score = l1*0.3 + l2*0.5 + l3*0.2
    """
    # Layer 1: always computable
    sig.l1_score = compute_l1_score(sig.volume_ratio, sig.pattern_type)

    # Layer 2: fundamental scoring
    sig.l2_score = 0.0
    if score_fundamentals_fn is not None:
        try:
            result = score_fundamentals_fn(sig.symbol, sig.signal_date)
            if isinstance(result, dict):
                sig.l2_score = float(result.get("total", 0))
        except Exception as exc:
            logger.warning(
                "score_fundamentals failed for %s on %s: %s",
                sig.symbol, sig.signal_date, exc,
            )

    # Layer 3: chip scoring
    sig.l3_score = 0.0
    if score_chip_fn is not None:
        try:
            result = score_chip_fn(sig.symbol, sig.signal_date)
            if isinstance(result, dict):
                sig.l3_score = float(result.get("total", 0))
        except Exception as exc:
            logger.warning(
                "score_chip failed for %s on %s: %s",
                sig.symbol, sig.signal_date, exc,
            )

    # Total score
    sig.total_score = sig.compute_total_score()

    return sig


# ──────────────────────────────────────────────
#  Process All Stocks
# ──────────────────────────────────────────────


def process_stock(
    stock: StockData,
    score_fundamentals_fn: Optional[Callable] = None,
    score_chip_fn: Optional[Callable] = None,
) -> list[Signal]:
    """Detect all signals for one stock and compute layer scores."""
    from indicators import compute_indicators
    from pattern_type1 import detect_type1
    from pattern_type2 import detect_type2
    from pattern_type3 import detect_type3

    # Compute indicators
    indicators = compute_indicators(stock)

    # Detect patterns
    signals: list[Signal] = []
    signals.extend(detect_type1(stock, indicators))
    signals.extend(detect_type2(stock, indicators))
    signals.extend(detect_type3(stock, indicators, ohlc_cache_dir=None))

    # Score each signal
    for sig in signals:
        score_signal(sig, score_fundamentals_fn, score_chip_fn)

    return signals


def process_all_stocks(
    stocks: Dict[str, StockData],
    score_fundamentals_fn: Optional[Callable] = None,
    score_chip_fn: Optional[Callable] = None,
    progress_callback: Optional[Callable] = None,
) -> list[Signal]:
    """Process all stocks, detect + score signals.

    Returns one flat list of all scored signals.
    """
    all_signals: list[Signal] = []
    total = len(stocks)
    processed = 0

    for symbol, stock in stocks.items():
        try:
            signals = process_stock(stock, score_fundamentals_fn, score_chip_fn)
            all_signals.extend(signals)
        except Exception as exc:
            logger.warning("Failed to process %s: %s", symbol, exc)

        processed += 1
        if progress_callback is not None:
            progress_callback(processed, total)

    # Sort by date then symbol
    all_signals.sort(key=lambda s: (s.signal_date, s.symbol))
    return all_signals


# ──────────────────────────────────────────────
#  Scenario Filter
# ──────────────────────────────────────────────


def filter_signals(signals: list[Signal], scenario_num: int) -> list[Signal]:
    """Filter signals according to a scenario's rule.

    Parameters
    ----------
    signals : list[Signal]
        All scored signals.
    scenario_num : int
        1-8 identifying which scenario filter to apply.

    Returns
    -------
    list[Signal]
        Signals that pass the filter.
    """
    if scenario_num == 1:
        # Scenario 1: No filter, use all signals
        return list(signals)

    elif scenario_num == 2:
        # L1 + price ≥ 100
        return [s for s in signals if s.entry_price >= 100]

    elif scenario_num == 3:
        # L1 + price ≥ 200
        return [s for s in signals if s.entry_price >= 200]

    elif scenario_num == 4:
        # L1 + price ≥ 500
        return [s for s in signals if s.entry_price >= 500]

    elif scenario_num == 5:
        # L1 + L2 ≥ 60
        return [
            s for s in signals
            if s.l2_score is not None and s.l2_score >= 60
        ]

    elif scenario_num == 6:
        # L1 + L3 ≥ 30
        return [
            s for s in signals
            if s.l3_score is not None and s.l3_score >= 30
        ]

    elif scenario_num == 7:
        # Full three-layer, total_score ≥ 40
        return [
            s for s in signals
            if s.l1_score is not None
            and s.l2_score is not None
            and s.l3_score is not None
            and s.total_score is not None
            and s.total_score >= 40
        ]

    elif scenario_num == 8:
        # Full three-layer + price ≥ 200
        return [
            s for s in signals
            if s.entry_price >= 200
            and s.l1_score is not None
            and s.l2_score is not None
            and s.l3_score is not None
            and s.total_score is not None
            and s.total_score >= 40
        ]

    else:
        raise ValueError(f"Unknown scenario number: {scenario_num}")


# ──────────────────────────────────────────────
#  Performance Tracking
# ──────────────────────────────────────────────


def run_scenario(
    scenario: dict,
    all_signals: list[Signal],
    stocks: Dict[str, StockData],
) -> dict:
    """Run a single scenario: filter, track, compute stats + yearly breakdown.

    Returns a scenario result dict ready for JSON serialization.
    """
    from performance import PerformanceTracker

    scenario_num = scenario["num"]

    # Filter signals
    filtered = filter_signals(all_signals, scenario_num)

    # Run performance tracking
    tracker = PerformanceTracker()
    for sig in filtered:
        tracker.record_signal(sig)
    tracker.compute_forward_returns(stocks)
    stats_by_type = tracker.compute_stats()

    # Get combined stats (pattern_type=0 = ALL)
    all_stats = stats_by_type.get(0)

    # Deduct costs from returns
    if all_stats is not None:
        _deduct_costs_from_stats(all_stats)

    # Compute yearly breakdown
    yearly = compute_yearly_breakdown(
        filtered,
        tracker.returns if hasattr(tracker, "returns") else {},
    )

    # Build result dict
    result = {
        "scenario": scenario_num,
        "name": scenario["name"],
        "filter": scenario["filter"],
        "total_signals": len(filtered),
        "stats": _stats_to_dict(all_stats),
        "yearly": yearly,
    }

    return result


def run_all_scenarios(
    all_signals: list[Signal],
    stocks: Dict[str, StockData],
) -> list[dict]:
    """Run all 8 scenarios and return results as a list of dicts."""
    results: list[dict] = []
    for scenario in SCENARIOS:
        result = run_scenario(scenario, all_signals, stocks)
        results.append(result)
        logger.info(
            "  Scenario %d (%s): %d signals",
            scenario["num"], scenario["name"], result["total_signals"],
        )
    return results


def _deduct_costs_from_stats(stats) -> None:
    """Subtract round-trip cost from avg_return fields.
    Only applies when there are signals."""
    if stats is None or stats.total_signals == 0:
        return
    for field in ["avg_return_5d", "avg_return_10d", "avg_return_20d", "avg_return_60d"]:
        if hasattr(stats, field):
            setattr(stats, field, apply_cost(getattr(stats, field)))


def _stats_to_dict(stats) -> dict:
    """Convert a PerformanceStats object to a plain dict for JSON."""

    if stats is None:
        return {
            "win_rate_5d": 0.0,
            "win_rate_10d": 0.0,
            "win_rate_20d": 0.0,
            "win_rate_60d": 0.0,
            "avg_return_5d": 0.0,
            "avg_return_10d": 0.0,
            "avg_return_20d": 0.0,
            "avg_return_60d": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
        }
    return {
        "win_rate_5d": round(stats.win_rate_5d, 4),
        "win_rate_10d": round(stats.win_rate_10d, 4),
        "win_rate_20d": round(stats.win_rate_20d, 4),
        "win_rate_60d": round(stats.win_rate_60d, 4),
        "avg_return_5d": round(stats.avg_return_5d, 4),
        "avg_return_10d": round(stats.avg_return_10d, 4),
        "avg_return_20d": round(stats.avg_return_20d, 4),
        "avg_return_60d": round(stats.avg_return_60d, 4),
        "sharpe_ratio": round(stats.sharpe_ratio, 4),
        "max_drawdown": round(stats.max_drawdown, 4),
    }


# ──────────────────────────────────────────────
#  Yearly Breakdown
# ──────────────────────────────────────────────


def compute_yearly_breakdown(
    signals: list[Signal],
    returns: Optional[Dict[int, list[float]]] = None,
) -> dict:
    """Group signals by year and compute per-year stats.

    Parameters
    ----------
    signals : list[Signal]
        Filtered signals for a scenario.
    returns : dict, optional
        Map of {holding_period: [return_pcts]} from PerformanceTracker.

    Returns
    -------
    dict
        {year_str: {"signals": N, "win_rate_20d": float, "avg_return_20d": float}}
    """
    if not signals:
        return {}

    # Group signals by year
    year_to_indices: dict[str, list[int]] = {}
    for i, sig in enumerate(signals):
        year = sig.signal_date[:4]
        if year not in year_to_indices:
            year_to_indices[year] = []
        year_to_indices[year].append(i)

    result: dict[str, dict] = {}
    for year, indices in sorted(year_to_indices.items()):
        entry: dict = {
            "signals": len(indices),
        }

        # Calculate win_rate and avg_return from 20d returns
        if returns and 20 in returns:
            r20 = returns[20]
            year_returns = [r20[i] for i in indices if i < len(r20)]
            if year_returns:
                arr = np.array(year_returns, dtype=np.float64)
                entry["win_rate_20d"] = round(float(np.mean(arr > 0)), 4)
                entry["avg_return_20d"] = round(float(np.mean(arr)), 4)
            else:
                entry["win_rate_20d"] = 0.0
                entry["avg_return_20d"] = 0.0
        else:
            entry["win_rate_20d"] = 0.0
            entry["avg_return_20d"] = 0.0

        result[year] = entry

    return result


# ──────────────────────────────────────────────
#  JSON Output
# ──────────────────────────────────────────────


def _signal_to_dict(sig: Signal) -> dict:
    """Convert a Signal to a JSON-serializable dict."""
    return {
        "symbol": sig.symbol,
        "name": sig.name,
        "signal_date": sig.signal_date,
        "pattern_type": sig.pattern_type,
        "entry_price": round(sig.entry_price, 2),
        "volume_ratio": round(sig.volume_ratio, 4),
        "l1_score": sig.l1_score,
        "l2_score": sig.l2_score,
        "l3_score": sig.l3_score,
        "total_score": sig.total_score,
        "metadata": {k: round(v, 4) if isinstance(v, float) else v
                      for k, v in sig.metadata.items()},
    }


def save_signal_json(signals: list[Signal], path: str) -> None:
    """Serialize all signals to JSON."""
    serialized = [_signal_to_dict(s) for s in signals]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serialized, f, ensure_ascii=False, indent=2)
    logger.info("Saved %d signals to %s", len(signals), path)


def save_scenario_result(result: dict, path: str) -> None:
    """Save a single scenario result to JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("Saved scenario %d result to %s", result["scenario"], path)


def save_yearly_breakdown(yearly: dict, path: str) -> None:
    """Save yearly breakdown data to JSON."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(yearly, f, ensure_ascii=False, indent=2)
    logger.info("Saved yearly breakdown to %s", path)


# ──────────────────────────────────────────────
#  Main Orchestrator
# ──────────────────────────────────────────────


def run(
    data_dir: str = DATA_DIR,
    start_date: str = START_DATE,
    end_date: str = END_DATE,
    output_dir: str = OUTPUT_DIR,
    progress_callback: Optional[Callable] = None,
) -> dict:
    """Run the full 10-year backtest.

    Parameters
    ----------
    data_dir : str
        Directory containing batch_*.json files.
    start_date, end_date : str
        Date range (inclusive) in YYYY-MM-DD format.
    output_dir : str
        Output directory for JSON results.
    progress_callback : callable, optional
        Called as fn(processed, total) after each stock.

    Returns
    -------
    dict
        Summary of the backtest results.
    """
    start_time = time.time()
    logger.info("Starting 10-year backtest: %s ~ %s", start_date, end_date)

    # Load scorers (graceful if not available)
    score_fundamentals_fn, score_chip_fn = _load_scorers()

    if score_fundamentals_fn is not None:
        logger.info("Layer 2 (fundamental) scorer loaded")
    else:
        logger.info("Layer 2 (fundamental) scorer NOT available — using score=0")

    if score_chip_fn is not None:
        logger.info("Layer 3 (chip) scorer loaded")
    else:
        logger.info("Layer 3 (chip) scorer NOT available — using score=0")

    # Step 1: Load stocks
    logger.info("Loading stocks from %s ...", data_dir)
    from data_loader import load_stocks
    stocks = load_stocks(data_dir, start_date, end_date)
    logger.info("Loaded %d stocks", len(stocks))

    if len(stocks) == 0:
        logger.warning("No stocks loaded — aborting backtest")
        return {"stocks_loaded": 0, "total_signals": 0, "scenarios_ran": 0}

    # Step 2: Process all stocks
    logger.info("Processing %d stocks...", len(stocks))

    def _default_progress(processed: int, total: int) -> None:
        if processed % 100 == 0 or processed == total:
            pct = processed / total * 100
            logger.info("  Progress: %d / %d (%.1f%%)", processed, total, pct)

    cb = progress_callback or _default_progress

    all_signals = process_all_stocks(stocks, score_fundamentals_fn, score_chip_fn, cb)
    logger.info("Total signals detected: %d", len(all_signals))

    if len(all_signals) == 0:
        logger.warning("No signals detected — aborting backtest")
        return {"stocks_loaded": len(stocks), "total_signals": 0, "scenarios_ran": 0}

    # Step 3: Run all 8 scenarios
    logger.info("Running %d scenarios...", len(SCENARIOS))
    scenario_results = run_all_scenarios(all_signals, stocks)

    # Step 4: Build yearly breakdown (all-scenario combined)
    all_yearly: dict = {}
    for result in scenario_results:
        for year, data in result.get("yearly", {}).items():
            if year not in all_yearly:
                all_yearly[year] = {}
            all_yearly[year][f"scenario_{result['scenario']}"] = data

    # Output
    os.makedirs(output_dir, exist_ok=True)

    # Save all signals
    all_signals_path = os.path.join(output_dir, "all_signals.json")
    save_signal_json(all_signals, all_signals_path)

    # Save per-scenario results
    for result in scenario_results:
        path = os.path.join(output_dir, f"scenario_{result['scenario']}.json")
        save_scenario_result(result, path)

    # Save yearly breakdown
    yearly_path = os.path.join(output_dir, "yearly_breakdown.json")
    save_yearly_breakdown(all_yearly, yearly_path)

    elapsed = time.time() - start_time
    logger.info("Backtest complete in %.1f seconds", elapsed)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"  10-Year Backtest Complete: {start_date} ~ {end_date}")
    print(f"{'=' * 60}")
    print(f"  Stocks loaded:  {len(stocks)}")
    print(f"  Total signals:  {len(all_signals)}")
    print(f"  Runtime:        {elapsed:.1f}s")
    print()
    print(f"  {'#':>2}  {'Scenario':<35} {'Signals':>8}")
    print(f"  {'-' * 47}")
    for result in scenario_results:
        print(f"  {result['scenario']:>2}  {result['name']:<35} {result['total_signals']:>8}")
    print(f"{'=' * 60}")

    return {
        "stocks_loaded": len(stocks),
        "total_signals": len(all_signals),
        "scenarios_ran": len(scenario_results),
        "elapsed_seconds": elapsed,
    }


# ──────────────────────────────────────────────
#  CLI Entry Point
# ──────────────────────────────────────────────


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Suppress noisy third-party loggers
    for name in ["FinMind", "urllib3", "requests"]:
        logging.getLogger(name).setLevel(logging.WARNING)

    run()
