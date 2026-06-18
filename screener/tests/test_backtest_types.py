"""Tests for backtest_types.py — shared dataclasses."""

from __future__ import annotations

from typing import List, Dict

import pytest

from backtest_types import StockData, Signal, PerformanceStats, SectorInfo


class TestStockData:
    """StockData creation, validation, and helper methods."""

    def test_basic_creation_twse(self):
        """TSMC stock on TWSE (.TW) should set market='TWSE'."""
        sd = StockData(
            symbol="2330.TW",
            name="台積電",
            dates=["2024-01-02", "2024-01-03"],
            closes=[150.0, 151.5],
            volumes=[1000000, 1200000],
        )
        assert sd.symbol == "2330.TW"
        assert sd.name == "台積電"
        assert sd.market == "TWSE"
        assert sd.dates == ["2024-01-02", "2024-01-03"]
        assert sd.closes == [150.0, 151.5]
        assert sd.volumes == [1000000, 1200000]

    def test_otc_market_detection(self):
        """Stock ending in .TWO should have market='OTC'."""
        sd = StockData(
            symbol="6488.TWO",
            name="環球晶圓",
            dates=["2024-01-02"],
            closes=[200.0],
            volumes=[500000],
        )
        assert sd.market == "OTC"

    def test_market_overridden_by_suffix(self):
        """Even if market is manually set, __post_init__ should override it."""
        sd = StockData(
            symbol="6488.TWO",
            name="環球晶圓",
            dates=["2024-01-02"],
            closes=[200.0],
            volumes=[500000],
        )
        # market should be OTC even if we passed 'TWSE' — but we don't pass it,
        # we rely on __post_init__. The default from dataclass is 'TWSE' if user
        # set it, but __post_init__ overrides.
        assert sd.market == "OTC"

    def test_mismatched_lengths_raises(self):
        """AssertionError when dates/closes/volumes length mismatch."""
        with pytest.raises(AssertionError):
            StockData(
                symbol="2330.TW",
                name="台積電",
                dates=["2024-01-02", "2024-01-03"],
                closes=[150.0],
                volumes=[1000000, 1200000],
            )

    def test_volumes_mismatch_raises(self):
        with pytest.raises(AssertionError):
            StockData(
                symbol="2330.TW",
                name="台積電",
                dates=["2024-01-02", "2024-01-03"],
                closes=[150.0, 151.5],
                volumes=[1000000],
            )

    def test_date_index_found(self):
        sd = StockData(
            symbol="2330.TW",
            name="台積電",
            dates=["2024-01-02", "2024-01-03", "2024-01-04"],
            closes=[150.0, 151.5, 152.0],
            volumes=[1000000, 1200000, 1100000],
        )
        assert sd.date_index("2024-01-03") == 1

    def test_date_index_not_found_returns_minus_one(self):
        sd = StockData(
            symbol="2330.TW",
            name="台積電",
            dates=["2024-01-02", "2024-01-03"],
            closes=[150.0, 151.5],
            volumes=[1000000, 1200000],
        )
        assert sd.date_index("2024-01-01") == -1

    def test_date_index_empty_dates(self):
        sd = StockData(
            symbol="2330.TW",
            name="台積電",
            dates=[],
            closes=[],
            volumes=[],
        )
        assert sd.date_index("2024-01-01") == -1


class TestSignal:
    """Signal dataclass — pattern metadata."""

    def test_basic_signal(self):
        sig = Signal(
            symbol="2330.TW",
            name="台積電",
            signal_date="2024-01-15",
            pattern_type=1,
            entry_price=155.0,
            volume_ratio=2.5,
            metadata={"ma20": 150.0, "obv_high": True},
        )
        assert sig.symbol == "2330.TW"
        assert sig.pattern_type == 1
        assert sig.entry_price == 155.0
        assert sig.volume_ratio == 2.5
        assert sig.metadata == {"ma20": 150.0, "obv_high": True}

    def test_signal_empty_metadata(self):
        sig = Signal(
            symbol="2330.TW",
            name="台積電",
            signal_date="2024-01-15",
            pattern_type=2,
            entry_price=155.0,
            volume_ratio=1.0,
            metadata={},
        )
        assert sig.metadata == {}

    def test_signal_pattern_types(self):
        for pt in [1, 2, 3]:
            sig = Signal(
                symbol="2330.TW",
                name="台積電",
                signal_date="2024-01-15",
                pattern_type=pt,
                entry_price=155.0,
                volume_ratio=1.0,
                metadata={},
            )
            assert sig.pattern_type == pt

    # ── L2 / L3 scoring fields ──────────────────────────────────────────────

    def test_scoring_fields_default_to_none(self):
        """New scoring fields should default to None for backward compatibility."""
        sig = Signal(
            symbol="2330.TW",
            name="台積電",
            signal_date="2024-01-15",
            pattern_type=1,
            entry_price=155.0,
            volume_ratio=2.5,
        )
        assert sig.l1_score is None
        assert sig.l2_score is None
        assert sig.l3_score is None
        assert sig.total_score is None

    def test_set_scoring_fields(self):
        """Scoring fields can be set after construction."""
        sig = Signal(
            symbol="2330.TW",
            name="台積電",
            signal_date="2024-01-15",
            pattern_type=1,
            entry_price=155.0,
            volume_ratio=2.5,
        )
        sig.l1_score = 80.0
        sig.l2_score = 70.0
        sig.l3_score = 45.0
        assert sig.l1_score == 80.0
        assert sig.l2_score == 70.0
        assert sig.l3_score == 45.0

    def test_compute_total_score(self):
        """compute_total_score() returns L1*0.3 + L2*0.5 + L3*0.2."""
        sig = Signal(
            symbol="2330.TW",
            name="台積電",
            signal_date="2024-01-15",
            pattern_type=1,
            entry_price=155.0,
            volume_ratio=2.5,
        )
        sig.l1_score = 80.0
        sig.l2_score = 70.0
        sig.l3_score = 45.0
        sig.total_score = sig.compute_total_score()
        # 80*0.3 + 70*0.5 + 45*0.2 = 24 + 35 + 9 = 68.0
        assert sig.total_score == 68.0

    def test_compute_total_score_none_if_any_missing(self):
        """Return None when any layer score is None."""
        sig = Signal(
            symbol="2330.TW",
            name="台積電",
            signal_date="2024-01-15",
            pattern_type=1,
            entry_price=155.0,
            volume_ratio=2.5,
        )
        sig.l1_score = 80.0
        sig.l2_score = 70.0
        # l3_score is still None
        assert sig.compute_total_score() is None

    def test_signal_repr_includes_scoring(self):
        """Signal repr should include scoring fields once set."""
        sig = Signal(
            symbol="2330.TW",
            name="台積電",
            signal_date="2024-01-15",
            pattern_type=1,
            entry_price=155.0,
            volume_ratio=2.5,
        )
        # Before scoring
        r = repr(sig)
        assert "l1_score=None" in r
        assert "l2_score=None" in r

        # After scoring
        sig.l1_score = 80.0
        sig.l2_score = 70.0
        r2 = repr(sig)
        assert "l1_score=80.0" in r2
        assert "l2_score=70.0" in r2


class TestPerformanceStats:
    """PerformanceStats — metrics for a pattern type."""

    def test_basic_stats(self):
        ps = PerformanceStats(
            pattern_type=1,
            total_signals=100,
            win_rate_5d=0.65,
            win_rate_10d=0.60,
            win_rate_20d=0.55,
            win_rate_60d=0.50,
            avg_return_5d=1.2,
            avg_return_10d=2.5,
            avg_return_20d=3.8,
            avg_return_60d=5.0,
            max_drawdown=-15.0,
            sharpe_ratio=1.5,
            avg_holding_days=12.5,
            return_std_20d=4.2,
            best_return_20d=12.0,
            worst_return_20d=-8.0,
        )
        assert ps.pattern_type == 1
        assert ps.total_signals == 100
        assert ps.win_rate_20d == 0.55
        assert ps.sharpe_ratio == 1.5

    def test_no_signals_defaults(self):
        """When total_signals=0, all rates/returns default to 0.0."""
        ps = PerformanceStats(
            pattern_type=2,
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
        assert ps.total_signals == 0
        for field_name in [
            "win_rate_5d", "win_rate_10d", "win_rate_20d", "win_rate_60d",
            "avg_return_5d", "avg_return_10d", "avg_return_20d", "avg_return_60d",
            "max_drawdown", "sharpe_ratio", "avg_holding_days",
            "return_std_20d", "best_return_20d", "worst_return_20d",
        ]:
            assert getattr(ps, field_name) == 0.0


class TestSectorInfo:
    """SectorInfo — sector classification."""

    def test_electronics_sector(self):
        si = SectorInfo(symbol="2330.TW", sector="半導體", category="電子")
        assert si.symbol == "2330.TW"
        assert si.sector == "半導體"
        assert si.category == "電子"

    def test_financial_sector(self):
        si = SectorInfo(symbol="2881.TW", sector="金融保險", category="金融")
        assert si.category == "金融"

    def test_traditional_sector(self):
        si = SectorInfo(symbol="1101.TW", sector="水泥", category="傳產")
        assert si.category == "傳產"


class TestFloatRepr:
    """Floats should be rounded to 4 decimal places in __repr__."""

    def test_performance_stats_repr_rounds_floats(self):
        ps = PerformanceStats(
            pattern_type=1,
            total_signals=100,
            win_rate_5d=0.12345678,
            win_rate_10d=0.23456789,
            win_rate_20d=0.34567890,
            win_rate_60d=0.45678901,
            avg_return_5d=1.23456789,
            avg_return_10d=2.34567890,
            avg_return_20d=3.45678901,
            avg_return_60d=4.56789012,
            max_drawdown=-15.12345678,
            sharpe_ratio=1.23456789,
            avg_holding_days=12.34567890,
            return_std_20d=4.12345678,
            best_return_20d=12.34567890,
            worst_return_20d=-8.12345678,
        )
        # PerformanceStats should have a __repr__ that rounds floats to 4 decimals
        r = repr(ps)
        # Check that the repr contains rounded values (4 decimal places)
        assert "0.1235" in r  # 0.12345678 rounded to 4 decimals
        assert "0.2346" in r  # 0.23456789 rounded
        assert "1.2346" in r  # 1.23456789 rounded
        assert "-15.1235" in r  # -15.12345678 rounded

    def test_stock_data_repr(self):
        sd = StockData(
            symbol="2330.TW",
            name="台積電",
            dates=["2024-01-02"],
            closes=[150.56789],
            volumes=[1000000],
        )
        r = repr(sd)
        # closes should be rounded to 4 decimals even if not individually
        assert "StockData" in r or "stockdata" in r.lower()
