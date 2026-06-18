"""Tests for performance.py — trade tracking and statistics."""

import math

import numpy as np
import pytest

from backtest_types import Signal, StockData, PerformanceStats
from performance import (
    HOLDING_PERIODS,
    PerformanceTracker,
    pretty_print_stats,
)


# ──────────────────────────────────────────────
#  Fixtures
# ──────────────────────────────────────────────


@pytest.fixture
def sample_stocks() -> dict[str, StockData]:
    """Return a small dict of StockData for testing."""
    dates = [f"2024-01-{d:02d}" for d in range(2, 32)]
    # Steady uptrend: close starts at 100, increases by 0.5 per day
    close_uptrend = [100.0 + i * 0.5 for i in range(len(dates))]
    # Volatile stock: big swings
    close_volatile = [100.0 + 10 * math.sin(i * 0.5) for i in range(len(dates))]

    return {
        "2330.TW": StockData(
            symbol="2330.TW",
            name="TSMC",
            dates=dates,
            closes=close_uptrend,
            volumes=[1000] * len(dates),
        ),
        "6488.TWO": StockData(
            symbol="6488.TWO",
            name="TestCorp",
            dates=dates,
            closes=close_volatile,
            volumes=[500] * len(dates),
        ),
        "SHORT.TW": StockData(
            symbol="SHORT.TW",
            name="ShortData",
            dates=dates[:10],  # Only 10 days of data
            closes=[100.0 + i * 0.5 for i in range(10)],
            volumes=[1000] * 10,
        ),
    }


def _make_sig(symbol: str, pattern_type: int, date: str, price: float) -> Signal:
    """Helper to create a Signal with minimal boilerplate."""
    return Signal(
        symbol=symbol,
        name=symbol,
        signal_date=date,
        pattern_type=pattern_type,
        entry_price=price,
        volume_ratio=1.0,
        metadata={},
    )


@pytest.fixture
def tracker() -> PerformanceTracker:
    return PerformanceTracker()


@pytest.fixture
def populated_tracker(tracker: PerformanceTracker, sample_stocks: dict[str, StockData]) -> PerformanceTracker:
    """A tracker with 3 signals recorded and returns computed."""
    tracker.record_signal(_make_sig("2330.TW", 1, "2024-01-10", 104.5))
    tracker.record_signal(_make_sig("6488.TWO", 2, "2024-01-15", 105.0))
    tracker.record_signal(_make_sig("2330.TW", 3, "2024-01-20", 109.0))
    tracker.compute_forward_returns(sample_stocks)
    return tracker


# ──────────────────────────────────────────────
#  record_signal
# ──────────────────────────────────────────────


class TestRecordSignal:
    def test_appends_signal(self, tracker: PerformanceTracker) -> None:
        s = _make_sig("2330.TW", 1, "2024-01-10", 100.0)
        tracker.record_signal(s)
        assert len(tracker.signals) == 1
        assert tracker.signals[0] is s

    def test_appends_multiple(self, tracker: PerformanceTracker) -> None:
        for i in range(5):
            tracker.record_signal(_make_sig("2330.TW", 1, "2024-01-10", 100.0))
        assert len(tracker.signals) == 5


# ──────────────────────────────────────────────
#  compute_forward_returns
# ──────────────────────────────────────────────


class TestComputeForwardReturns:
    def test_normal_case(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Signal on 2024-01-10 (index 8), T+N should compute correctly."""
        tracker.record_signal(_make_sig("2330.TW", 1, "2024-01-10", 104.5))
        tracker.compute_forward_returns(sample_stocks)

        # 2024-01-10 is index 8 in dates (dates start at 2024-01-02 idx=0)
        # close[8] = 100 + 8*0.5 = 104.0
        # 5d forward: close[13] = 100 + 13*0.5 = 106.5 → (106.5/104.0 - 1)*100
        expected_5 = (106.5 / 104.0 - 1.0) * 100.0
        assert len(tracker.returns[5]) == 1
        assert tracker.returns[5][0] == pytest.approx(expected_5, rel=1e-10)

    def test_forward_returns_all_periods(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Verify all holding periods are populated."""
        tracker.record_signal(_make_sig("2330.TW", 1, "2024-01-10", 104.5))
        tracker.compute_forward_returns(sample_stocks)

        for p in HOLDING_PERIODS:
            assert len(tracker.returns[p]) == 1

    def test_signal_date_not_found_skipped(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Signal date not in stock dates → skip with warning."""
        tracker.record_signal(_make_sig("2330.TW", 1, "2099-12-31", 1000.0))
        tracker.compute_forward_returns(sample_stocks)
        for p in HOLDING_PERIODS:
            assert len(tracker.returns[p]) == 0, f"period {p} should be empty"

    def test_stock_not_found_skipped(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Stock id missing from all_stocks → skip with warning."""
        tracker.record_signal(_make_sig("MISSING.TW", 1, "2024-01-10", 100.0))
        tracker.compute_forward_returns(sample_stocks)
        for p in HOLDING_PERIODS:
            assert len(tracker.returns[p]) == 0

    def test_tn_exceeds_data_uses_last_close(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Signal near end of data — T+N should clamp to last index."""
        # "SHORT.TW" has dates up to 2024-01-11 (index 9)
        tracker.record_signal(_make_sig("SHORT.TW", 1, "2024-01-04", 101.5))
        tracker.compute_forward_returns(sample_stocks)

        # idx of 2024-01-04 in SHORT.TW dates is 2
        # close[2] = 100 + 2*0.5 = 101.0
        # For p=60: idx = min(2+60, 9) = 9, close[9] = 100 + 9*0.5 = 104.5
        # return = (104.5/101.0 - 1)*100
        expected_60 = (104.5 / 101.0 - 1.0) * 100.0
        assert tracker.returns[60][0] == pytest.approx(expected_60, rel=1e-10)
        # 5 days forward: idx=7, close[7]=103.5
        expected_5 = (103.5 / 101.0 - 1.0) * 100.0
        assert tracker.returns[5][0] == pytest.approx(expected_5, rel=1e-10)

    def test_nan_close_skipped(
        self, tracker: PerformanceTracker
    ) -> None:
        """Stock close contains NaN at signal date → skip."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 12)]
        closes = [100.0, 101.0, float("nan"), 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0]
        stock = {
            "NAN.TW": StockData(
                symbol="NAN.TW",
                name="NaNTest",
                dates=dates,
                closes=closes,
                volumes=[1000] * len(dates),
            ),
        }

        # Signal at a valid date
        tracker.record_signal(_make_sig("NAN.TW", 1, "2024-01-03", 101.0))
        tracker.compute_forward_returns(stock)
        # close at idx 1 (2024-01-03) = 101.0, ok
        assert len(tracker.returns[5]) == 1

        tracker.clear()
        # Signal at NaN close date
        tracker.record_signal(_make_sig("NAN.TW", 1, "2024-01-04", float("nan")))
        tracker.compute_forward_returns(stock)
        for p in HOLDING_PERIODS:
            assert len(tracker.returns[p]) == 0

    def test_multiple_signals_aggregate(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Multiple signals produce multiple returns per period."""
        sigs = [
            _make_sig("2330.TW", 1, "2024-01-05", 102.0),
            _make_sig("2330.TW", 1, "2024-01-10", 104.5),
            _make_sig("2330.TW", 2, "2024-01-15", 107.0),
        ]
        for s in sigs:
            tracker.record_signal(s)
        tracker.compute_forward_returns(sample_stocks)

        assert len(tracker.returns[5]) == 3
        assert len(tracker.returns[10]) == 3

    def test_clear_resets(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Clear wipes all signals and returns."""
        tracker.record_signal(_make_sig("2330.TW", 1, "2024-01-10", 104.5))
        tracker.compute_forward_returns(sample_stocks)
        assert len(tracker.signals) == 1
        assert len(tracker.returns[5]) == 1

        tracker.clear()
        assert len(tracker.signals) == 0
        for p in HOLDING_PERIODS:
            assert len(tracker.returns[p]) == 0


# ──────────────────────────────────────────────
#  compute_stats
# ──────────────────────────────────────────────


class TestComputeStats:
    def test_empty_tracker_returns_zeros(self, tracker: PerformanceTracker) -> None:
        """No signals → all stats should be zero."""
        tracker.compute_forward_returns({})
        stats = tracker.compute_stats()

        for pt in (0, 1, 2, 3):
            ps = stats[pt]
            assert ps.pattern_type == pt
            assert ps.total_signals == 0
            assert ps.win_rate_5d == 0.0
            assert ps.win_rate_10d == 0.0
            assert ps.win_rate_20d == 0.0
            assert ps.win_rate_60d == 0.0
            assert ps.avg_return_5d == 0.0
            assert ps.avg_return_10d == 0.0
            assert ps.avg_return_20d == 0.0
            assert ps.avg_return_60d == 0.0
            assert ps.max_drawdown == 0.0
            assert ps.sharpe_ratio == 0.0
            assert ps.avg_holding_days == 0.0
            assert ps.return_std_20d == 0.0
            assert ps.best_return_20d == 0.0
            assert ps.worst_return_20d == 0.0

    def test_all_positive_returns(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Signal in an uptrend → all returns positive → win rate=1."""
        tracker.record_signal(_make_sig("2330.TW", 1, "2024-01-05", 102.0))
        tracker.compute_forward_returns(sample_stocks)
        stats = tracker.compute_stats()

        ps = stats[0]  # ALL
        assert ps.win_rate_5d == 1.0
        assert ps.win_rate_20d == 1.0
        assert ps.avg_holding_days == 20.0  # winners exist at 20d

    def test_all_negative_returns(self, tracker: PerformanceTracker) -> None:
        """Downtrend stock → all returns negative → win rate=0."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]
        closes = [100.0 - i * 0.5 for i in range(len(dates))]  # downtrend
        stock = {
            "DOWN.TW": StockData(
                symbol="DOWN.TW",
                name="DownTrend",
                dates=dates,
                closes=closes,
                volumes=[1000] * len(dates),
            ),
        }
        tracker.record_signal(_make_sig("DOWN.TW", 2, "2024-01-10", 96.0))
        tracker.compute_forward_returns(stock)
        stats = tracker.compute_stats()

        ps = stats[2]
        assert ps.win_rate_20d == 0.0
        assert ps.avg_holding_days == 0.0  # no winners at 20d

    def test_per_pattern_type(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Different pattern types should produce separate stats."""
        tracker.record_signal(_make_sig("2330.TW", 1, "2024-01-05", 102.0))
        tracker.record_signal(_make_sig("6488.TWO", 2, "2024-01-10", 108.0))
        tracker.record_signal(_make_sig("2330.TW", 3, "2024-01-15", 107.0))
        tracker.compute_forward_returns(sample_stocks)
        stats = tracker.compute_stats()

        # Each type has its own signals
        assert stats[1].total_signals == 1
        assert stats[2].total_signals == 1
        assert stats[3].total_signals == 1
        assert stats[0].total_signals == 3  # ALL combined

    def test_max_drawdown_single_trade(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Single trade → max_drawdown = max(0, -return_at_20d / 100)."""
        # Volatile stock — we only check the 20d return
        tracker.record_signal(_make_sig("6488.TWO", 1, "2024-01-15", 105.0))
        tracker.compute_forward_returns(sample_stocks)
        stats = tracker.compute_stats()

        ps = stats[1]
        ret_20d = stats[1].avg_return_20d  # in %
        # Single trade: max_drawdown = max(0, -return/100)
        if stats[1].worst_return_20d < 0:
            assert ps.max_drawdown == pytest.approx(-stats[1].worst_return_20d / 100.0, rel=1e-6)
        else:
            assert ps.max_drawdown == 0.0

    def test_sharpe_ratio_positive(
        self, tracker: PerformanceTracker, sample_stocks: dict[str, StockData]
    ) -> None:
        """Multiple uptrend signals → positive Sharpe (variance from different entry points)."""
        for d, p in [("2024-01-05", 102.0), ("2024-01-10", 104.5), ("2024-01-15", 107.0)]:
            tracker.record_signal(_make_sig("2330.TW", 1, d, p))
        tracker.compute_forward_returns(sample_stocks)
        stats = tracker.compute_stats()

        ps = stats[1]
        # With 3 signals, should compute Sharpe across pooled daily returns
        # In an uptrend, should be positive
        assert ps.sharpe_ratio > 0, "uptrend should have positive Sharpe"

    def test_sharpe_ratio_negative(self, tracker: PerformanceTracker) -> None:
        """Multiple downtrend signals → negative Sharpe."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]
        closes = [100.0 - i * 1.0 for i in range(len(dates))]
        stock = {
            "DN.TW": StockData(
                symbol="DN.TW",
                name="Down",
                dates=dates,
                closes=closes,
                volumes=[1000] * len(dates),
            ),
        }
        for d in ("2024-01-10", "2024-01-15", "2024-01-20"):
            tracker.record_signal(_make_sig("DN.TW", 1, d, 100.0))
        tracker.compute_forward_returns(stock)
        stats = tracker.compute_stats()

        ps = stats[1]
        assert ps.sharpe_ratio < 0, "downtrend should have negative Sharpe"

    def test_std_deviation(self, populated_tracker: PerformanceTracker) -> None:
        """Std dev should be >= 0."""
        stats = populated_tracker.compute_stats()
        assert stats[0].return_std_20d >= 0

    def test_period_zero_pattern_type_not_in_signals(
        self, tracker: PerformanceTracker
    ) -> None:
        """No signals of a given type → total_signals=0, stats all zero."""
        tracker.record_signal(_make_sig("2330.TW", 1, "2024-01-10", 104.5))
        tracker.compute_forward_returns({})
        stats = tracker.compute_stats()

        # Type 2 and 3 never had signals recorded (but also no returns since empty stocks)
        for pt in (2, 3):
            assert stats[pt].total_signals == 0
            assert stats[pt].win_rate_20d == 0.0
            assert stats[pt].avg_return_20d == 0.0

    def test_sharpe_zero_when_no_variance(self, tracker: PerformanceTracker) -> None:
        """All returns identical → Sharpe = 0 (std=0)."""
        dates = [f"2024-01-{d:02d}" for d in range(2, 32)]
        closes = [100.0] * len(dates)  # flat
        stock = {
            "FLAT.TW": StockData(
                symbol="FLAT.TW",
                name="Flat",
                dates=dates,
                closes=closes,
                volumes=[1000] * len(dates),
            ),
        }
        tracker.record_signal(_make_sig("FLAT.TW", 1, "2024-01-10", 100.0))
        tracker.compute_forward_returns(stock)
        stats = tracker.compute_stats()

        assert stats[0].sharpe_ratio == 0.0, "flat returns → Sharpe = 0"


# ──────────────────────────────────────────────
#  pretty_print_stats (smoke test)
# ──────────────────────────────────────────────


class TestPrettyPrint:
    def test_empty_stats(self) -> None:
        """Empty stats should not crash."""
        empty = {
            pt: PerformanceStats(
                pattern_type=pt,
                total_signals=0,
                win_rate_5d=0.0,
                win_rate_10d=0.0,
                win_rate_20d=0.0,
                win_rate_60d=0.0,
                avg_return_5d=0.0,
                avg_return_10d=0.0,
                avg_return_20d=0.0,
                avg_return_60d=0.0,
                max_drawdown=0.0,
                sharpe_ratio=0.0,
                avg_holding_days=0.0,
                return_std_20d=0.0,
                best_return_20d=0.0,
                worst_return_20d=0.0,
            )
            for pt in (0, 1, 2, 3)
        }
        output = pretty_print_stats(empty)
        assert isinstance(output, str)
        assert len(output) > 0

    def test_populated_stats(self, populated_tracker: PerformanceTracker) -> None:
        """Populated tracker should produce readable table."""
        stats = populated_tracker.compute_stats()
        output = pretty_print_stats(stats)
        assert isinstance(output, str)
        assert "ALL" in output
        assert "Type 1" in output
        assert "Type 2" in output
        assert "Type 3" in output
        assert "Period" in output
        assert "Win%" in output
        assert "Sharpe" in output
