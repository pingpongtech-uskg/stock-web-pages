"""Best-effort Yahoo/yfinance adapters used by the offline publisher.

The browser never calls Yahoo.  The publisher prefers the yfinance package so
its explicit ``auto_adjust=False`` / ``Adj Close`` contract is visible in the
code.  A small stdlib chart fallback keeps refreshes useful in environments
where installing yfinance is temporarily impossible; fallback rows are tagged
with their source and are never silently presented as FinMind data.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable


YFINANCE_PRICE_SOURCE = "yfinance:Ticker.history(Adj Close)"
YFINANCE_FUNDAMENTAL_SOURCE = "yfinance:Ticker.financials/cashflow/balance_sheet"
YAHOO_CHART_SOURCE = "YahooFinance:chart.adjclose (yfinance-compatible fallback)"
USER_AGENT = "taiwan-stock-research/0.2 (static snapshot publisher)"


def yahoo_symbol(code: str, market: str = "TWSE") -> str:
    """Map the two Taiwan exchange suffixes used by Yahoo Finance."""

    suffix = ".TWO" if market == "TPEx" else ".TW"
    return f"{str(code).strip().upper()}{suffix}"


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date_text(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "")
    if not text:
        return None
    # Pandas Timestamp and timezone-aware ISO strings both work through the
    # first ten characters; invalid values are discarded by the caller.
    text = text[:10]
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _column(row: Any, name: str) -> Any:
    """Read a yfinance row with either flat or one-ticker MultiIndex columns."""

    try:
        value = row[name]
        if hasattr(value, "iloc") and len(value) == 1:
            return value.iloc[0]
        return value
    except (KeyError, IndexError, TypeError):
        pass
    try:
        for key in row.index:
            if str(key).split("|")[-1].split("'")[-1] == name or str(key).endswith(name):
                return row[key]
    except (AttributeError, KeyError, TypeError):
        pass
    return None


def _history_from_yfinance(
    code: str,
    market: str,
    start: date,
    end: date,
    *,
    timeout: float,
) -> list[dict[str, Any]]:
    import yfinance as yf  # type: ignore[import-not-found]

    ticker = yf.Ticker(yahoo_symbol(code, market))
    # auto_adjust=False is intentional: Adj Close is then present and the raw
    # close stays available for a separate quote/execution series.
    try:
        history = ticker.history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=True,
            repair=True,
            timeout=timeout,
        )
    except TypeError:
        # Older yfinance releases may not expose repair or timeout on history.
        history = ticker.history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
            actions=True,
        )
    rows: list[dict[str, Any]] = []
    try:
        iterator: Iterable[tuple[Any, Any]] = history.iterrows()
    except AttributeError:
        return rows
    for index, row in iterator:
        day = _date_text(index)
        adjusted = _number(_column(row, "Adj Close"))
        close = _number(_column(row, "Close"))
        volume = _number(_column(row, "Volume"))
        if day is None or adjusted is None or adjusted <= 0:
            continue
        rows.append(
            {
                "date": day,
                "close": close,
                "adjustedClose": adjusted,
                "volume": volume,
                "source": YFINANCE_PRICE_SOURCE,
            }
        )
    return rows


def _history_from_chart(
    code: str,
    market: str,
    start: date,
    end: date,
    *,
    timeout: float,
) -> list[dict[str, Any]]:
    params = {
        "period1": str(int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp())),
        "period2": str(int(datetime((end + timedelta(days=1)).year, (end + timedelta(days=1)).month, (end + timedelta(days=1)).day, tzinfo=timezone.utc).timestamp())),
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol(code, market))}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    result = (payload.get("chart") or {}).get("result") or []
    if not result or not isinstance(result[0], dict):
        return []
    chart = result[0]
    timestamps = chart.get("timestamp") or []
    quote = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
    adjusted_series = ((chart.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or []
    close_series = quote.get("close") or []
    volume_series = quote.get("volume") or []
    rows: list[dict[str, Any]] = []
    for index, timestamp in enumerate(timestamps):
        try:
            day = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            continue
        adjusted = _number(adjusted_series[index] if index < len(adjusted_series) else None)
        if adjusted is None or adjusted <= 0:
            continue
        rows.append(
            {
                "date": day,
                "close": _number(close_series[index] if index < len(close_series) else None),
                "adjustedClose": adjusted,
                "volume": _number(volume_series[index] if index < len(volume_series) else None),
                "source": YAHOO_CHART_SOURCE,
            }
        )
    return rows


def fetch_adjusted_history(
    code: str,
    market: str,
    start: date,
    end: date,
    *,
    timeout: float = 10.0,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Return rows, source reference, and an optional human-readable error."""

    markets = [market] if market in {"TWSE", "TPEx"} else ["TWSE", "TPEx"]
    errors: list[str] = []
    # The chart endpoint is a single lightweight public request and is the
    # normal path for a 100-symbol daily universe.  yfinance remains the
    # fallback for environments where chart access is unavailable.
    for candidate_market in markets:
        try:
            rows = _history_from_chart(code, candidate_market, start, end, timeout=timeout)
            if rows:
                return rows, YAHOO_CHART_SOURCE, None
        except Exception as exc:
            errors.append(f"{candidate_market} chart {type(exc).__name__}: {exc}")
    for candidate_market in markets:
        try:
            rows = _history_from_yfinance(code, candidate_market, start, end, timeout=timeout)
            if rows:
                return rows, YFINANCE_PRICE_SOURCE, None
        except Exception as exc:  # best effort; publisher keeps the raw series
            errors.append(f"{candidate_market} yfinance {type(exc).__name__}: {exc}")
        else:
            errors.append(f"{candidate_market} yfinance returned no adjusted rows")
    return [], None, "; ".join(errors)


def _frame_value(frame: Any, aliases: tuple[str, ...], column: Any) -> float | None:
    """Read one statement row from a pandas DataFrame without importing pandas."""

    if frame is None:
        return None
    try:
        index_values = list(frame.index)
        match = next((item for item in index_values if str(item).strip().lower() in {alias.lower() for alias in aliases}), None)
        if match is None:
            # Yahoo occasionally adds punctuation or spaces to a statement key.
            match = next((item for item in index_values if any(alias.lower() in str(item).strip().lower() for alias in aliases)), None)
        if match is None:
            return None
        value = frame.loc[match, column]
    except (AttributeError, KeyError, IndexError, TypeError):
        return None
    return _number(value)


def _latest_columns(frame: Any) -> list[Any]:
    try:
        values = list(frame.columns)
    except (AttributeError, TypeError):
        return []
    return sorted(values, key=lambda item: str(item), reverse=True)


def fetch_fundamental_proxies(
    code: str,
    market: str,
    *,
    timeout: float = 10.0,
) -> tuple[dict[str, Any], str | None, str | None]:
    """Fetch only derived latest-period metrics from yfinance statements."""

    try:
        import yfinance as yf  # type: ignore[import-not-found]

        markets = [market] if market in {"TWSE", "TPEx"} else ["TWSE", "TPEx"]
        errors: list[str] = []
        income = cashflow = balance = None
        for candidate_market in markets:
            try:
                ticker = yf.Ticker(yahoo_symbol(code, candidate_market))
                income = getattr(ticker, "financials", None)
                if income is None:
                    income = ticker.get_income_stmt(freq="yearly")
                cashflow = getattr(ticker, "cashflow", None)
                if cashflow is None:
                    cashflow = ticker.get_cash_flow(freq="yearly")
                balance = getattr(ticker, "balance_sheet", None)
                if balance is None:
                    balance = ticker.get_balance_sheet(freq="yearly")
                if income is not None and len(getattr(income, "columns", [])):
                    break
            except Exception as exc:
                errors.append(f"{candidate_market} {type(exc).__name__}: {exc}")
        if income is None:
            return {}, YFINANCE_FUNDAMENTAL_SOURCE, "; ".join(errors) or "yfinance returned no income statement"
        columns = _latest_columns(income)
        if not columns:
            return {}, YFINANCE_FUNDAMENTAL_SOURCE, "yfinance returned no annual income statement"
        latest = columns[0]
        revenue = _frame_value(income, ("Total Revenue", "Operating Revenue"), latest)
        net_income = _frame_value(income, ("Net Income", "Net Income Common Stockholders"), latest)
        operating_income = _frame_value(income, ("Operating Income",), latest)
        ebitda = _frame_value(income, ("EBITDA", "Normalized EBITDA"), latest)
        operating_cashflow = _frame_value(cashflow, ("Operating Cash Flow", "Total Cash From Operating Activities"), latest)
        equity = _frame_value(balance, ("Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"), latest)
        cash = _frame_value(balance, ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents", "Cash Financial"), latest)
        debt = _frame_value(balance, ("Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"), latest)
        net_debt_to_ebitda = None
        if debt is not None and cash is not None and ebitda is not None and ebitda > 0:
            net_debt_to_ebitda = (debt - cash) / ebitda
        metrics = {
            "period": str(latest)[:10],
            "latestNetIncome": net_income,
            "latestOperatingCashFlow": operating_cashflow,
            "latestOperatingMargin": operating_income / revenue if operating_income is not None and revenue and revenue > 0 else None,
            "latestRoe": net_income / equity if net_income is not None and equity and equity > 0 else None,
            "netDebtToEbitda": net_debt_to_ebitda,
            "latestRevenue": revenue,
        }
        return metrics, YFINANCE_FUNDAMENTAL_SOURCE, None
    except Exception as exc:
        return {}, None, f"yfinance fundamentals {type(exc).__name__}: {exc}"
