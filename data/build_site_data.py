#!/usr/bin/env python3
"""
build_site_data.py — Transform batch_*.json into per-stock JSON with technical indicators.

Input:  /tmp/tw_stock_data/batch_*.json
Output: public/data/stocks/{code}.json (latest 1000 trading days, enough for 樂活五線譜 3.5yr)

Key rule: MA uses data[T-N:T] excluding T (user's hard rule).
"""
import json
import math
import os
import glob
import sys


# ═══════════════════════════════════════════════════════════════
# Technical indicator functions
# ═══════════════════════════════════════════════════════════════

def compute_ma(close: list[float], period: int) -> list[float | None]:
    """
    Simple Moving Average excluding current day.
    MA at index T = average of close[T-period : T] (excludes close[T]).
    Returns None for indices where insufficient history exists.
    """
    result = []
    for i in range(len(close)):
        if i < period:
            result.append(None)
        else:
            window = close[i - period : i]
            result.append(sum(window) / period)
    return result


def compute_rsi(close: list[float], period: int = 14) -> list[float | None]:
    """
    RSI using Wilder's smoothing method.
    """
    result = [None] * len(close)

    if len(close) < period + 1:
        return result

    # First average gain/loss: simple average of first 'period' changes
    gains = []
    losses = []
    for i in range(1, period + 1):
        change = close[i] - close[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_gain == 0 and avg_loss == 0:
        result[period] = 50.0
    elif avg_loss == 0:
        result[period] = 100.0
    elif avg_gain == 0:
        result[period] = 0.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    # Wilder's smoothing for subsequent values
    for i in range(period + 1, len(close)):
        change = close[i] - close[i - 1]
        gain = max(change, 0)
        loss = abs(min(change, 0))

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_gain == 0 and avg_loss == 0:
            result[i] = 50.0
        elif avg_loss == 0:
            result[i] = 100.0
        elif avg_gain == 0:
            result[i] = 0.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))

    return result


def compute_kd(close: list[float], period: int = 9, smooth: int = 3) -> tuple[list[float | None], list[float | None]]:
    """
    Stochastic KD using close data (max/min close over period as proxy for high/low).
    """
    k_line = [None] * len(close)
    d_line = [None] * len(close)

    rsv_values = [None] * len(close)

    # Compute RSV for each bar
    for i in range(period - 1, len(close)):
        window = close[i - period + 1 : i + 1]
        high = max(window)
        low = min(window)
        if high == low:
            rsv_values[i] = 50.0
        else:
            rsv_values[i] = (close[i] - low) / (high - low) * 100.0

    # Compute K and D with smoothing
    for i in range(len(close)):
        if rsv_values[i] is None:
            continue
        # K = 2/3 * prev_K + 1/3 * RSV
        if i == 0 or k_line[i - 1] is None:
            prev_k = 50.0
        else:
            prev_k = k_line[i - 1]
        k_line[i] = prev_k * (smooth - 1) / smooth + rsv_values[i] / smooth

        # D = 2/3 * prev_D + 1/3 * K
        if i == 0 or d_line[i - 1] is None:
            prev_d = 50.0
        else:
            prev_d = d_line[i - 1]
        d_line[i] = prev_d * (smooth - 1) / smooth + k_line[i] / smooth

    # Mark initial period as None (not enough history)
    min_required = period + smooth - 1
    if min_required < len(close):
        for i in range(min_required):
            k_line[i] = None
            d_line[i] = None
    else:
        # Not enough data for any valid KD
        k_line = [None] * len(close)
        d_line = [None] * len(close)

    return k_line, d_line


def _ema(data: list[float], period: int) -> list[float | None]:
    """Exponential Moving Average."""
    result = [None] * len(data)
    if len(data) < period:
        return result

    # SMA for the first EMA value
    sma = sum(data[:period]) / period
    result[period - 1] = sma

    multiplier = 2.0 / (period + 1)
    for i in range(period, len(data)):
        result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]

    return result


def compute_macd(close: list[float], fast: int = 12, slow: int = 26, signal_period: int = 9) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """
    MACD = EMA(fast) - EMA(slow).
    Signal = EMA(MACD, signal_period).
    Histogram = MACD - Signal.
    """
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)

    macd_line = [None] * len(close)
    for i in range(len(close)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            macd_line[i] = ema_fast[i] - ema_slow[i]

    # Signal line: EMA of MACD line
    signal_line = [None] * len(close)
    # Extract valid MACD values for EMA computation
    valid_macd = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    if len(valid_macd) >= signal_period:
        start_idx = valid_macd[0][0]
        macd_values = [v for _, v in valid_macd]
        ema_signal = _ema(macd_values, signal_period)
        for j, (orig_idx, _) in enumerate(valid_macd):
            signal_line[orig_idx] = ema_signal[j]

    # Histogram
    hist = [None] * len(close)
    for i in range(len(close)):
        if macd_line[i] is not None and signal_line[i] is not None:
            hist[i] = macd_line[i] - signal_line[i]

    return macd_line, signal_line, hist


def compute_change(close: list[float]) -> dict[str, float]:
    """
    Compute percentage change for 1d, 1w, 1m, 3m, 1y.
    Using trading day approximations: 1w=5, 1m=22, 3m=66, 1y=252
    """
    periods = {"1d": 1, "1w": 5, "1m": 22, "3m": 66, "1y": 252}
    result = {}
    latest = close[-1]
    for name, offset in periods.items():
        if len(close) > offset:
            prev = close[-1 - offset]
            if prev != 0:
                result[name] = round((latest - prev) / prev * 100, 2)
            else:
                result[name] = 0.0
        else:
            result[name] = 0.0
    return result


def compute_ma_status(ma5: float | None, ma20: float | None, ma60: float | None) -> str:
    """
    Determine MA alignment:
    - 多頭排列: MA5 > MA20 > MA60
    - 空頭排列: MA5 < MA20 < MA60
    - 盤整: anything else
    """
    if ma5 is None or ma20 is None or ma60 is None:
        return "盤整"
    if ma5 > ma20 > ma60:
        return "多頭排列"
    elif ma5 < ma20 < ma60:
        return "空頭排列"
    else:
        return "盤整"


# ═══════════════════════════════════════════════════════════════
# Stock processing
# ═══════════════════════════════════════════════════════════════

def process_stock(code: str, stock_data: dict, max_days: int = 1000) -> dict:
    """
    Process a single stock's data into the output JSON format.

    Args:
        code: Stock code (e.g. "2330")
        stock_data: Raw data from batch file (dates, close, volume, name, start, end, days)
        max_days: Maximum number of trading days to output

    Returns:
        Dict in the per-stock JSON format for Astro consumption.
    """
    dates = stock_data["dates"]
    close = stock_data["close"]
    volume = stock_data["volume"]

    # Take most recent max_days
    if len(dates) > max_days:
        dates = dates[-max_days:]
        close = close[-max_days:]
        volume = volume[-max_days:]

    # Compute all indicators on the full dataset
    ma5 = compute_ma(close, 5)
    ma20 = compute_ma(close, 20)
    ma60 = compute_ma(close, 60)
    rsi14 = compute_rsi(close, 14)
    kd_k, kd_d = compute_kd(close, 9, 3)
    macd, macd_signal, macd_hist = compute_macd(close, 12, 26, 9)

    # Latest values
    latest_price = close[-1]
    if len(close) >= 2:
        latest_change_pct = round((close[-1] - close[-2]) / close[-2] * 100, 2)
    else:
        latest_change_pct = 0.0
    latest_volume = volume[-1]

    # Change percentages (computed on the truncated data)
    change = compute_change(close)

    # MA status (using latest available MAs)
    ma_status = compute_ma_status(
        ma5[-1] if ma5 else None,
        ma20[-1] if ma20 else None,
        ma60[-1] if ma60 else None,
    )

    # Round all float values to 2 decimal places for compact JSON
    def round_list(lst):
        if lst is None:
            return None
        return [round(v, 2) if v is not None else None for v in lst]

    result = {
        "code": code,
        "name": stock_data["name"],
        "start": stock_data["start"],
        "end": stock_data["end"],
        "days": stock_data["days"],
        "price": {
            "dates": dates,
            "close": round_list(close),
            "volume": volume,  # keep as int
            "ma5": round_list(ma5),
            "ma20": round_list(ma20),
            "ma60": round_list(ma60),
            "rsi14": round_list(rsi14),
            "kd_k": round_list(kd_k),
            "kd_d": round_list(kd_d),
            "macd": round_list(macd),
            "macd_signal": round_list(macd_signal),
            "macd_hist": round_list(macd_hist),
        },
        "latest": {
            "price": round(latest_price, 2),
            "change_pct": latest_change_pct,
            "volume": latest_volume,
        },
        "change": change,
        "ma_status": ma_status,
    }
    return result


# ═══════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════

def load_batch_files(batch_dir: str) -> dict[str, dict]:
    """
    Load all batch_*.json files and merge into a single dict keyed by stock code.

    Keys like "2330.TW" are stripped to "2330".
    """
    all_stocks = {}
    pattern = os.path.join(batch_dir, "batch_*.json")
    files = sorted(glob.glob(pattern))
    print(f"Found {len(files)} batch files in {batch_dir}")

    for fpath in files:
        with open(fpath, "r", encoding="utf-8") as f:
            batch = json.load(f)
        for key, stock_data in batch.items():
            # Strip .TW suffix
            code = key.replace(".TW", "").replace(".tw", "")
            all_stocks[code] = stock_data

    print(f"Loaded {len(all_stocks)} stocks total")
    return all_stocks


def main():
    batch_dir = "/tmp/tw_stock_data"
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "data", "stocks")
    output_dir = os.path.abspath(output_dir)

    # Also support being run from project root
    if not os.path.isdir(batch_dir):
        batch_dir = "/tmp/tw_stock_data"

    os.makedirs(output_dir, exist_ok=True)

    all_stocks = load_batch_files(batch_dir)

    processed = 0
    errors = 0

    for code, stock_data in sorted(all_stocks.items()):
        try:
            result = process_stock(code, stock_data, max_days=1000)
            out_path = os.path.join(output_dir, f"{code}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
            processed += 1
        except Exception as e:
            print(f"ERROR processing {code} ({stock_data.get('name', '?')}): {e}", file=sys.stderr)
            errors += 1

    print(f"Done. Processed {processed} stocks, {errors} errors.")
    print(f"Output: {output_dir}/")

    # Quick verification
    verify_path = os.path.join(output_dir, "2330.json")
    if os.path.exists(verify_path):
        with open(verify_path, "r", encoding="utf-8") as f:
            ts = json.load(f)
        print(f"Verification: 2330.json exists, {len(ts['price']['dates'])} days, "
              f"latest={ts['latest']['price']}, MA5[last]={ts['price']['ma5'][-1]}, "
              f"close[0]={ts['price']['close'][0]}")


if __name__ == "__main__":
    main()
