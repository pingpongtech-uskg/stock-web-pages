#!/usr/bin/env python3
"""📊 Layer 2 fundamental scoring module.

Standalone module that scores Taiwan stock fundamentals on 5 dimensions:
1.  Revenue Growth (max 30 pts)
2.  EPS Trend (max 25 pts)
3.  Gross Margin Trend (max 15 pts)
4.  Cash Flow Quality (max 30 pts) — landmine detection
5.  Debt Ratio (bonus/penalty, no cap)

Total = sum(all 5), clamped to [0, 100].

Data sources
────────────
Primary:  FinMind API (TaiwanStockMonthRevenue / TaiwanStockFinancialStatements /
          TaiwanStockCashFlowsStatement / TaiwanStockBalanceSheet)
Fallback: yfinance (converted to FinMind-compatible DataFrame format)

Look-ahead bias prevention
──────────────────────────
Every data point is filtered to date < signal_date before any scoring.
"""

from __future__ import annotations

import os
import re
import warnings

warnings.filterwarnings("ignore")

# ─── FinMind token loading ───


def _load_finmind_token() -> str | None:
    """Load FinMind token from existing scripts (same pattern as daily_monitor.py)."""
    src_files = [
        os.path.join(os.path.dirname(__file__), "scripts", "download_otc_prices.py"),
    ]
    for fp in src_files:
        if os.path.exists(fp):
            with open(fp) as f:
                content = f.read()
            for m in re.finditer(
                r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", content
            ):
                return m.group()
    return None


# ─── Safe API helpers ───


def _filter_before(df, signal_date: str):
    """Filter rows where ``date`` is strictly before *signal_date*."""
    if df is None or len(df) == 0:
        return None
    filtered = df[df["date"] < signal_date]
    return filtered if len(filtered) > 0 else None


def _safe_fetch(api, method_name: str, stock_id: str, **kwargs):
    """Call *method_name* on *api*, returning the result or ``None`` on any error."""
    if api is None:
        return None
    try:
        method = getattr(api, method_name)
        return method(stock_id=stock_id, **kwargs)
    except Exception:
        return None


# ─── yfinance fallback ───


def _yf_ticker_symbol(symbol: str) -> str:
    """Convert a bare stock code (2330) to a yfinance-compatible ticker."""
    # Try to determine suffix from the exchange
    code = symbol.split(".")[0] if "." in symbol else symbol
    # Default: TWSE for 1xxx, OTC for 2xxx+, but check both if uncertain
    first_digit = int(code[0])
    if first_digit == 1:
        return f"{code}.TW"
    return f"{code}.TWO"


def _yf_to_fm_style(yf_data, field_map, stock_id: str):
    """Convert a yfinance DataFrame (columns=dates, rows=fields) into FinMind-style rows.

    Returns a list of dicts with keys ``date``, ``stock_id``, ``type``, ``value``.
    """
    if yf_data is None or yf_data.empty:
        return None
    import pandas as pd

    rows = []
    for col in yf_data.columns:
        date_str = str(col.date()) if hasattr(col, "date") else str(col)[:10]
        for yf_field, fm_field in field_map.items():
            if yf_field in yf_data.index:
                val = yf_data.loc[yf_field, col]
                if pd.notna(val) and val != 0:
                    rows.append(
                        {
                            "date": date_str,
                            "stock_id": stock_id,
                            "type": fm_field,
                            "value": float(val),
                        }
                    )
    return rows if rows else None


def _yf_financials(symbol: str):
    """Fetch quarterly financials from yfinance, return FinMind-style list of dicts."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(_yf_ticker_symbol(symbol))
        q = ticker.quarterly_financials
        if q is None or q.empty:
            return None
        field_map = {
            "Total Revenue": "Revenue",
            "Gross Profit": "GrossProfit",
            "Operating Income": "OperatingIncome",
            "Pretax Income": "PreTaxIncome",
            "Net Income": "IncomeAfterTaxes",
            "Basic EPS": "EPS",
        }
        return _yf_to_fm_style(q, field_map, symbol)
    except Exception:
        return None


def _yf_cashflow(symbol: str):
    """Fetch quarterly cash flow from yfinance, return FinMind-style list."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(_yf_ticker_symbol(symbol))
        cf = ticker.cashflow
        if cf is None or cf.empty:
            return None
        field_map = {
            "Operating Cash Flow": "CashFlowsFromOperatingActivities",
            "Free Cash Flow": "FreeCashFlow",
        }
        return _yf_to_fm_style(cf, field_map, symbol)
    except Exception:
        return None


def _yf_balance_sheet(symbol: str):
    """Fetch quarterly balance sheet from yfinance, return FinMind-style list."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(_yf_ticker_symbol(symbol))
        bs = ticker.balance_sheet
        if bs is None or bs.empty:
            return None
        field_map = {
            "Total Debt": "TotalDebt",
            "Total Stockholder Equity": "TotalEquity",
        }
        return _yf_to_fm_style(bs, field_map, symbol)
    except Exception:
        return None


def _yf_month_revenue(symbol: str):
    """Revenue fallback: yfinance doesn't have monthly revenue, so return None."""
    # yfinance only has quarterly revenue; monthly revenue is FinMind-specific.
    return None


# ─── Data fetching layer ───


def _fetch_all(api, stock_id: str, signal_date: str):
    """Fetch all four data sources (FinMind primary, yfinance fallback).

    Returns (*rev*, *fin*, *cf*, *bs*) — each is a DataFrame or ``None``.
    """
    import pandas as pd

    # 1. Monthly revenue
    rev = _safe_fetch(api, "taiwan_stock_month_revenue", stock_id)
    if rev is None or len(rev) == 0:
        rev_rows = _yf_month_revenue(stock_id)
        rev = pd.DataFrame(rev_rows) if rev_rows else None

    # 2. Financial statements
    fin = _safe_fetch(api, "taiwan_stock_financial_statement", stock_id)
    if fin is None or len(fin) == 0:
        fin_rows = _yf_financials(stock_id)
        fin = pd.DataFrame(fin_rows) if fin_rows else None

    # 3. Cash flow
    cf = _safe_fetch(api, "taiwan_stock_cash_flows_statement", stock_id)
    if cf is None or len(cf) == 0:
        cf_rows = _yf_cashflow(stock_id)
        cf = pd.DataFrame(cf_rows) if cf_rows else None

    # 4. Balance sheet
    bs = _safe_fetch(api, "taiwan_stock_balance_sheet", stock_id)
    if bs is None or len(bs) == 0:
        bs_rows = _yf_balance_sheet(stock_id)
        bs = pd.DataFrame(bs_rows) if bs_rows else None

    # Apply look-ahead filter
    rev_f = _filter_before(rev, signal_date)
    fin_f = _filter_before(fin, signal_date)
    cf_f = _filter_before(cf, signal_date)
    bs_f = _filter_before(bs, signal_date)

    return rev_f, fin_f, cf_f, bs_f


# ═══════════════════════════════════════════════════════════════
# Scoring dimensions
# ═══════════════════════════════════════════════════════════════


def _score_revenue(rev_df, _signal_date: str) -> int:
    """Revenue Growth (max 30 pts)."""
    if rev_df is None or len(rev_df) < 6:
        return 0

    rev_df = rev_df.sort_values("date")
    recent = rev_df.tail(3)

    yoy_values: list[float] = []
    for _, row in recent.iterrows():
        d = row["date"]
        yr_ago = f"{int(d[:4]) - 1}-{d[5:]}"
        prev = rev_df[rev_df["date"] == yr_ago]
        if len(prev) > 0:
            cur_r = float(row["revenue"])
            prev_r = float(prev.iloc[0]["revenue"])
            if prev_r > 0:
                yoy = (cur_r - prev_r) / prev_r * 100
                yoy_values.append(yoy)

    if len(yoy_values) < 3:
        return 0

    # Any month negative → penalty
    if any(y < 0 for y in yoy_values):
        return -15

    mean_yoy = sum(yoy_values) / len(yoy_values)
    if mean_yoy > 15:
        return 30
    if mean_yoy > 5:
        return 15
    return 0


def _score_eps(df_fin, _signal_date: str) -> int:
    """EPS Trend (max 25 pts).

    Looks at the most recent 2 quarters with EPS data.
    """
    if df_fin is None or len(df_fin) == 0:
        return 0

    eps = df_fin[df_fin["type"] == "EPS"].copy()
    if len(eps) < 2:
        return 0

    eps = eps.sort_values("date")
    recent_eps = eps.tail(2)

    eps_values = [float(v) for v in recent_eps["value"].values]

    # Most recent quarter negative
    if eps_values[-1] < 0:
        return -15

    # Both positive AND QoQ growing
    if all(v > 0 for v in eps_values) and eps_values[-1] > eps_values[-2]:
        return 25

    # Both positive
    if all(v > 0 for v in eps_values):
        return 15

    return 0


def _score_margin(df_fin, _signal_date: str) -> int:
    """Gross Margin Trend (max 15 pts).

    Compares gross margin over the most recent 2 quarters.
    """
    if df_fin is None or len(df_fin) == 0:
        return 0

    gp = df_fin[df_fin["type"] == "GrossProfit"].copy()
    rev = df_fin[df_fin["type"] == "Revenue"].copy()

    if len(gp) < 2 or len(rev) < 2:
        return 0

    gp = gp.sort_values("date")
    rev = rev.sort_values("date")

    # Build date → value lookup
    gp_by_date = dict(zip(gp["date"].values, gp["value"].values))
    rev_by_date = dict(zip(rev["date"].values, rev["value"].values))

    common = sorted(set(gp_by_date) & set(rev_by_date))
    if len(common) < 2:
        return 0

    recent_two = common[-2:]
    margins = [
        float(gp_by_date[d]) / float(rev_by_date[d]) * 100
        for d in recent_two
        if float(rev_by_date[d]) > 0
    ]
    if len(margins) < 2:
        return 0

    # Flat or rising
    if margins[-1] >= margins[-2]:
        return 15

    # Declining but ≥ 20 %
    if margins[-1] >= 20:
        return 5

    # Declining and < 20 %
    return -10


def _score_cashflow(df_fin, df_cf, _signal_date: str) -> int:
    """Cash Flow Quality (max 30 pts, landmine detection).

    Averages CFO/NI ratio over the most recent 4 quarters with both data points.
    """
    if df_fin is None or df_cf is None:
        return 0
    if len(df_fin) == 0 or len(df_cf) == 0:
        return 0

    ni = df_fin[df_fin["type"] == "IncomeAfterTaxes"].copy()
    cfo = df_cf[df_cf["type"] == "CashFlowsFromOperatingActivities"].copy()

    if len(ni) == 0 or len(cfo) == 0:
        return 0

    ni_by_date = dict(zip(ni["date"].values, ni["value"].values))
    cfo_by_date = dict(zip(cfo["date"].values, cfo["value"].values))

    common = sorted(set(ni_by_date) & set(cfo_by_date))
    if len(common) == 0:
        return 0

    # Up to 4 most recent quarters
    recent = common[-4:]
    ratios: list[float] = []
    for d in recent:
        ni_val = float(ni_by_date[d])
        if ni_val > 0:  # Skip quarters with negative NI (ratio would be misleading)
            ratio = float(cfo_by_date[d]) / ni_val * 100
            ratios.append(ratio)

    if len(ratios) == 0:
        return 0

    avg = sum(ratios) / len(ratios)

    if avg > 80:
        return 30
    if avg > 50:
        return 15
    return -50


def _score_debt(df_bs, _signal_date: str) -> int:
    """Debt Ratio (bonus/penalty, no cap).

    Uses the most recent D/E ratio from balance sheet.
    """
    if df_bs is None or len(df_bs) == 0:
        return 0

    debt = df_bs[df_bs["type"] == "TotalDebt"]
    equity = df_bs[df_bs["type"] == "TotalEquity"]

    if len(debt) == 0 or len(equity) == 0:
        return 0

    debt_by_date = dict(zip(debt["date"].values, debt["value"].values))
    equity_by_date = dict(zip(equity["date"].values, equity["value"].values))

    common = sorted(set(debt_by_date) & set(equity_by_date))
    if len(common) == 0:
        return 0

    latest = common[-1]
    d = float(debt_by_date[latest])
    e = float(equity_by_date[latest])

    if e <= 0:
        return 0

    de = d / e * 100

    if de < 50:
        return 10
    if de > 150:
        return -20
    return 0


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════


def score_fundamentals(
    symbol: str,
    signal_date: str,
    finmind_api=None,
) -> dict[str, int]:
    """Score a Taiwan stock's fundamentals on 5 dimensions.

    Parameters
    ----------
    symbol : str
        Stock symbol, e.g. ``"2330.TW"``, ``"6488.TWO"``, or bare ``"2330"``.
    signal_date : str
        Signal trigger date in ``"YYYY-MM-DD"`` format.  **Only** financial data
        published strictly before this date is used (look-ahead bias prevention).
    finmind_api : DataLoader, optional
        Pre-authenticated FinMind ``DataLoader`` instance.  If ``None`` the module
        tries to load the token from existing scripts automatically.

    Returns
    -------
    dict
        Keys: ``revenue_score``, ``eps_score``, ``margin_score``,
        ``cashflow_score``, ``debt_score``, ``total``.
        Each value is an ``int``; ``total`` is clamped to ``[0, 100]``.
    """
    stock_id = symbol.split(".")[0] if "." in symbol else symbol

    # Auto-authenticate if no api was passed
    api = finmind_api
    if api is None:
        token = _load_finmind_token()
        if token:
            from FinMind.data import DataLoader

            api = DataLoader()
            api.login_by_token(api_token=token)

    # Fetch all data sources (with yfinance fallback)
    rev_df, fin_df, cf_df, bs_df = _fetch_all(api, stock_id, signal_date)

    # Score each dimension
    revenue_score = _score_revenue(rev_df, signal_date)
    eps_score = _score_eps(fin_df, signal_date)
    margin_score = _score_margin(fin_df, signal_date)
    cashflow_score = _score_cashflow(fin_df, cf_df, signal_date)
    debt_score = _score_debt(bs_df, signal_date)

    total = revenue_score + eps_score + margin_score + cashflow_score + debt_score
    total = max(0, min(100, total))

    return {
        "revenue_score": revenue_score,
        "eps_score": eps_score,
        "margin_score": margin_score,
        "cashflow_score": cashflow_score,
        "debt_score": debt_score,
        "total": total,
    }
