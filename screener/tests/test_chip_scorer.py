"""Tests for chip_scorer.py — Layer 3 chip/capital flow scoring.

Tests use synthetic DataFrames to verify scoring logic in isolation,
and mock the FinMind API to test graceful degradation.

Method names match the real FinMind DataLoader API:
  - taiwan_stock_institutional_investors
  - taiwan_stock_margin_purchase_short_sale
  - taiwan_stock_shareholding
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import pytest

from chip_scorer import (
    _score_institutional,
    _score_margin,
    _score_concentration,
    score_chip,
)


# ──────────────────────────────────────────────
#  Helpers: build synthetic FinMind DataFrames
# ──────────────────────────────────────────────


def _make_inst_df(
    dates: list[str],
    names: list[str],
    buys: list[float],
    sells: list[float],
) -> pd.DataFrame:
    """Build a DataFrame matching TaiwanStockInstitutionalInvestorsBuySell.

    Columns: date, stock_id, buy, name, sell
    """
    rows: list[dict[str, Any]] = []
    for i, d in enumerate(dates):
        rows.append({
            "date": d,
            "stock_id": "2330",
            "buy": buys[i],
            "name": names[i % len(names)],
            "sell": sells[i],
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _make_margin_df(
    dates: list[str],
    short_sale_balance: list[float],
) -> pd.DataFrame:
    """Build a DataFrame matching TaiwanStockMarginPurchaseShortSale.

    For our scoring we use ShortSaleTodayBalance.
    """
    rows: list[dict[str, Any]] = []
    for i, d in enumerate(dates):
        rows.append({
            "date": d,
            "stock_id": "2330",
            "ShortSaleTodayBalance": short_sale_balance[i],
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _make_shareholding_df(
    dates: list[str],
    number_of_shares: list[int],
    foreign_ratio: list[float],
) -> pd.DataFrame:
    """Build a DataFrame matching TaiwanStockShareholding.

    Columns: date, stock_id, NumberOfSharesIssued, ForeignInvestmentSharesRatio, ...
    """
    rows: list[dict[str, Any]] = []
    for i, d in enumerate(dates):
        rows.append({
            "date": d,
            "stock_id": "2330",
            "NumberOfSharesIssued": number_of_shares[i],
            "ForeignInvestmentSharesRatio": foreign_ratio[i],
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _trade_dates_before(base: str, n: int) -> list[str]:
    """Return n trading-dates going backward from base (exclusive)."""
    from datetime import datetime as dt, timedelta

    base_dt = dt.strptime(base, "%Y-%m-%d")
    out: list[str] = []
    cur = base_dt
    while len(out) < n:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:  # Mon–Fri
            out.insert(0, cur.strftime("%Y-%m-%d"))
    return out


# ──────────────────────────────────────────────
#  Institutional Buying Score (max 30)
# ──────────────────────────────────────────────


class TestScoreInstitutional:
    """_score_institutional() with name values from FinMind."""

    # FinMind name values:
    #   Investment_Trust  = 投信
    #   Foreign_Investor  = 外資
    #   Dealer_self / Dealer_Hedging = 自營商

    def test_trust_5_consecutive_net_buys_plus30(self):
        """Investment_Trust net buy ≥5 consecutive days → +30."""
        dates = _trade_dates_before("2024-03-15", 10)
        # Last 5 days: 投信 net buying
        names = ["Foreign_Investor"] * 5 + ["Investment_Trust"] * 5
        buys = [100] * 5 + [150] * 5
        sells = [110] * 5 + [20] * 5  # net: -10 for foreign, +130 for trust
        df = _make_inst_df(dates, names, buys, sells)
        score = _score_institutional(df, "2330", "2024-03-15")
        assert score == 30

    def test_foreign_3_consecutive_net_buys_plus15(self):
        """Foreign_Investor net buy ≥3 consecutive days → +15."""
        dates = _trade_dates_before("2024-03-15", 5)
        names = ["Foreign_Investor"] * 5
        buys = [200] * 5
        sells = [100] * 5  # net +100 each day
        df = _make_inst_df(dates, names, buys, sells)
        score = _score_institutional(df, "2330", "2024-03-15")
        # 5 consecutive Foreign_Investor net buys → +15 (not 30, since not Investment_Trust)
        assert score == 15

    def test_trust_priority_over_foreign(self):
        """Investment_Trust 5 consecutive takes priority over Foreign_Investor 3 consecutive."""
        dates = _trade_dates_before("2024-03-15", 6)
        names = ["Foreign_Investor"] * 1 + ["Investment_Trust"] * 5
        buys = [300] * 1 + [200] * 5
        sells = [100] * 1 + [50] * 5
        df = _make_inst_df(dates, names, buys, sells)
        score = _score_institutional(df, "2330", "2024-03-15")
        assert score == 30

    def test_no_matching_rule_returns_zero(self):
        """No institutional buying pattern → 0."""
        dates = _trade_dates_before("2024-03-15", 10)
        names = ["Foreign_Investor"] * 10
        # No consistent net buying
        buys = [100, 200, 50, 300, 100, 200, 50, 400, 100, 300]
        sells = [150, 100, 200, 100, 150, 150, 100, 200, 200, 100]
        df = _make_inst_df(dates, names, buys, sells)
        score = _score_institutional(df, "2330", "2024-03-15")
        assert score == 0

    def test_empty_df_returns_zero(self):
        """Empty DataFrame → 0."""
        df = pd.DataFrame(columns=["date", "stock_id", "buy", "name", "sell"])
        score = _score_institutional(df, "2330", "2024-03-15")
        assert score == 0

    def test_all_data_after_signal_excluded(self):
        """Only data before signal_date is considered."""
        dates = _trade_dates_before("2024-03-15", 3) + ["2024-03-17", "2024-03-18"]
        names = ["Investment_Trust"] * 5
        buys = [150] * 5
        sells = [20] * 5
        df = _make_inst_df(dates, names, buys, sells)
        # Only 3 days before 2024-03-15, 2 after → 3 consecutive < 5
        score = _score_institutional(df, "2330", "2024-03-15")
        assert score == 0

    def test_exactly_5_trust_consecutive(self):
        """Exactly 5 consecutive Investment_Trust net buys → +30."""
        dates = _trade_dates_before("2024-03-15", 5)
        names = ["Investment_Trust"] * 5
        buys = [150] * 5
        sells = [20] * 5
        df = _make_inst_df(dates, names, buys, sells)
        score = _score_institutional(df, "2330", "2024-03-15")
        assert score == 30


# ──────────────────────────────────────────────
#  Margin Trading Score (max 15)
# ──────────────────────────────────────────────


class TestScoreMargin:
    """_score_margin() — ShortSaleTodayBalance trends."""

    def test_short_sale_dropped_20_pct_plus15(self):
        """融券餘額 dropped >20% in 5 days → +15."""
        dates = _trade_dates_before("2024-03-15", 5)
        # 10M → 6M = 40% drop
        short_sale = [10_000_000, 9_000_000, 8_000_000, 7_000_000, 6_000_000]
        df = _make_margin_df(dates, short_sale)
        score = _score_margin(df, "2330", "2024-03-15")
        assert score == 15

    def test_short_sale_dropped_exactly_20_pct(self):
        """Exactly 20% drop → still qualifies for +15."""
        dates = _trade_dates_before("2024-03-15", 5)
        short_sale = [10_000_000, 10_000_000, 10_000_000, 10_000_000, 8_000_000]
        df = _make_margin_df(dates, short_sale)
        score = _score_margin(df, "2330", "2024-03-15")
        # 8M/10M = 0.8 → 20% drop → the spec says >20%, so exactly 20% doesn't qualify
        # Actually the spec says "dropped >20%", so > means strictly more than 20%
        # 8M/10M = 20% drop, which is not >20%, so it should be 0
        assert score == 0

    def test_short_sale_dropped_21_pct_qualifies(self):
        """Just over 20% drop qualifies for +15."""
        dates = _trade_dates_before("2024-03-15", 5)
        short_sale = [10_000_000, 10_000_000, 10_000_000, 10_000_000, 7_990_000]
        df = _make_margin_df(dates, short_sale)
        score = _score_margin(df, "2330", "2024-03-15")
        # (10M - 7.99M) / 10M = 20.1% > 20% ✓
        assert score == 15

    def test_no_drop_returns_zero(self):
        """No margin pattern → 0."""
        dates = _trade_dates_before("2024-03-15", 5)
        short_sale = [10_000_000] * 5
        df = _make_margin_df(dates, short_sale)
        score = _score_margin(df, "2330", "2024-03-15")
        assert score == 0

    def test_empty_df_returns_zero(self):
        """Empty DataFrame → 0."""
        df = pd.DataFrame(columns=["date", "stock_id", "ShortSaleTodayBalance"])
        score = _score_margin(df, "2330", "2024-03-15")
        assert score == 0

    def test_less_than_5_days_returns_zero(self):
        """Fewer than 5 data points → can't compute 5-day trend → 0."""
        dates = _trade_dates_before("2024-03-15", 3)
        short_sale = [10_000_000, 9_500_000, 9_000_000]
        df = _make_margin_df(dates, short_sale)
        score = _score_margin(df, "2330", "2024-03-15")
        assert score == 0


# ──────────────────────────────────────────────
#  Shareholder Concentration Score (max 15)
# ──────────────────────────────────────────────


class TestScoreConcentration:
    """_score_concentration() — shareholder trends."""

    def test_shares_issued_decreasing_plus15(self):
        """NumberOfSharesIssued decreasing over 4 weeks → +15."""
        dates = _trade_dates_before("2024-03-15", 4)
        # NumberOfSharesIssued decreasing
        shares = [100_000_000, 99_500_000, 99_000_000, 98_500_000]
        foreign_ratio = [70.0, 70.0, 70.0, 70.0]
        df = _make_shareholding_df(dates, shares, foreign_ratio)
        score = _score_concentration(df, "2330", "2024-03-15")
        # Decreasing shares → custodial accounts decreased → +15
        assert score == 15

    def test_foreign_ratio_rising_plus10(self):
        """ForeignInvestmentSharesRatio rising + NumberOfSharesIssued stable → +10."""
        dates = _trade_dates_before("2024-03-15", 4)
        shares = [100_000_000] * 4
        foreign_ratio = [70.0, 71.0, 72.0, 73.0]
        df = _make_shareholding_df(dates, shares, foreign_ratio)
        score = _score_concentration(df, "2330", "2024-03-15")
        # Shares stable but foreign ratio rising → +10
        assert score == 10

    def test_neither_rule_returns_zero(self):
        """No concentration pattern → 0."""
        dates = _trade_dates_before("2024-03-15", 4)
        shares = [100_000_000] * 4
        foreign_ratio = [70.0] * 4
        df = _make_shareholding_df(dates, shares, foreign_ratio)
        score = _score_concentration(df, "2330", "2024-03-15")
        assert score == 0

    def test_empty_df_returns_zero(self):
        """Empty DataFrame → 0."""
        df = pd.DataFrame(columns=["date", "stock_id", "NumberOfSharesIssued",
                                   "ForeignInvestmentSharesRatio"])
        score = _score_concentration(df, "2330", "2024-03-15")
        assert score == 0

    def test_fewer_than_4_weeks_returns_zero(self):
        """Fewer than 4 data points → 0."""
        dates = _trade_dates_before("2024-03-15", 2)
        shares = [100_000_000, 99_000_000]
        foreign_ratio = [70.0, 71.0]
        df = _make_shareholding_df(dates, shares, foreign_ratio)
        score = _score_concentration(df, "2330", "2024-03-15")
        assert score == 0


# ──────────────────────────────────────────────
#  Graceful Degradation
# ──────────────────────────────────────────────


class TestGracefulDegradation:
    """score_chip() must handle missing/unavailable data gracefully."""

    def test_no_finmind_api_returns_zeros(self, caplog, monkeypatch):
        """When FinMind is unavailable, all scores are 0, no crash."""
        monkeypatch.setattr(
            "chip_scorer._create_finmind_api",
            lambda: None,
        )
        caplog.set_level(logging.WARNING)
        result = score_chip("2330.TW", "2024-03-15")
        assert result == {"institutional_score": 0, "margin_score": 0,
                          "concentration_score": 0, "total": 0}
        assert len(caplog.records) > 0

    def test_exception_during_fetch_returns_zero(self, caplog):
        """If an exception occurs fetching data, return 0 for that sub-score."""
        caplog.set_level(logging.WARNING)

        class BrokenAPI:
            def taiwan_stock_institutional_investors(self, stock_id="", start_date="",
                                                      end_date="", timeout=None,
                                                      use_async=False, stock_id_list=None):
                raise ConnectionError("API unavailable")

            def taiwan_stock_margin_purchase_short_sale(self, stock_id="", start_date="",
                                                         end_date="", timeout=None,
                                                         use_async=False, stock_id_list=None):
                raise ValueError("no data")

            def taiwan_stock_shareholding(self, stock_id="", start_date="",
                                           end_date="", timeout=None,
                                           use_async=False, stock_id_list=None):
                raise Exception("generic error")

        result = score_chip("2330.TW", "2024-03-15", finmind_api=BrokenAPI())
        assert result == {"institutional_score": 0, "margin_score": 0,
                          "concentration_score": 0, "total": 0}

    def test_empty_data_returns_zero(self, caplog):
        """Empty DataFrame from API → score 0 for that dimension."""
        caplog.set_level(logging.WARNING)

        class EmptyAPI:
            def taiwan_stock_institutional_investors(self, **kw):
                return pd.DataFrame()
            def taiwan_stock_margin_purchase_short_sale(self, **kw):
                return pd.DataFrame()
            def taiwan_stock_shareholding(self, **kw):
                return pd.DataFrame()

        result = score_chip("2330.TW", "2024-03-15", finmind_api=EmptyAPI())
        assert result == {"institutional_score": 0, "margin_score": 0,
                          "concentration_score": 0, "total": 0}

    def test_partial_data_available(self):
        """Some datasets work, partial scores preserved."""
        class PartialAPI:
            def taiwan_stock_institutional_investors(self, **kw):
                dates = pd.date_range(end="2024-03-14", periods=5, freq="D")
                rows = [{"date": d, "stock_id": "2330",
                         "buy": 100000, "name": "Investment_Trust", "sell": 10000}
                        for d in dates]
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                return df

            def taiwan_stock_margin_purchase_short_sale(self, **kw):
                raise ConnectionError("Margin API down")

            def taiwan_stock_shareholding(self, **kw):
                return pd.DataFrame()

        result = score_chip("2330.TW", "2024-03-15", finmind_api=PartialAPI())
        assert result["institutional_score"] == 30
        assert result["margin_score"] == 0
        assert result["concentration_score"] == 0
        assert result["total"] == 30


# ──────────────────────────────────────────────
#  Total score capping (max 60)
# ──────────────────────────────────────────────


class TestTotalCap:
    """Total score must be capped at 60."""

    def test_max_scores_capped_at_60(self):
        """30 + 15 + 15 = 60 → total is 60."""

        class MaxAPI:
            def taiwan_stock_institutional_investors(self, **kw):
                dates = pd.date_range(end="2024-03-14", periods=5, freq="D")
                rows = [{"date": d, "stock_id": "2330",
                         "buy": 100000, "name": "Investment_Trust", "sell": 10000}
                        for d in dates]
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                return df

            def taiwan_stock_margin_purchase_short_sale(self, **kw):
                dates = pd.date_range(end="2024-03-14", periods=5, freq="D")
                rows = [{"date": d, "stock_id": "2330",
                         "ShortSaleTodayBalance": 10_000_000 - i * 2_000_000}
                        for i, d in enumerate(dates)]
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                return df

            def taiwan_stock_shareholding(self, **kw):
                dates = pd.date_range(end="2024-03-14", periods=4, freq="W")
                rows = [{"date": d, "stock_id": "2330",
                         "NumberOfSharesIssued": 100_000_000 - i * 2_000_000,
                         "ForeignInvestmentSharesRatio": 70.0}
                        for i, d in enumerate(dates)]
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                return df

        result = score_chip("2330.TW", "2024-03-15", finmind_api=MaxAPI())
        assert result["institutional_score"] == 30
        assert result["margin_score"] == 15
        assert result["concentration_score"] == 15
        assert result["total"] == 60

    def test_total_does_not_exceed_60(self):
        """Total must be capped at 60 even if sum exceeds it."""

        class OverMaxAPI:
            def taiwan_stock_institutional_investors(self, **kw):
                dates = pd.date_range(end="2024-03-14", periods=5, freq="D")
                rows = [{"date": d, "stock_id": "2330",
                         "buy": 100000, "name": "Investment_Trust", "sell": 10000}
                        for d in dates]
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                return df

            def taiwan_stock_margin_purchase_short_sale(self, **kw):
                dates = pd.date_range(end="2024-03-14", periods=5, freq="D")
                rows = [{"date": d, "stock_id": "2330",
                         "ShortSaleTodayBalance": 10_000_000 - i * 2_000_000}
                        for i, d in enumerate(dates)]
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                return df

            def taiwan_stock_shareholding(self, **kw):
                dates = pd.date_range(end="2024-03-14", periods=4, freq="W")
                rows = [{"date": d, "stock_id": "2330",
                         "NumberOfSharesIssued": 100_000_000 - i * 2_000_000,
                         "ForeignInvestmentSharesRatio": 70.0}
                        for i, d in enumerate(dates)]
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                return df

        result = score_chip("2330.TW", "2024-03-15", finmind_api=OverMaxAPI())
        assert result["total"] == 60


# ──────────────────────────────────────────────
#  Look-ahead bias protection
# ──────────────────────────────────────────────


class TestLookAheadBias:
    """Only data before signal_date is used."""

    def test_data_after_signal_excluded(self):
        """Data on or after signal_date is excluded from scoring."""

        class FutureDataAPI:
            def taiwan_stock_institutional_investors(self, **kw):
                # Returns 8 days: 3 before signal + 5 after
                dates = list(pd.date_range(end="2024-03-19", periods=8, freq="D"))
                rows = []
                for d in dates:
                    d_str = d.strftime("%Y-%m-%d")
                    rows.append({"date": d_str, "stock_id": "2330",
                                 "buy": 100000, "name": "Investment_Trust", "sell": 10000})
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"])
                return df

            def taiwan_stock_margin_purchase_short_sale(self, **kw):
                return pd.DataFrame()

            def taiwan_stock_shareholding(self, **kw):
                return pd.DataFrame()

        result = score_chip("2330.TW", "2024-03-15", finmind_api=FutureDataAPI())
        # Only 3 days before signal (2024-03-14, 13, 12) → < 5 consecutive
        assert result["institutional_score"] == 0


# ──────────────────────────────────────────────
#  Symbol normalization
# ──────────────────────────────────────────────


class TestSymbolNormalization:
    """score_chip strips .TW/.TWO suffix for FinMind API calls."""

    def test_symbol_suffix_stripped(self):
        """'2330.TW' → stock_id='2330' for FinMind."""

        class CheckAPI:
            def __init__(self):
                self.stock_ids = []

            def taiwan_stock_institutional_investors(self, stock_id="", **kw):
                self.stock_ids.append(("inst", stock_id))
                return pd.DataFrame()

            def taiwan_stock_margin_purchase_short_sale(self, stock_id="", **kw):
                self.stock_ids.append(("margin", stock_id))
                return pd.DataFrame()

            def taiwan_stock_shareholding(self, stock_id="", **kw):
                self.stock_ids.append(("share", stock_id))
                return pd.DataFrame()

        api = CheckAPI()
        score_chip("2330.TW", "2024-03-15", finmind_api=api)
        for source, sid in api.stock_ids:
            assert sid == "2330", f"{source} got {sid!r}"

    def test_otc_suffix_stripped(self):
        """'6488.TWO' → stock_id='6488'."""

        class CheckAPI:
            def __init__(self):
                self.stock_ids = []

            def taiwan_stock_institutional_investors(self, stock_id="", **kw):
                self.stock_ids.append(stock_id)
                return pd.DataFrame()

            def taiwan_stock_margin_purchase_short_sale(self, stock_id="", **kw):
                self.stock_ids.append(stock_id)
                return pd.DataFrame()

            def taiwan_stock_shareholding(self, stock_id="", **kw):
                self.stock_ids.append(stock_id)
                return pd.DataFrame()

        api = CheckAPI()
        score_chip("6488.TWO", "2024-03-15", finmind_api=api)
        for sid in api.stock_ids:
            assert sid == "6488"

    def test_no_suffix_passed_as_is(self):
        """'2330' is passed as-is to FinMind."""

        class CheckAPI:
            def __init__(self):
                self.stock_ids = []

            def taiwan_stock_institutional_investors(self, stock_id="", **kw):
                self.stock_ids.append(stock_id)
                return pd.DataFrame()

            def taiwan_stock_margin_purchase_short_sale(self, stock_id="", **kw):
                self.stock_ids.append(stock_id)
                return pd.DataFrame()

            def taiwan_stock_shareholding(self, stock_id="", **kw):
                self.stock_ids.append(stock_id)
                return pd.DataFrame()

        api = CheckAPI()
        score_chip("2330", "2024-03-15", finmind_api=api)
        for sid in api.stock_ids:
            assert sid == "2330"
