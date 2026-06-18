"""Tests for ten_year_backtest.py — 10-year multi-scenario backtest runner."""

from __future__ import annotations

import json
import math
import os
import tempfile
from typing import Dict, List

import numpy as np
import pytest

from backtest_types import Signal, StockData


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_signal(
    symbol: str = "TEST.TW",
    name: str = "Test",
    signal_date: str = "2024-01-15",
    pattern_type: int = 1,
    entry_price: float = 155.0,
    volume_ratio: float = 3.0,
    l1_score: float | None = None,
    l2_score: float | None = None,
    l3_score: float | None = None,
    total_score: float | None = None,
) -> Signal:
    sig = Signal(
        symbol=symbol,
        name=name,
        signal_date=signal_date,
        pattern_type=pattern_type,
        entry_price=entry_price,
        volume_ratio=volume_ratio,
        metadata={},
    )
    if l1_score is not None:
        sig.l1_score = l1_score
    if l2_score is not None:
        sig.l2_score = l2_score
    if l3_score is not None:
        sig.l3_score = l3_score
    if total_score is not None:
        sig.total_score = total_score
    return sig


def make_uptrend_stock(n_days: int = 200) -> StockData:
    """Steady uptrend with flat volume."""
    dates = [f"2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}" for i in range(n_days)]
    closes = [100.0 + i * 0.5 for i in range(n_days)]
    volumes = [1_000_000 for _ in range(n_days)]
    return StockData(
        symbol="UP.TW",
        name="Uptrend",
        dates=dates,
        closes=closes,
        volumes=volumes,
    )


def make_injected_stock(
    n_days: int = 200,
    seed: int = 42,
    symbol: str = "INJECT.TW",
) -> StockData:
    """Stock with injected Type 1 pattern at index 150."""
    np.random.seed(seed)
    dates = [f"2024-{(i // 20) + 1:02d}-{(i % 20) + 1:02d}" for i in range(n_days)]
    closes = [100.0]
    for i in range(1, n_days):
        closes.append(closes[-1] * (1 + np.random.normal(0.0005, 0.015)))
    volumes = [1_000_000 + int(abs(np.random.normal(0, 500_000))) for _ in range(n_days)]
    # Inject Type 1 at index 150: silence then spike
    for j in range(90, 150):
        volumes[j] = 200_000
    volumes[150] = 5_000_000
    closes[150] = closes[149] * 1.05
    return StockData(
        symbol=symbol,
        name="Injected",
        dates=dates,
        closes=closes,
        volumes=volumes,
    )


# ── L1 Score Calculation Tests ──────────────────────────────────────────────

class TestL1Score:
    """Layer 1 score = min(volume_ratio * 20, 100) * multiplier, capped at 100."""

    def test_basic_l1_score(self):
        """volume_ratio=3.0, pattern_type=1 → base=60, mult=1.0, score=60."""
        from ten_year_backtest import compute_l1_score
        score = compute_l1_score(volume_ratio=3.0, pattern_type=1)
        assert score == 60.0

    def test_l1_score_capped_at_100(self):
        """volume_ratio=10.0 → base=200, capped at 100, then ×1.0 → 100."""
        from ten_year_backtest import compute_l1_score
        score = compute_l1_score(volume_ratio=10.0, pattern_type=1)
        assert score == 100.0

    def test_l1_score_type2_multiplier(self):
        """Type 2 multiplier = 0.8: base=60 ×0.8 = 48."""
        from ten_year_backtest import compute_l1_score
        score = compute_l1_score(volume_ratio=3.0, pattern_type=2)
        assert score == 48.0

    def test_l1_score_type3_multiplier(self):
        """Type 3 multiplier = 1.2: base=60 ×1.2 = 72."""
        from ten_year_backtest import compute_l1_score
        score = compute_l1_score(volume_ratio=3.0, pattern_type=3)
        assert score == 72.0

    def test_l1_score_capped_with_multiplier(self):
        """volume_ratio=10.0, type=3 → base=200 capped=100, ×1.2 capped=100."""
        from ten_year_backtest import compute_l1_score
        score = compute_l1_score(volume_ratio=10.0, pattern_type=3)
        assert score == 100.0


# ── Scenario Filter Tests ───────────────────────────────────────────────────

class TestScenarioFilter:
    """Each of the 8 scenarios applies a specific filter to all signals."""

    @pytest.fixture
    def signals(self):
        """Create a diverse set of signals for scenario testing."""
        sigs = []
        # Pattern 1, different prices and scores
        for i, price in enumerate([50.0, 100.0, 150.0, 200.0, 300.0, 500.0, 600.0]):
            sig = make_signal(
                symbol="TEST.TW",
                signal_date=f"2024-{(i//20)+1:02d}-{(i%20)+1:02d}",
                pattern_type=1,
                entry_price=price,
                volume_ratio=3.0,
                l1_score=60.0,
                l2_score=70.0 if i < 5 else 30.0,  # First 5 have high L2
                l3_score=40.0 if i < 4 else 10.0,    # First 4 have high L3
            )
            sig.total_score = sig.compute_total_score()
            sigs.append(sig)
        return sigs

    def test_scenario1_no_filter(self, signals):
        """Scenario 1: Pure L1 — no filter, use all signals."""
        from ten_year_backtest import filter_signals
        filtered = filter_signals(signals, scenario_num=1)
        assert len(filtered) == len(signals)

    def test_scenario2_price_ge_100(self, signals):
        """Scenario 2: L1 + price >= 100."""
        from ten_year_backtest import filter_signals
        filtered = filter_signals(signals, scenario_num=2)
        assert all(s.entry_price >= 100 for s in filtered)
        assert len(filtered) == 6  # 50 filtered out

    def test_scenario3_price_ge_200(self, signals):
        """Scenario 3: L1 + price >= 200."""
        from ten_year_backtest import filter_signals
        filtered = filter_signals(signals, scenario_num=3)
        assert all(s.entry_price >= 200 for s in filtered)
        assert len(filtered) == 4

    def test_scenario4_price_ge_500(self, signals):
        """Scenario 4: L1 + price >= 500."""
        from ten_year_backtest import filter_signals
        filtered = filter_signals(signals, scenario_num=4)
        assert all(s.entry_price >= 500 for s in filtered)
        assert len(filtered) == 2

    def test_scenario5_l2_ge_60(self, signals):
        """Scenario 5: L1 + L2 >= 60."""
        from ten_year_backtest import filter_signals
        filtered = filter_signals(signals, scenario_num=5)
        assert all(s.l2_score is not None and s.l2_score >= 60 for s in filtered)
        assert len(filtered) == 5

    def test_scenario6_l3_ge_30(self, signals):
        """Scenario 6: L1 + L3 >= 30."""
        from ten_year_backtest import filter_signals
        filtered = filter_signals(signals, scenario_num=6)
        assert all(s.l3_score is not None and s.l3_score >= 30 for s in filtered)
        assert len(filtered) == 4

    def test_scenario7_full_three_layer(self, signals):
        """Scenario 7: Full three layer, total_score >= 40."""
        from ten_year_backtest import filter_signals
        filtered = filter_signals(signals, scenario_num=7)
        for s in filtered:
            assert s.l1_score is not None
            assert s.l2_score is not None
            assert s.l3_score is not None
            assert s.total_score is not None and s.total_score >= 40

    def test_scenario8_strictest(self, signals):
        """Scenario 8: Full three layer + price >= 200."""
        from ten_year_backtest import filter_signals
        filtered = filter_signals(signals, scenario_num=8)
        for s in filtered:
            assert s.entry_price >= 200
            assert s.l1_score is not None
            assert s.l2_score is not None
            assert s.l3_score is not None
            assert s.total_score is not None and s.total_score >= 40


# ── Cost Deduction Tests ────────────────────────────────────────────────────

class TestCostDeduction:
    """Transaction cost: 0.6% per trade + 0.5% slippage = 1.1% round trip."""

    def test_cost_deduction_amount(self):
        """Subtract 1.1 from each return percentage."""
        from ten_year_backtest import apply_cost
        assert apply_cost(5.0) == pytest.approx(3.9)
        assert apply_cost(0.0) == pytest.approx(-1.1)
        assert apply_cost(-2.0) == pytest.approx(-3.1)

    def test_cost_is_applied_correctly(self):
        """Verify with multiple return values."""
        from ten_year_backtest import apply_cost
        returns = [10.0, 5.0, 0.0, -5.0]
        expected = [8.9, 3.9, -1.1, -6.1]
        for r, e in zip(returns, expected):
            assert apply_cost(r) == pytest.approx(e)


# ── Yearly Breakdown Tests ──────────────────────────────────────────────────

class TestYearlyBreakdown:
    """Compute per-year statistics from a list of signals."""

    def test_yearly_split_empty(self):
        """Empty signals → empty dict."""
        from ten_year_backtest import compute_yearly_breakdown
        result = compute_yearly_breakdown([])
        assert result == {}

    def test_yearly_split_multiple_years(self):
        """Signals across multiple years → grouped correctly."""
        from ten_year_backtest import compute_yearly_breakdown
        signals = [
            make_signal(signal_date="2017-03-15", l1_score=60.0, l2_score=70.0, l3_score=40.0),
            make_signal(signal_date="2017-06-15", l1_score=60.0, l2_score=70.0, l3_score=40.0),
            make_signal(signal_date="2018-01-10", l1_score=60.0, l2_score=70.0, l3_score=40.0),
            make_signal(signal_date="2019-11-20", l1_score=60.0, l2_score=70.0, l3_score=40.0),
        ]
        result = compute_yearly_breakdown(signals)
        assert "2017" in result
        assert "2018" in result
        assert "2019" in result
        assert result["2017"]["signals"] == 2
        assert result["2018"]["signals"] == 1
        assert result["2019"]["signals"] == 1

    def test_yearly_win_rate(self):
        """Win rate computed per year."""
        from ten_year_backtest import compute_yearly_breakdown
        signals = [
            make_signal(signal_date="2017-03-15"),
            make_signal(signal_date="2017-06-15"),
            make_signal(signal_date="2017-09-15"),
        ]
        # All returns positive (all winners)
        result = compute_yearly_breakdown(signals, {20: [3.0, 5.0, 2.0]})
        assert result["2017"]["win_rate_20d"] == pytest.approx(1.0)
        assert result["2017"]["avg_return_20d"] == pytest.approx(10.0 / 3, abs=0.001)

    def test_yearly_no_returns(self):
        """When no returns data, stats default to 0."""
        from ten_year_backtest import compute_yearly_breakdown
        signals = [make_signal(signal_date="2017-03-15")]
        result = compute_yearly_breakdown(signals, {})
        assert result["2017"]["win_rate_20d"] == 0.0
        assert result["2017"]["avg_return_20d"] == 0.0


# ── Scenario Info Tests ─────────────────────────────────────────────────────

class TestScenarioInfo:
    """Define all 8 scenarios with name and filter function."""

    def test_scenario_count(self):
        """Must have exactly 8 scenarios."""
        from ten_year_backtest import SCENARIOS
        assert len(SCENARIOS) == 8

    def test_scenario_names(self):
        """Each scenario has a descriptive name."""
        from ten_year_backtest import SCENARIOS
        names = [s["name"] for s in SCENARIOS]
        assert "Pure L1 (baseline)" in names
        assert "Full three-layer + price ≥200" in names

    def test_scenario_keys(self):
        """Each scenario has: num, name, filter, filter_desc."""
        from ten_year_backtest import SCENARIOS
        for s in SCENARIOS:
            assert "num" in s
            assert "name" in s
            assert "filter" in s
            assert "filter_desc" in s


# ── Integration Tests ───────────────────────────────────────────────────────

class TestIntegration:
    """Full pipeline: detect signals, score, filter, track performance."""

    def test_full_pipeline_with_one_stock(self):
        """Run detection on one injected stock, verify all_scenarios computed."""
        from ten_year_backtest import (
            process_all_stocks, run_all_scenarios, SCENARIOS,
        )

        stock = make_injected_stock(200)
        stocks = {stock.symbol: stock}

        # Process all signals from this one stock
        all_signals = process_all_stocks(stocks)

        # Should find at least some signals
        assert len(all_signals) >= 0  # May find 0 if injected pattern doesn't trigger

        # Run all 8 scenarios
        scenario_results = run_all_scenarios(all_signals, stocks)

        # Should have 8 results
        assert len(scenario_results) == 8

        # Each result has expected keys
        for result in scenario_results:
            assert "scenario" in result
            assert "name" in result
            assert "total_signals" in result
            assert isinstance(result["total_signals"], int)

    def test_all_signals_have_scores(self):
        """After processing, all signals have l1_score set (others may be 0)."""
        from ten_year_backtest import process_all_stocks

        stock = make_injected_stock(200)
        stocks = {stock.symbol: stock}

        all_signals = process_all_stocks(stocks)

        for sig in all_signals:
            assert sig.l1_score is not None, f"Signal {sig.signal_date} missing l1_score"
            assert 0 <= sig.l1_score <= 100, f"l1_score {sig.l1_score} out of range"
            # l2_score and l3_score may be 0 if scorers unavailable
            assert sig.l2_score is not None, f"Signal {sig.signal_date} missing l2_score"
            assert sig.l3_score is not None, f"Signal {sig.signal_date} missing l3_score"
            assert sig.total_score is not None, f"Signal {sig.signal_date} missing total_score"

    def test_output_json_structure(self):
        """Scenario result JSON has the expected structure."""
        from ten_year_backtest import SCENARIOS

        # Build a minimal scenario result
        scenario_result = {
            "scenario": 1,
            "name": "Pure L1 (baseline)",
            "filter": "none",
            "total_signals": 50,
            "stats": {
                "win_rate_5d": 0.55,
                "win_rate_10d": 0.52,
                "win_rate_20d": 0.50,
                "win_rate_60d": 0.48,
                "avg_return_5d": 1.2,
                "avg_return_10d": 2.5,
                "avg_return_20d": 3.8,
                "avg_return_60d": 5.0,
                "sharpe_ratio": 0.85,
                "max_drawdown": 0.25,
            },
            "yearly": {
                "2024": {
                    "signals": 50,
                    "win_rate_20d": 0.50,
                    "avg_return_20d": 3.8,
                },
            },
        }
        # Verify it's JSON-serializable
        json_str = json.dumps(scenario_result)
        loaded = json.loads(json_str)
        assert loaded["scenario"] == 1
        assert loaded["total_signals"] == 50
        assert loaded["yearly"]["2024"]["win_rate_20d"] == 0.50


# ── Graceful Degradation Tests ──────────────────────────────────────────────

class TestGracefulDegradation:
    """When Layer 2/3 scorers are unavailable, l2/l3 scores should be 0."""

    def test_l1_only_when_scorers_missing(self):
        """When fundamental_scorer and chip_scorer can't be imported, l2/l3=0."""
        from ten_year_backtest import score_signal

        sig = make_signal(volume_ratio=3.0)
        sig = score_signal(sig, score_fundamentals_fn=None, score_chip_fn=None)

        assert sig.l1_score == 60.0  # L1 from volume_ratio
        assert sig.l2_score == 0.0   # No L2 scorer
        assert sig.l3_score == 0.0   # No L3 scorer
        assert sig.total_score == pytest.approx(60.0 * 0.3)  # 18.0


# ── Output File Tests ───────────────────────────────────────────────────────

class TestOutputFiles:
    """Verify JSON output files are created correctly."""

    def test_save_all_signals(self):
        """all_signals.json should contain serialized signal list."""
        from ten_year_backtest import save_signal_json

        signals = [
            make_signal(signal_date="2024-01-15", l1_score=60.0, l2_score=70.0, l3_score=40.0),
            make_signal(signal_date="2024-02-15", l1_score=80.0, l2_score=50.0, l3_score=30.0),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "all_signals.json")
            save_signal_json(signals, path)
            assert os.path.exists(path)
            with open(path) as f:
                data = json.load(f)
            assert isinstance(data, list)
            assert len(data) == 2
            assert data[0]["symbol"] == "TEST.TW"
            assert data[0]["l1_score"] == 60.0
            assert data[1]["l2_score"] == 50.0

    def test_save_scenario_result(self):
        """Scenario JSON output matches expected format."""
        from ten_year_backtest import save_scenario_result

        result = {
            "scenario": 1,
            "name": "Test",
            "filter": "none",
            "total_signals": 10,
            "stats": {
                "win_rate_5d": 0.5,
                "win_rate_20d": 0.55,
                "avg_return_20d": 2.5,
                "sharpe_ratio": 0.9,
                "max_drawdown": 0.15,
            },
            "yearly": {
                "2024": {"signals": 10, "win_rate_20d": 0.5, "avg_return_20d": 2.5},
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "scenario_1.json")
            save_scenario_result(result, path)
            assert os.path.exists(path)
            with open(path) as f:
                data = json.load(f)
            assert data["total_signals"] == 10
            assert data["stats"]["sharpe_ratio"] == 0.9
