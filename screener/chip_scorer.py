"""🏭 Layer 3 chip/capital flow scoring module.

Standalone module ``score_chip(symbol, signal_date, finmind_api=None)``
that scores a stock on institutional buying, margin trading, and
shareholder concentration.  Designed for the tw-stock-monitor backtest
pipeline — graceful degradation when FinMind data is unavailable.

FinMind API methods used (register-level token compatible):
    - *taiwan_stock_institutional_investors*   (Investment_Trust / Foreign_Investor)
    - *taiwan_stock_margin_purchase_short_sale* (ShortSaleTodayBalance)
    - *taiwan_stock_shareholding*               (NumberOfSharesIssued, ForeignInvestmentSharesRatio)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────
MAX_TOTAL = 60
MAX_INSTITUTIONAL = 30
MAX_MARGIN = 15
MAX_CONCENTRATION = 15

# ── Token loading ─────────────────────────────────────────────────

_FINMIND_TOKEN: str | None = None


def _load_finmind_token() -> str | None:
    """Read the FinMind JWT token from ``scripts/download_otc_prices.py``.

    Uses the same regex pattern as ``daily_monitor.load_finmind_token()``
    and ``backtest_main._try_setup_finmind()``.
    """
    global _FINMIND_TOKEN
    if _FINMIND_TOKEN:
        return _FINMIND_TOKEN

    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, "scripts", "download_otc_prices.py"),
        os.path.join(script_dir, "scripts", "full_scoring_v2.py"),
    ]
    pattern = re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
    for fp in candidates:
        if os.path.exists(fp):
            with open(fp) as fh:
                content = fh.read()
            for match in pattern.finditer(content):
                _FINMIND_TOKEN = match.group()
                return _FINMIND_TOKEN
    logger.warning("FinMind token not found in any source file")
    return None


def _create_finmind_api():
    """Create a FinMind ``DataLoader`` instance logged in with the project token.

    Returns ``None`` if token is missing or login fails.
    """
    token = _load_finmind_token()
    if token is None:
        return None
    try:
        from FinMind.data import DataLoader

        api = DataLoader()
        api.login_by_token(api_token=token)
        return api
    except Exception as exc:
        logger.warning("Failed to create FinMind API: %s", exc)
        return None


# ── Symbol normalization ──────────────────────────────────────────


def _normalize_symbol(symbol: str) -> str:
    """Strip ``.TW`` / ``.TWO`` suffix for FinMind API calls."""
    for suffix in (".TW", ".TWO"):
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)]
    return symbol


# ── Generic API caller ────────────────────────────────────────────


def _fetch_data(
    api: Any,
    method_name: str,
    stock_id: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Safely call *method_name* on *api* and return a DataFrame.

    Returns an empty DataFrame on any error.
    """
    method = getattr(api, method_name, None)
    if method is None:
        logger.warning("FinMind API has no method %r", method_name)
        return pd.DataFrame()
    try:
        df = method(stock_id=stock_id, start_date=start_date, end_date=end_date)
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame()
        return df
    except Exception as exc:
        logger.warning("FinMind %s(%s) failed: %s", method_name, stock_id, exc)
        return pd.DataFrame()


# ── Date helpers ──────────────────────────────────────────────────


def _dates_before(df: pd.DataFrame, before_date: str) -> pd.DataFrame:
    """Filter rows where ``date`` column < *before_date* (no look-ahead)."""
    cutoff = pd.Timestamp(before_date)
    if "date" not in df.columns:
        return df
    date_col = pd.to_datetime(df["date"])
    return df[date_col < cutoff].copy()


# ── 1. Institutional Buying Score ─────────────────────────────────


def _max_consecutive_net_buys(df: pd.DataFrame) -> int:
    """Return the longest streak of consecutive trading days with net buy > 0.

    ``df`` must be sorted by ``date`` and have a ``net_buy`` column.
    """
    if df.empty:
        return 0
    net_buy = (df["net_buy"] > 0).astype(int).values
    max_streak = 0
    current = 0
    for val in net_buy:
        if val:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def _score_institutional(df: pd.DataFrame, symbol: str, before_date: str) -> int:
    """Score institutional buying (max 30).

    Priority:
        1. Investment_Trust net buy ≥5 consecutive days → +30
        2. Foreign_Investor net buy ≥3 consecutive days → +15
        3. Otherwise → 0

    ``df`` is the raw DataFrame from FinMind (columns: date, stock_id, buy, name, sell).
    The function handles filtering to data before *before_date* internally.
    """
    if df.empty:
        return 0

    # Filter look-ahead
    df = _dates_before(df, before_date)
    if df.empty:
        return 0

    # Add net_buy column
    df = df.copy()
    df["net_buy"] = df["buy"] - df["sell"]

    # ── Rule 1: Investment_Trust (投信) 5 consecutive — highest priority ──
    trust = df[df["name"] == "Investment_Trust"].sort_values("date")
    if not trust.empty and len(trust) >= 5:
        if _max_consecutive_net_buys(trust) >= 5:
            return MAX_INSTITUTIONAL

    # ── Rule 2: Foreign_Investor (外資) 3 consecutive — medium priority ──
    foreign = df[df["name"] == "Foreign_Investor"].sort_values("date")
    if not foreign.empty and len(foreign) >= 3:
        if _max_consecutive_net_buys(foreign) >= 3:
            return 15

    return 0


# ── 2. Margin Trading Score ───────────────────────────────────────


def _score_margin(df: pd.DataFrame, symbol: str, before_date: str) -> int:
    """Score margin trading (max 15).

    Rules (check ShortSaleTodayBalance over 5 trading days):
        - Dropped >20% → +15
        - Otherwise → 0
    """
    if df.empty:
        return 0

    df = _dates_before(df, before_date)
    if df.empty:
        return 0

    col = "ShortSaleTodayBalance"
    if col not in df.columns:
        logger.warning("Margin data missing column %r", col)
        return 0

    df = df.sort_values("date").dropna(subset=[col])
    if len(df) < 5:
        return 0

    oldest = df[col].iloc[0]
    newest = df[col].iloc[-1]

    # >20% drop: (newest - oldest) / oldest < -0.20
    if oldest > 0 and (newest - oldest) / oldest < -0.20:
        return MAX_MARGIN

    return 0


# ── 3. Shareholder Concentration Score ────────────────────────────


def _score_concentration(df: pd.DataFrame, symbol: str, before_date: str) -> int:
    """Score shareholder concentration (max 15).

    Rules (check over 4+ data points):
        - NumberOfSharesIssued decreasing over the period → +15
        - ForeignInvestmentSharesRatio rising → +10
        - Otherwise → 0

    The ideal dataset (TaiwanStockHoldingSharesPer with level/shareholders/percent)
    requires a paid FinMind subscription, so we use TaiwanStockShareholding as a proxy.
    """
    if df.empty:
        return 0

    df = _dates_before(df, before_date)
    if df.empty:
        return 0

    df = df.sort_values("date")
    if len(df) < 4:
        return 0

    has_shares = "NumberOfSharesIssued" in df.columns
    has_ratio = "ForeignInvestmentSharesRatio" in df.columns

    if not has_shares and not has_ratio:
        logger.warning("Shareholding data has neither NumberOfSharesIssued nor ForeignInvestmentSharesRatio")
        return 0

    # ── Rule 1: Total shares decreasing → proxy for custodial account decrease ──
    if has_shares:
        shares_series = df["NumberOfSharesIssued"].dropna()
        if len(shares_series) >= 4:
            first, last = shares_series.iloc[0], shares_series.iloc[-1]
            if last < first:  # decreasing over time
                return MAX_CONCENTRATION

    # ── Rule 2: Foreign ratio rising → proxy for major holder ratio rising ──
    if has_ratio:
        ratio_series = df["ForeignInvestmentSharesRatio"].dropna()
        if len(ratio_series) >= 4:
            first, last = ratio_series.iloc[0], ratio_series.iloc[-1]
            if last > first:  # rising over time
                return 10

    return 0


# ── Public API ─────────────────────────────────────────────────────


def score_chip(
    symbol: str,
    signal_date: str,
    finmind_api: Any = None,
) -> dict[str, int]:
    """Score a stock's chip / capital flow dynamics.

    Parameters
    ----------
    symbol : str
        e.g. ``"2330.TW"``, ``"2330"``, or ``"6488.TWO"``.
    signal_date : str
        ``"YYYY-MM-DD"`` — only data published **before** this date is used.
    finmind_api : optional
        A FinMind ``DataLoader`` instance.  If ``None``, one is created
        automatically using the project token from ``scripts/download_otc_prices.py``.

    Returns
    -------
    dict
        ``{"institutional_score": int, "margin_score": int,
          "concentration_score": int, "total": int}``

    Graceful degradation: any missing/unavailable data returns 0 for that
    sub-score with a logged warning.  Never raises.
    """
    api = finmind_api
    if api is None:
        api = _create_finmind_api()
        if api is None:
            logger.warning(
                "No FinMind API available — all chip scores = 0 for %s on %s",
                symbol,
                signal_date,
            )
            return _zero_result()

    stock_id = _normalize_symbol(symbol)
    # Request 60 days of history so we have enough for all look-back windows
    start = _start_date(signal_date, lookback_days=90)

    # ── 1. Institutional ─────────────────────────────────────────
    try:
        inst_df = _fetch_data(
            api,
            "taiwan_stock_institutional_investors",
            stock_id, start, signal_date,
        )
        inst_score = _score_institutional(inst_df, stock_id, signal_date)
    except Exception as exc:
        logger.warning("Institutional scoring failed for %s: %s", symbol, exc)
        inst_score = 0

    # ── 2. Margin ────────────────────────────────────────────────
    try:
        margin_df = _fetch_data(
            api,
            "taiwan_stock_margin_purchase_short_sale",
            stock_id, start, signal_date,
        )
        margin_score = _score_margin(margin_df, stock_id, signal_date)
    except Exception as exc:
        logger.warning("Margin scoring failed for %s: %s", symbol, exc)
        margin_score = 0

    # ── 3. Shareholder Concentration ──────────────────────────────
    try:
        share_df = _fetch_data(
            api,
            "taiwan_stock_shareholding",
            stock_id, start, signal_date,
        )
        conc_score = _score_concentration(share_df, stock_id, signal_date)
    except Exception as exc:
        logger.warning("Concentration scoring failed for %s: %s", symbol, exc)
        conc_score = 0

    # ── Total (capped) ────────────────────────────────────────────
    raw_total = inst_score + margin_score + conc_score
    total = min(raw_total, MAX_TOTAL)

    return {
        "institutional_score": inst_score,
        "margin_score": margin_score,
        "concentration_score": conc_score,
        "total": total,
    }


def _start_date(signal_date: str, lookback_days: int = 90) -> str:
    """Return an ISO date *lookback_days* before *signal_date*."""
    dt = datetime.strptime(signal_date, "%Y-%m-%d")
    from datetime import timedelta

    return (dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")


def _zero_result() -> dict[str, int]:
    """Return a fully-zeroed result dict."""
    return {
        "institutional_score": 0,
        "margin_score": 0,
        "concentration_score": 0,
        "total": 0,
    }
