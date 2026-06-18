"""Tests for fundamental_scorer.py — Layer 2 fundamental scoring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from fundamental_scorer import score_fundamentals

# ── helpers ──


def _month_rev(pairs: list) -> pd.DataFrame:
    """Create FinMind-style month revenue DataFrame from (date, revenue) pairs."""
    return pd.DataFrame(
        [{"date": d, "revenue": r, "stock_id": "2330"} for d, r in pairs]
    )


def _fin_stmt(records: list) -> pd.DataFrame:
    """Create FinMind-style financial statement from (date, type, value) records."""
    return pd.DataFrame(
        [{"date": d, "stock_id": "2330", "type": t, "value": v, "origin_name": ""}
         for d, t, v in records]
    )


def _cashflow(records: list) -> pd.DataFrame:
    """Create FinMind-style cash flow statement."""
    return pd.DataFrame(
        [{"date": d, "stock_id": "2330", "type": t, "value": v, "origin_name": ""}
         for d, t, v in records]
    )


def _balance_sheet(records: list) -> pd.DataFrame:
    """Create FinMind-style balance sheet."""
    return pd.DataFrame(
        [{"date": d, "stock_id": "2330", "type": t, "value": v, "origin_name": ""}
         for d, t, v in records]
    )


def _make_api(
    month_revenue: pd.DataFrame | None = None,
    financial_statement: pd.DataFrame | None = None,
    cash_flow: pd.DataFrame | None = None,
    balance_sheet: pd.DataFrame | None = None,
) -> MagicMock:
    """Build a mocked FinMind DataLoader with controlled return values."""
    api = MagicMock()
    api.taiwan_stock_month_revenue.return_value = (
        month_revenue if month_revenue is not None else pd.DataFrame()
    )
    api.taiwan_stock_financial_statement.return_value = (
        financial_statement if financial_statement is not None else pd.DataFrame()
    )
    api.taiwan_stock_cash_flows_statement.return_value = (
        cash_flow if cash_flow is not None else pd.DataFrame()
    )
    api.taiwan_stock_balance_sheet.return_value = (
        balance_sheet if balance_sheet is not None else pd.DataFrame()
    )
    return api


# ═══════════════════════════════════════════════════
# 1. Revenue Growth Scoring
# ═══════════════════════════════════════════════════


class TestRevenueScoring:
    """Revenue Growth (max 30 pts)."""

    def test_strong_growth_plus30(self):
        """Recent 3 months mean YoY > 15% → +30."""
        api = _make_api(
            month_revenue=_month_rev([
                # 2023 months (same period last year)
                ("2023-01-10", 100.0),   # Jan 2023
                ("2023-02-10", 105.0),   # Feb 2023
                ("2023-03-10", 110.0),   # Mar 2023
                # Additional months for 2022 (for YoY of Dec 2023)
                ("2022-12-10", 90.0),
                # 2024 months
                ("2024-01-10", 120.0),   # Jan 2024 → +20%
                ("2024-02-10", 130.0),   # Feb 2024 → +23.8%
                # Dec 2023 revenue for recent 3 months
                ("2023-12-10", 135.0),   # Dec 2023 → +50%
                # Extra data so we have enough points
                ("2023-11-10", 95.0),
                ("2022-11-10", 85.0),
                ("2022-12-10", 90.0),
            ]),
            financial_statement=_fin_stmt([
                # At least some EPS data so other scores don't skew test
                ("2024-02-20", "EPS", 3.0),
                ("2023-11-15", "EPS", 2.5),
                ("2023-08-15", "EPS", 2.0),
                ("2024-02-20", "IncomeAfterTaxes", 100000),
                ("2023-11-15", "IncomeAfterTaxes", 80000),
                ("2023-08-15", "IncomeAfterTaxes", 60000),
                ("2024-02-20", "GrossProfit", 100000),
                ("2023-11-15", "GrossProfit", 80000),
                ("2023-08-15", "GrossProfit", 60000),
                ("2024-02-20", "Revenue", 200000),
                ("2023-11-15", "Revenue", 180000),
                ("2023-08-15", "Revenue", 150000),
                ("2024-02-20", "CashFlowsFromOperatingActivities", 50000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 45000),
                ("2023-08-15", "CashFlowsFromOperatingActivities", 40000),
                ("2023-05-15", "CashFlowsFromOperatingActivities", 35000),
            ]),
            cash_flow=_cashflow([
                ("2024-02-20", "CashFlowsFromOperatingActivities", 50000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 45000),
                ("2023-08-15", "CashFlowsFromOperatingActivities", 40000),
                ("2023-05-15", "CashFlowsFromOperatingActivities", 35000),
            ]),
            balance_sheet=_balance_sheet([
                ("2024-02-20", "TotalDebt", 50000),
                ("2024-02-20", "TotalEquity", 200000),
            ]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["revenue_score"] == 30, f"Expected 30, got {result}"

    def test_moderate_growth_plus15(self):
        """Recent 3 months mean YoY > 5% and ≤15% → +15 (no negative months)."""
        api = _make_api(
            month_revenue=_month_rev([
                ("2023-01-10", 100.0),
                ("2023-02-10", 100.0),
                ("2023-03-10", 100.0),
                ("2022-12-10", 100.0),
                ("2024-01-10", 110.0),    # +10%
                ("2024-02-10", 108.0),    # +8%
                ("2023-12-10", 105.0),    # +5%
                ("2023-11-10", 85.0),
                ("2022-11-10", 80.0),
                ("2022-12-10", 100.0),
            ]),
            financial_statement=_fin_stmt([
                ("2024-02-20", "EPS", 3.0),
                ("2023-11-15", "EPS", 2.5),
                ("2024-02-20", "IncomeAfterTaxes", 100000),
                ("2023-11-15", "IncomeAfterTaxes", 80000),
                ("2024-02-20", "GrossProfit", 100000),
                ("2023-11-15", "GrossProfit", 80000),
                ("2024-02-20", "CashFlowsFromOperatingActivities", 50000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 45000),
            ]),
            cash_flow=_cashflow([
                ("2024-02-20", "CashFlowsFromOperatingActivities", 50000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 45000),
                ("2023-08-15", "CashFlowsFromOperatingActivities", 40000),
                ("2023-05-15", "CashFlowsFromOperatingActivities", 35000),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["revenue_score"] == 15, f"Expected 15, got {result}"

    def test_any_negative_month_minus15(self):
        """If any of the recent 3 months has negative YoY → -15."""
        api = _make_api(
            month_revenue=_month_rev([
                ("2023-01-10", 100.0),
                ("2023-02-10", 100.0),
                ("2023-03-10", 100.0),
                ("2022-12-10", 100.0),
                # Dec 2023 revenue (recent month)
                ("2023-12-10", 110.0),    # +10%
                # Jan 2024 (recent month)
                ("2024-01-10", 115.0),    # +15%
                # Feb 2024 (recent month) — NEGATIVE YoY
                ("2024-02-10", 95.0),     # -5%
                ("2023-11-10", 90.0),
                ("2022-11-10", 80.0),
                ("2022-12-10", 100.0),
            ]),
            financial_statement=_fin_stmt([
                ("2024-02-20", "EPS", 3.0),
                ("2023-11-15", "EPS", 2.5),
                ("2024-02-20", "IncomeAfterTaxes", 100000),
                ("2023-11-15", "IncomeAfterTaxes", 80000),
                ("2024-02-20", "GrossProfit", 100000),
                ("2023-11-15", "GrossProfit", 80000),
                ("2024-02-20", "CashFlowsFromOperatingActivities", 50000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 45000),
            ]),
            cash_flow=_cashflow([
                ("2024-02-20", "CashFlowsFromOperatingActivities", 50000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 45000),
                ("2023-08-15", "CashFlowsFromOperatingActivities", 40000),
                ("2023-05-15", "CashFlowsFromOperatingActivities", 35000),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["revenue_score"] == -15, f"Expected -15, got {result}"

    def test_no_revenue_data(self):
        """No data → 0."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=pd.DataFrame(),
            cash_flow=pd.DataFrame(),
            balance_sheet=pd.DataFrame(),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["revenue_score"] == 0


# ═══════════════════════════════════════════════════
# 2. EPS Trend Scoring
# ═══════════════════════════════════════════════════


class TestEPScoring:
    """EPS Trend (max 25 pts)."""

    def test_eps_positive_and_growing_plus25(self):
        """Recent 2 quarters EPS both positive AND QoQ growing → +25."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([
                # Q2 2023 EPS
                ("2023-08-15", "EPS", 2.0),
                ("2023-08-15", "IncomeAfterTaxes", 80000),
                ("2023-08-15", "GrossProfit", 100000),
                ("2023-08-15", "Revenue", 200000),
                # Q3 2023 EPS (more recent)
                ("2023-11-15", "EPS", 2.5),   # QoQ growing from 2.0
                ("2023-11-15", "IncomeAfterTaxes", 90000),
                ("2023-11-15", "GrossProfit", 110000),
                ("2023-11-15", "Revenue", 220000),
            ]),
            cash_flow=_cashflow([
                ("2023-08-15", "CashFlowsFromOperatingActivities", 40000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 40000),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["eps_score"] == 25, f"Expected 25, got {result}"

    def test_eps_positive_but_not_growing_plus15(self):
        """Recent 2 quarters EPS both positive but not QoQ growing → +15."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([
                # Q3 2023 EPS
                ("2023-11-15", "EPS", 2.5),
                ("2023-11-15", "IncomeAfterTaxes", 90000),
                ("2023-11-15", "GrossProfit", 110000),
                ("2023-11-15", "Revenue", 220000),
                # Q2 2023 EPS (same or higher, meaning not growing QoQ)
                ("2023-08-15", "EPS", 2.5),   # same, not QoQ growing
                ("2023-08-15", "IncomeAfterTaxes", 90000),
                ("2023-08-15", "GrossProfit", 110000),
                ("2023-08-15", "Revenue", 220000),
            ]),
            cash_flow=_cashflow([
                ("2023-08-15", "CashFlowsFromOperatingActivities", 40000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 40000),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["eps_score"] == 15, f"Expected 15, got {result}"

    def test_eps_negative_minus15(self):
        """Most recent quarter EPS negative → -15."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([
                ("2023-11-15", "EPS", -0.5),  # negative
                ("2023-11-15", "IncomeAfterTaxes", -10000),
                ("2023-11-15", "GrossProfit", 50000),
                ("2023-11-15", "Revenue", 200000),
                ("2023-08-15", "EPS", 1.0),
                ("2023-08-15", "IncomeAfterTaxes", 50000),
                ("2023-08-15", "GrossProfit", 80000),
                ("2023-08-15", "Revenue", 180000),
            ]),
            cash_flow=_cashflow([
                ("2023-08-15", "CashFlowsFromOperatingActivities", 40000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 40000),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["eps_score"] == -15, f"Expected -15, got {result}"

    def test_no_eps_data(self):
        """No EPS data → 0."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=pd.DataFrame(),
            cash_flow=pd.DataFrame(),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["eps_score"] == 0


# ═══════════════════════════════════════════════════
# 3. Gross Margin Trend Scoring
# ═══════════════════════════════════════════════════


class TestMarginScoring:
    """Gross Margin Trend (max 15 pts)."""

    def test_margin_flat_or_rising_plus15(self):
        """Recent 2 quarters gross margin flat or rising → +15."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([
                # Q2 2023: GrossProfit=100, Revenue=200 → margin=50%
                ("2023-08-15", "GrossProfit", 100.0),
                ("2023-08-15", "Revenue", 200.0),
                ("2023-08-15", "EPS", 2.0),
                ("2023-08-15", "IncomeAfterTaxes", 80000),
                # Q3 2023: GrossProfit=120, Revenue=220 → margin=54.5% (rising)
                ("2023-11-15", "GrossProfit", 120.0),
                ("2023-11-15", "Revenue", 220.0),
                ("2023-11-15", "EPS", 2.5),
                ("2023-11-15", "IncomeAfterTaxes", 90000),
            ]),
            cash_flow=_cashflow([
                ("2023-08-15", "CashFlowsFromOperatingActivities", 40000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 40000),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["margin_score"] == 15, f"Expected 15, got {result}"

    def test_margin_declining_but_high_plus5(self):
        """Margin declining but still ≥20% → +5."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([
                # Q2 2023: margin=40%
                ("2023-08-15", "GrossProfit", 80.0),
                ("2023-08-15", "Revenue", 200.0),
                ("2023-08-15", "EPS", 2.0),
                ("2023-08-15", "IncomeAfterTaxes", 80000),
                # Q3 2023: margin=30% (declining but ≥20%)
                ("2023-11-15", "GrossProfit", 66.0),
                ("2023-11-15", "Revenue", 220.0),
                ("2023-11-15", "EPS", 2.0),
                ("2023-11-15", "IncomeAfterTaxes", 80000),
            ]),
            cash_flow=_cashflow([
                ("2023-08-15", "CashFlowsFromOperatingActivities", 40000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 40000),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["margin_score"] == 5, f"Expected 5, got {result}"

    def test_margin_declining_and_low_minus10(self):
        """Margin declining and <20% → -10."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([
                # Q2 2023: margin=25%
                ("2023-08-15", "GrossProfit", 50.0),
                ("2023-08-15", "Revenue", 200.0),
                ("2023-08-15", "EPS", 2.0),
                ("2023-08-15", "IncomeAfterTaxes", 80000),
                # Q3 2023: margin=15% (declining and <20%)
                ("2023-11-15", "GrossProfit", 33.0),
                ("2023-11-15", "Revenue", 220.0),
                ("2023-11-15", "EPS", 2.0),
                ("2023-11-15", "IncomeAfterTaxes", 80000),
            ]),
            cash_flow=_cashflow([
                ("2023-08-15", "CashFlowsFromOperatingActivities", 40000),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 40000),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["margin_score"] == -10, f"Expected -10, got {result}"

    def test_no_margin_data(self):
        """No margin data → 0."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=pd.DataFrame(),
            cash_flow=pd.DataFrame(),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["margin_score"] == 0


# ═══════════════════════════════════════════════════
# 4. Cash Flow Quality Scoring
# ═══════════════════════════════════════════════════


class TestCashFlowScoring:
    """Cash Flow Quality (max 30 pts, landmine detection)."""

    def test_cfo_ni_above_80_plus30(self):
        """Recent 4 quarters avg CFO/NI > 80% → +30."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([
                # 4 quarters of NI data
                ("2023-05-15", "IncomeAfterTaxes", 100.0),
                ("2023-05-15", "EPS", 1.0),
                ("2023-05-15", "GrossProfit", 200.0),
                ("2023-05-15", "Revenue", 400.0),
                ("2023-08-15", "IncomeAfterTaxes", 100.0),
                ("2023-08-15", "EPS", 1.0),
                ("2023-08-15", "GrossProfit", 200.0),
                ("2023-08-15", "Revenue", 400.0),
                ("2023-11-15", "IncomeAfterTaxes", 100.0),
                ("2023-11-15", "EPS", 1.0),
                ("2023-11-15", "GrossProfit", 200.0),
                ("2023-11-15", "Revenue", 400.0),
                ("2024-02-20", "IncomeAfterTaxes", 100.0),
                ("2024-02-20", "EPS", 1.0),
                ("2024-02-20", "GrossProfit", 200.0),
                ("2024-02-20", "Revenue", 400.0),
            ]),
            cash_flow=_cashflow([
                # 4 quarters of CFO = 90 each → CFO/NI = 90% > 80%
                ("2023-05-15", "CashFlowsFromOperatingActivities", 90.0),
                ("2023-08-15", "CashFlowsFromOperatingActivities", 90.0),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 90.0),
                ("2024-02-20", "CashFlowsFromOperatingActivities", 90.0),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["cashflow_score"] == 30, f"Expected 30, got {result}"

    def test_cfo_ni_above_50_but_not_80_plus15(self):
        """Recent 4 quarters avg CFO/NI > 50% but ≤80% → +15."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([
                ("2023-05-15", "IncomeAfterTaxes", 100.0),
                ("2023-05-15", "EPS", 1.0),
                ("2023-05-15", "GrossProfit", 200.0),
                ("2023-05-15", "Revenue", 400.0),
                ("2023-08-15", "IncomeAfterTaxes", 100.0),
                ("2023-08-15", "EPS", 1.0),
                ("2023-08-15", "GrossProfit", 200.0),
                ("2023-08-15", "Revenue", 400.0),
                ("2023-11-15", "IncomeAfterTaxes", 100.0),
                ("2023-11-15", "EPS", 1.0),
                ("2023-11-15", "GrossProfit", 200.0),
                ("2023-11-15", "Revenue", 400.0),
                ("2024-02-20", "IncomeAfterTaxes", 100.0),
                ("2024-02-20", "EPS", 1.0),
                ("2024-02-20", "GrossProfit", 200.0),
                ("2024-02-20", "Revenue", 400.0),
            ]),
            cash_flow=_cashflow([
                # CFO = 60 each → CFO/NI = 60% (between 50% and 80%)
                ("2023-05-15", "CashFlowsFromOperatingActivities", 60.0),
                ("2023-08-15", "CashFlowsFromOperatingActivities", 60.0),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 60.0),
                ("2024-02-20", "CashFlowsFromOperatingActivities", 60.0),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["cashflow_score"] == 15, f"Expected 15, got {result}"

    def test_cfo_ni_below_50_minus50(self):
        """CFO/NI < 50% → -50 (landmine penalty)."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([
                ("2023-05-15", "IncomeAfterTaxes", 100.0),
                ("2023-05-15", "EPS", 1.0),
                ("2023-05-15", "GrossProfit", 200.0),
                ("2023-05-15", "Revenue", 400.0),
                ("2023-08-15", "IncomeAfterTaxes", 100.0),
                ("2023-08-15", "EPS", 1.0),
                ("2023-08-15", "GrossProfit", 200.0),
                ("2023-08-15", "Revenue", 400.0),
                ("2023-11-15", "IncomeAfterTaxes", 100.0),
                ("2023-11-15", "EPS", 1.0),
                ("2023-11-15", "GrossProfit", 200.0),
                ("2023-11-15", "Revenue", 400.0),
                ("2024-02-20", "IncomeAfterTaxes", 100.0),
                ("2024-02-20", "EPS", 1.0),
                ("2024-02-20", "GrossProfit", 200.0),
                ("2024-02-20", "Revenue", 400.0),
            ]),
            cash_flow=_cashflow([
                # CFO = 30 each → CFO/NI = 30% < 50%
                ("2023-05-15", "CashFlowsFromOperatingActivities", 30.0),
                ("2023-08-15", "CashFlowsFromOperatingActivities", 30.0),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 30.0),
                ("2024-02-20", "CashFlowsFromOperatingActivities", 30.0),
            ]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["cashflow_score"] == -50, f"Expected -50, got {result}"

    def test_no_cashflow_data(self):
        """No cash flow data → 0."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=pd.DataFrame(),
            cash_flow=pd.DataFrame(),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["cashflow_score"] == 0


# ═══════════════════════════════════════════════════
# 5. Debt Ratio Scoring
# ═══════════════════════════════════════════════════


class TestDebtScoring:
    """Debt Ratio (bonus/penalty)."""

    def test_de_low_plus10(self):
        """D/E < 50% → +10."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([]),
            cash_flow=_cashflow([]),
            balance_sheet=_balance_sheet([
                ("2024-02-20", "TotalDebt", 40.0),
                ("2024-02-20", "TotalEquity", 100.0),  # D/E = 40%
            ]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["debt_score"] == 10, f"Expected 10, got {result}"

    def test_de_high_minus20(self):
        """D/E > 150% → -20."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=_fin_stmt([]),
            cash_flow=_cashflow([]),
            balance_sheet=_balance_sheet([
                ("2024-02-20", "TotalDebt", 200.0),
                ("2024-02-20", "TotalEquity", 100.0),  # D/E = 200%
            ]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["debt_score"] == -20, f"Expected -20, got {result}"

    def test_no_debt_data(self):
        """No D/E data → 0."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=pd.DataFrame(),
            cash_flow=pd.DataFrame(),
            balance_sheet=pd.DataFrame(),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["debt_score"] == 0


# ═══════════════════════════════════════════════════
# 6. Total Score Clamping
# ═══════════════════════════════════════════════════


class TestTotalScore:
    """Total score clamped to [0, 100]."""

    def test_total_capped_at_100(self):
        """When sum exceeds 100, total should be clamped to 100."""
        # Best case: revenue=30, eps=25, margin=15, cashflow=30, debt=10 = 110
        api = _make_api(
            month_revenue=_month_rev([
                ("2023-01-10", 100.0),
                ("2023-02-10", 100.0),
                ("2023-03-10", 100.0),
                ("2022-12-10", 80.0),
                ("2024-01-10", 120.0),    # +20%
                ("2024-02-10", 125.0),    # +25%
                ("2023-12-10", 130.0),    # +30%
                ("2023-11-10", 90.0),
                ("2022-11-10", 80.0),
                ("2022-12-10", 80.0),
            ]),
            financial_statement=_fin_stmt([
                ("2023-08-15", "EPS", 2.0),
                ("2023-08-15", "IncomeAfterTaxes", 100.0),
                ("2023-08-15", "GrossProfit", 200.0),
                ("2023-08-15", "Revenue", 400.0),
                ("2023-11-15", "EPS", 2.5),
                ("2023-11-15", "IncomeAfterTaxes", 100.0),
                ("2023-11-15", "GrossProfit", 220.0),  # rising margin
                ("2023-11-15", "Revenue", 400.0),
                ("2024-02-20", "EPS", 3.0),
                ("2024-02-20", "IncomeAfterTaxes", 100.0),
                ("2024-02-20", "GrossProfit", 220.0),
                ("2024-02-20", "Revenue", 400.0),
                # Q1 2024 — same quarters for cash flow calc
                ("2023-05-15", "IncomeAfterTaxes", 100.0),
            ]),
            cash_flow=_cashflow([
                ("2023-05-15", "CashFlowsFromOperatingActivities", 90.0),
                ("2023-08-15", "CashFlowsFromOperatingActivities", 90.0),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 90.0),
                ("2024-02-20", "CashFlowsFromOperatingActivities", 90.0),
            ]),
            balance_sheet=_balance_sheet([
                ("2024-02-20", "TotalDebt", 40.0),
                ("2024-02-20", "TotalEquity", 100.0),  # D/E=40%
            ]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["total"] == 100, f"Expected 100 (capped), got {result['total']}"

    def test_total_floor_at_0(self):
        """When sum is negative, total should be clamped to 0."""
        # Worst case: revenue=-15, eps=-15, margin=-10, cashflow=-50, debt=-20 = -110
        api = _make_api(
            month_revenue=_month_rev([
                ("2022-12-10", 100.0),
                ("2023-11-10", 80.0),
                ("2022-11-10", 100.0),
                ("2023-01-10", 100.0),
                ("2023-02-10", 100.0),
                ("2023-03-10", 100.0),
                # Negative YoY for recent months
                ("2023-12-10", 90.0),    # < 0% compared to 2022-12=100
                ("2024-01-10", 95.0),    # < 0% compared to 2023-01=100
                ("2024-02-10", 85.0),    # < 0% compared to 2023-02=100
            ]),
            financial_statement=_fin_stmt([
                ("2023-08-15", "EPS", -1.0),
                ("2023-08-15", "IncomeAfterTaxes", -100.0),
                ("2023-08-15", "GrossProfit", 30.0),
                ("2023-08-15", "Revenue", 200.0),
                ("2023-11-15", "EPS", -2.0),
                ("2023-11-15", "IncomeAfterTaxes", -100.0),
                ("2023-11-15", "GrossProfit", 25.0),
                ("2023-11-15", "Revenue", 250.0),
                # More quarters for cash flow calc
                ("2024-02-20", "IncomeAfterTaxes", -100.0),
            ]),
            cash_flow=_cashflow([
                ("2023-05-15", "CashFlowsFromOperatingActivities", 20.0),
                ("2023-08-15", "CashFlowsFromOperatingActivities", 20.0),
                ("2023-11-15", "CashFlowsFromOperatingActivities", 20.0),
                ("2024-02-20", "CashFlowsFromOperatingActivities", 20.0),
            ]),
            balance_sheet=_balance_sheet([
                ("2024-02-20", "TotalDebt", 500.0),
                ("2024-02-20", "TotalEquity", 100.0),  # D/E=500%
            ]),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert result["total"] == 0, f"Expected 0 (floor), got {result['total']}"


# ═══════════════════════════════════════════════════
# 7. Look-ahead Bias Prevention
# ═══════════════════════════════════════════════════


class TestLookAheadBias:
    """Only use data published before signal_date."""

    def test_quarter_after_signal_excluded(self):
        """Quarter reports after signal_date should not be used."""
        api = _make_api(
            month_revenue=pd.DataFrame(),  # no revenue → 0
            financial_statement=_fin_stmt([
                # This quarter's report date is AFTER signal_date 2024-03-15
                ("2024-04-20", "EPS", 5.0),
                ("2024-04-20", "IncomeAfterTaxes", 200000),
                ("2024-04-20", "GrossProfit", 300000),
                ("2024-04-20", "Revenue", 500000),
                # Only old data
                ("2023-08-15", "EPS", 1.0),
                ("2023-08-15", "IncomeAfterTaxes", 50000),
                ("2023-08-15", "GrossProfit", 80000),
                ("2023-08-15", "Revenue", 200000),
            ]),
            cash_flow=_cashflow([]),
            balance_sheet=_balance_sheet([]),
        )
        # With signal_date before the Q4 2023 report, we should only see one quarter of data
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        # Only Q2 2023 data available (one quarter with EPS), no recent 2 quarters → EPS=0
        assert result["eps_score"] == 0, f"Expected 0 (only 1 pre-signal quarter), got {result}"

    def test_revenue_after_signal_excluded(self):
        """Revenue data with date >= signal_date should not be used."""
        api = _make_api(
            month_revenue=_month_rev([
                # March 2024 data reported on 2024-03-10 — before signal
                ("2024-03-10", 100.0),
                # But previous year March data isn't there for YoY comparison
                ("2023-03-10", 100.0),
                # All data is before signal date
                ("2024-01-10", 110.0),  # Jan 2024
                ("2024-02-10", 120.0),  # Feb 2024
                ("2023-01-10", 100.0),
                ("2023-02-10", 100.0),
                ("2023-11-10", 90.0),
                ("2022-11-10", 80.0),
                ("2022-12-10", 85.0),
                ("2023-12-10", 95.0),
            ]),
            financial_statement=_fin_stmt([
                ("2023-08-15", "EPS", 2.0),
                ("2023-08-15", "IncomeAfterTaxes", 80000),
                ("2023-08-15", "GrossProfit", 100000),
                ("2023-08-15", "Revenue", 200000),
            ]),
            cash_flow=_cashflow([]),
            balance_sheet=_balance_sheet([]),
        )
        result = score_fundamentals("2330.TW", "2024-04-01", finmind_api=api)
        # Should still work with data before signal
        assert isinstance(result["revenue_score"], int)


# ═══════════════════════════════════════════════════
# 8. Symbol Parsing
# ═══════════════════════════════════════════════════


class TestSymbolParsing:
    """Symbol parsing handles various formats."""

    def test_twse_symbol(self):
        """2330.TW → stock_id=2330."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=pd.DataFrame(),
            cash_flow=pd.DataFrame(),
            balance_sheet=pd.DataFrame(),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert isinstance(result, dict)

    def test_otc_symbol(self):
        """6488.TWO → stock_id=6488."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=pd.DataFrame(),
            cash_flow=pd.DataFrame(),
            balance_sheet=pd.DataFrame(),
        )
        result = score_fundamentals("6488.TWO", "2024-03-15", finmind_api=api)
        assert isinstance(result, dict)

    def test_bare_symbol(self):
        """2330 (no dot) → stock_id=2330."""
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=pd.DataFrame(),
            cash_flow=pd.DataFrame(),
            balance_sheet=pd.DataFrame(),
        )
        result = score_fundamentals("2330", "2024-03-15", finmind_api=api)
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════
# 9. Return Structure
# ═══════════════════════════════════════════════════


class TestReturnStructure:
    """Return dict contains all expected keys."""

    def test_all_keys_present(self):
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=pd.DataFrame(),
            cash_flow=pd.DataFrame(),
            balance_sheet=pd.DataFrame(),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        assert set(result.keys()) == {
            "revenue_score", "eps_score", "margin_score",
            "cashflow_score", "debt_score", "total",
        }

    def test_all_values_are_ints(self):
        api = _make_api(
            month_revenue=pd.DataFrame(),
            financial_statement=pd.DataFrame(),
            cash_flow=pd.DataFrame(),
            balance_sheet=pd.DataFrame(),
        )
        result = score_fundamentals("2330.TW", "2024-03-15", finmind_api=api)
        for k, v in result.items():
            assert isinstance(v, int), f"{k} should be int, got {type(v)}: {v}"
