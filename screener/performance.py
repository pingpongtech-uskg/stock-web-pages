#!/usr/bin/env python3
"""
📊 Performance Tracker — trade tracking and statistics

Tracks all signals from pattern-based strategies, computes forward
returns for multiple holding periods, and generates comprehensive
performance statistics (win rate, Sharpe, drawdown, etc.).

Usage:
    tracker = PerformanceTracker()
    for sig in signals:
        tracker.record_signal(sig)
    tracker.compute_forward_returns(all_stocks)
    stats = tracker.compute_stats()
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from backtest_types import Signal, StockData, PerformanceStats

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────

HOLDING_PERIODS = (5, 10, 20, 60)
PATTERN_TYPES = (0, 1, 2, 3)  # 0 = ALL combined


# ──────────────────────────────────────────────
#  PerformanceTracker
# ──────────────────────────────────────────────


class PerformanceTracker:
    """Record signals, compute forward returns, generate statistics."""

    def __init__(self) -> None:
        self.signals: list[Signal] = []
        # returns[period][i] = forward return % for the i-th signal at that period
        self.returns: dict[int, list[float]] = {p: [] for p in HOLDING_PERIODS}
        # Track which pattern_type each return entry belongs to
        self._return_types: dict[int, list[int]] = {p: [] for p in HOLDING_PERIODS}

    # ── Recording ──

    def record_signal(self, signal: Signal) -> None:
        """Store a signal."""
        self.signals.append(signal)

    # ── Forward returns ──

    def compute_forward_returns(self, all_stocks: dict[str, StockData]) -> None:
        """
        For each recorded signal:
          - Locate the stock and the signal-date index in its trading-day sequence.
          - Look forward 5, 10, 20, 60 trading days.
          - Return = (close[T+N] / close[T] - 1) * 100
          - If T+N exceeds the data, use the last available close.
        """
        # Reset
        for p in HOLDING_PERIODS:
            self.returns[p].clear()
            self._return_types[p].clear()

        for sig in self.signals:
            stock = all_stocks.get(sig.symbol)
            if stock is None:
                logger.warning("Stock %s not found in all_stocks — skip signal", sig.symbol)
                continue

            t = stock.date_index(sig.signal_date)
            if t < 0:
                logger.warning(
                    "Signal date %s not found in %s dates — skip",
                    sig.signal_date, sig.symbol,
                )
                continue

            close_t = stock.closes[t]
            if math.isnan(close_t) or close_t <= 0:
                continue

            for p in HOLDING_PERIODS:
                idx = min(t + p, len(stock.closes) - 1)
                close_tn = stock.closes[idx]
                if math.isnan(close_tn):
                    continue
                ret = (close_tn / close_t - 1.0) * 100.0
                if math.isnan(ret) or math.isinf(ret):
                    continue
                self.returns[p].append(ret)
                self._return_types[p].append(sig.pattern_type)

    # ── Statistics ──

    def compute_stats(self) -> dict[int, PerformanceStats]:
        """
        Returns dict keyed by pattern_type (0, 1, 2, 3) → PerformanceStats.
        Key 0 = ALL patterns combined.
        """
        result: dict[int, PerformanceStats] = {}

        for pt in PATTERN_TYPES:
            # Count signals
            total = sum(
                1 for s in self.signals
                if pt == 0 or s.pattern_type == pt
            )

            # Gather per-period returns for this pattern type
            period_returns: dict[int, list[float]] = {}
            for p in HOLDING_PERIODS:
                period_returns[p] = [
                    self.returns[p][i]
                    for i in range(len(self.returns[p]))
                    if pt == 0 or self._return_types[p][i] == pt
                ]

            # Build PerformanceStats
            ps = PerformanceStats(
                pattern_type=pt,
                total_signals=total,
                win_rate_5d=self._win_rate(period_returns[5]),
                win_rate_10d=self._win_rate(period_returns[10]),
                win_rate_20d=self._win_rate(period_returns[20]),
                win_rate_60d=self._win_rate(period_returns[60]),
                avg_return_5d=self._mean(period_returns[5]),
                avg_return_10d=self._mean(period_returns[10]),
                avg_return_20d=self._mean(period_returns[20]),
                avg_return_60d=self._mean(period_returns[60]),
                max_drawdown=self._max_drawdown(period_returns[20]),
                sharpe_ratio=self._sharpe(period_returns),
                avg_holding_days=self._avg_holding_days(period_returns[20]),
                return_std_20d=self._std(period_returns[20]),
                best_return_20d=self._best(period_returns[20]),
                worst_return_20d=self._worst(period_returns[20]),
            )
            result[pt] = ps

        return result

    # ── Static helpers for metric computation ──

    @staticmethod
    def _clean(returns: list[float]) -> np.ndarray:
        """Filter NaN/Inf and return a float64 array."""
        arr = np.array(
            [r for r in returns if not (math.isnan(r) or math.isinf(r))],
            dtype=np.float64,
        )
        return arr

    @staticmethod
    def _win_rate(returns: list[float]) -> float:
        arr = PerformanceTracker._clean(returns)
        if len(arr) == 0:
            return 0.0
        return float(np.mean(arr > 0))

    @staticmethod
    def _mean(returns: list[float]) -> float:
        arr = PerformanceTracker._clean(returns)
        if len(arr) == 0:
            return 0.0
        return float(np.mean(arr))

    @staticmethod
    def _std(returns: list[float]) -> float:
        arr = PerformanceTracker._clean(returns)
        if len(arr) <= 1:
            return 0.0
        return float(np.std(arr, ddof=1))

    @staticmethod
    def _best(returns: list[float]) -> float:
        arr = PerformanceTracker._clean(returns)
        if len(arr) == 0:
            return 0.0
        return float(np.max(arr))

    @staticmethod
    def _worst(returns: list[float]) -> float:
        arr = PerformanceTracker._clean(returns)
        if len(arr) == 0:
            return 0.0
        return float(np.min(arr))

    @staticmethod
    def _max_drawdown(returns_20d: list[float]) -> float:
        """
        Max drawdown from an equity curve built on 20d returns
        (treat trades as a sequential portfolio).
        Edge case: 1 trade → drawdown = max(0, -min_return).
        """
        arr = PerformanceTracker._clean(returns_20d)
        n = len(arr)
        if n == 0:
            return 0.0

        if n == 1:
            return max(0.0, -float(arr[0]) / 100.0)

        factors = 1.0 + arr / 100.0
        equity = np.cumprod(factors)
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak
        return float(np.max(dd))

    @staticmethod
    def _sharpe(period_returns: dict[int, list[float]]) -> float:
        """
        Annualized Sharpe ratio.
        For each trade at each holding period, compute daily return:
          daily = (1 + total_return/100) ^ (1/holding_days) - 1
        Pool all daily returns; annualize with sqrt(252).
        """
        daily_returns: list[float] = []
        for period in HOLDING_PERIODS:
            for ret in period_returns[period]:
                if math.isnan(ret) or math.isinf(ret):
                    continue
                daily_r = (1.0 + ret / 100.0) ** (1.0 / period) - 1.0
                if not (math.isnan(daily_r) or math.isinf(daily_r)):
                    daily_returns.append(daily_r)

        if len(daily_returns) <= 1:
            return 0.0

        dr_arr = np.array(daily_returns, dtype=np.float64)
        dr_mean = np.mean(dr_arr)
        dr_std = np.std(dr_arr, ddof=1)
        if dr_std < 1e-12:
            return 0.0
        return (dr_mean / dr_std) * math.sqrt(252)

    @staticmethod
    def _avg_holding_days(returns_20d: list[float]) -> float:
        """Average holding days for winning trades (20d period)."""
        arr = PerformanceTracker._clean(returns_20d)
        winners = arr[arr > 0]
        if len(winners) > 0:
            return 20.0
        return 0.0

    # ── Utility ──

    def clear(self) -> None:
        """Reset all recorded signals and returns."""
        self.signals.clear()
        for p in HOLDING_PERIODS:
            self.returns[p].clear()
            self._return_types[p].clear()


# ──────────────────────────────────────────────
#  Pretty-print utility
# ──────────────────────────────────────────────


def pretty_print_stats(stats: dict[int, PerformanceStats]) -> str:
    """Render stats as a human-readable table."""
    lines: list[str] = []
    for pt in PATTERN_TYPES:
        ps = stats.get(pt)
        if ps is None:
            continue
        label = "ALL" if pt == 0 else f"Type {pt}"
        lines.append(f"\n{'═' * 60}")
        lines.append(f"  {label}  —  {ps.total_signals} total signals")
        lines.append(f"{'═' * 60}")

        if ps.total_signals == 0:
            lines.append("  (no data)")
            continue

        header = (
            f"  {'Period':>6}  {'Win%':>7}  {'AvgRet':>8}  "
            f"{'StdDev':>7}  {'Best':>7}  {'Worst':>7}  "
            f"{'MaxDD':>7}  {'Sharpe':>7}  {'WinDays':>7}"
        )
        lines.append(header)
        lines.append("  " + "─" * (len(header) - 2))

        # Per-period rows
        period_labels = {
            5: (ps.win_rate_5d, ps.avg_return_5d, 0.0, 0.0, 0.0),
            10: (ps.win_rate_10d, ps.avg_return_10d, 0.0, 0.0, 0.0),
            20: (ps.win_rate_20d, ps.avg_return_20d, ps.return_std_20d,
                 ps.best_return_20d, ps.worst_return_20d),
            60: (ps.win_rate_60d, ps.avg_return_60d, 0.0, 0.0, 0.0),
        }

        for p in HOLDING_PERIODS:
            wr, ar, std, best, worst = period_labels[p]
            lines.append(
                f"  {p:>6d}  {wr:>6.1%}  {ar:>8.2f}  "
                f"{std:>7.2f}  {best:>7.2f}  {worst:>7.2f}  "
                f"{ps.max_drawdown:>6.1%}  {ps.sharpe_ratio:>7.2f}  "
                f"{ps.avg_holding_days:>7.1f}"
            )
    return "\n".join(lines)
