#!/usr/bin/env python3
"""
build_screener_history.py — Consolidate daily_trust10_*.json into screener_history.json.

Input:  /root/tw-stock-monitor/output/reports/daily_trust10_*.json
        /root/tw-stock-monitor/output/trust_all_cache.json (for consecutive buy days)
        /root/tw-stock-monitor/data/batch_*.json (for correct Z recomputation)
Output: src/data/screener_history.json

Structure:
  - active: unique stocks sorted by last_date DESC (newest first)
            Stocks that haven't appeared in 30 days are simply removed.
  - archive: ALL screening entries grouped by date (newest first)
             Pure historical record, no demotion from active.

Each entry includes:
  - first_date: earliest screening date
  - last_date: most recent screening date
  - consecutive_buy_days: actual consecutive days of 投信 net buying (from TWSE cache)
  - regression_z: 樂活五線譜 3.5yr Z-score (log-price regression, recomputed correctly)
"""
import json
import os
import glob
import numpy as np
from datetime import date, datetime, timedelta
from collections import defaultdict

REPORTS_DIR = "/root/tw-stock-monitor/output/reports"
TRUST_CACHE_FILE = "/root/tw-stock-monitor/output/trust_all_cache.json"
DATA_DIR = "/root/tw-stock-monitor/data"
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "data", "screener_history.json")
ARCHIVE_AFTER_DAYS = 30
MAX_CONSECUTIVE_GAP = 3  # For screening streak (weekend tolerance)


def load_reports(reports_dir: str) -> list[dict]:
    """Load all daily_trust10_*.json files, return sorted by date DESC."""
    pattern = os.path.join(reports_dir, "daily_trust10_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    reports = []
    for fpath in files:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        reports.append(data)
    return reports


def load_trust_cache(path: str) -> dict | None:
    """Load trust_all_cache.json. Returns {code: {dates: [...], net: [...]}} or None."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_batch_prices(data_dir: str, code: str) -> np.ndarray | None:
    """Load close prices for a stock from batch_*.json files. Returns numpy array or None."""
    for i in range(1, 26):
        p = os.path.join(data_dir, f"batch_{i:03d}.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            batch = json.load(f)
        # Try TW and TWO suffixes
        for suffix in [".TW", ".TWO", ""]:
            key = f"{code}{suffix}"
            if key in batch:
                prices = batch[key].get("close", [])
                if len(prices) >= 200:
                    return np.array(prices, dtype=float)
    return None


def compute_z(prices: np.ndarray) -> float | None:
    """
    樂活五線譜 3.5年 Z-score (raw prices, auto_adjust=False).
    參數與籌碼K線 APP 一致。
    
    p: array of daily close prices (most recent last).
    Returns Z = (P_now - trend_now) / sigma_residuals.
    """
    if len(prices) < 100:
        return None
    # 3.5yr = 882 trading days
    p = prices[-882:] if len(prices) >= 882 else prices
    if len(p) < 100:
        return None
    x = np.arange(len(p))
    slope, intercept = np.polyfit(x, p, 1)
    trend = slope * x + intercept
    residuals = p - trend
    sigma = np.std(residuals, ddof=0)
    if sigma <= 0:
        return None
    z = (p[-1] - trend[-1]) / sigma
    return round(float(z), 2)


def calc_consecutive_buy(trust_cache: dict, code: str, as_of_date: str | None = None) -> int:
    """
    Count consecutive days of positive 投信 net buying from trust cache.
    Counts backwards from as_of_date (or latest date in cache).
    """
    if trust_cache is None or code not in trust_cache:
        return 0
    
    stock_data = trust_cache[code]
    dates = stock_data.get("dates", [])
    nets = stock_data.get("net", [])
    
    if not dates or not nets:
        return 0
    
    # Find the cutoff index (as_of_date or use all data)
    cutoff_idx = len(dates)
    if as_of_date:
        for i in range(len(dates) - 1, -1, -1):
            if dates[i] <= as_of_date:
                cutoff_idx = i + 1
                break
    
    # Count consecutive positive net buys backwards from cutoff_idx - 1
    consecutive = 0
    for i in range(cutoff_idx - 1, -1, -1):
        if nets[i] > 0:
            consecutive += 1
        else:
            break
    
    return consecutive


def calc_net_shares_10d(trust_cache: dict, code: str, as_of_date: str) -> float:
    """
    Calculate the TRUE 10-day cumulative net shares (buy - sell).
    Uses sum of ALL daily net values (positive + negative), not just positive days.
    """
    if not trust_cache or code not in trust_cache:
        return 0
    
    stock_data = trust_cache[code]
    dates = stock_data.get('dates', [])
    nets = stock_data.get('net', [])
    
    if not dates or len(dates) < 1:
        return 0
    
    # Sort by date
    zd = sorted(zip(dates, nets))
    dt = [z[0] for z in zd]
    nv = [z[1] for z in zd]
    
    # Find the index of as_of_date or the closest <= as_of_date
    i = len(dt) - 1
    for j in range(len(dt) - 1, -1, -1):
        if dt[j] <= as_of_date:
            i = j
            break
    
    # Sum the last 10 days (or fewer if not enough data)
    start = max(0, i - 9)
    ts = sum(nv[j] for j in range(start, i + 1))
    return ts if ts > 0 else 0


def consolidate(reports: list[dict], trust_cache: dict | None, reference_date: str | None = None) -> dict:
    """Build active (unique, recent) and archive (all, grouped by date)."""
    ref = date.today() if reference_date is None else datetime.strptime(reference_date, "%Y-%m-%d").date()
    cutoff = ref - timedelta(days=ARCHIVE_AFTER_DAYS)

    # Build name_zh lookup
    name_zh_map: dict[str, str] = {
        "2377": "微星", "1229": "聯華", "2548": "華固",
    }
    for report in reports:
        for stock in report.get("top10", []):
            code = stock.get("code", "")
            zh = stock.get("name_zh", "")
            if code and zh:
                name_zh_map[code] = zh

    # Collect all entries + track earliest/latest per stock
    all_entries: list[dict] = []
    code_to_dates: dict[str, list[str]] = defaultdict(list)

    for report in reports:
        report_date = report.get("date", "")
        for stock in report.get("top10", []):
            code = stock.get("code", "")
            name_zh = stock.get("name_zh", "") or name_zh_map.get(code, "")
            entry = {
                "code": code,
                "name_zh": name_zh,
                "name_en": stock.get("name", ""),
                "net_amount_10d": stock.get("net_amount_10d", 0),
                "net_amount_10d_k": stock.get("net_amount_10d_k", 0),
                "net_shares_10d": stock.get("net_shares_10d", 0),
                "net_shares_10d_zhang": stock.get("net_shares_10d_zhang", 0),
                "last_date": stock.get("last_date", report_date),
                "cur_price": stock.get("cur_price", 0),
                "g_score": stock.get("g_score", 0),
                "l_score": stock.get("l_score", 0),
                "regression_z": stock.get("regression_z", 0),
                "rank": stock.get("rank", 0),
                "screening_date": report_date,
            }
            all_entries.append(entry)
            code_to_dates[code].append(report_date)

    # Build per-code lookup: latest entry, earliest date, and first_price
    latest_by_code: dict[str, dict] = {}
    first_price_map: dict[str, float] = {}  # code -> price at first appearance
    for entry in all_entries:
        code = entry["code"]
        if code not in latest_by_code or entry["screening_date"] > latest_by_code[code]["screening_date"]:
            latest_by_code[code] = entry

    # Build first_price_map: for each code, find price on first_date
    for code, dates in code_to_dates.items():
        first_date = min(dates)
        for entry in all_entries:
            if entry["code"] == code and entry["screening_date"] == first_date:
                first_price_map[code] = entry.get("cur_price", 0)
                break

    # Precompute Z + live prices for active stocks using yfinance
    print("Fetching live prices + Z from yfinance (raw prices, auto_adjust=False)...")
    z_cache: dict[str, float | None] = {}
    live_price_cache: dict[str, float] = {}  # code -> latest close price
    try:
        import yfinance as yf
        for code in latest_by_code:
            try:
                tk = None
                for ext in [".TW", ".TWO"]:
                    tk = yf.Ticker(f"{code}{ext}")
                    hist = tk.history(period="5y", auto_adjust=False)
                    if hist is not None and len(hist) >= 200:
                        break
                if hist is None or len(hist) < 200:
                    # Try shorter period for live price only
                    for ext in [".TW", ".TWO"]:
                        tk = yf.Ticker(f"{code}{ext}")
                        hist = tk.history(period="5d", auto_adjust=False)
                        if hist is not None and len(hist) >= 1:
                            break
                    if hist is None or len(hist) < 1:
                        continue
                    # Have price but not enough for Z
                    p = hist['Close'].values
                    if hasattr(p[0], 'item'):
                        p = np.array([float(x) for x in p])
                    live_price_cache[code] = float(p[-1])
                    continue

                p = hist['Close'].values
                if hasattr(p[0], 'item'):
                    p = np.array([float(x) for x in p])
                # Live price = latest close
                live_price_cache[code] = float(p[-1])
                # Z from full 5y
                z = compute_z(p)
                if z is not None:
                    z_cache[code] = z
            except Exception as e:
                continue
    except ImportError:
        print("  WARNING: yfinance not available, using report prices as-is")

    # Update cur_price for active stocks from live data
    updated_count = 0
    for code, entry in latest_by_code.items():
        if code in live_price_cache:
            old_p = entry.get("cur_price", 0)
            new_p = live_price_cache[code]
            if abs(new_p - old_p) > 0.01:
                entry["cur_price"] = round(new_p, 2)
                updated_count += 1
    if updated_count:
        print(f"  Updated cur_price for {updated_count} stocks from yfinance live data")

    # Precompute cheap/dividend scores for ALL stocks (active + archive)
    all_codes = sorted(set(list(latest_by_code.keys()) + list(code_to_dates.keys())))
    print(f"Computing cheap/dividend value scores for {len(all_codes)} stocks...")
    value_cache: dict[str, dict] = {}
    try:
        from compute_value_scores import get_scores as get_value_scores
        value_cache = get_value_scores(all_codes)
    except ImportError:
        print("  WARNING: compute_value_scores not available, showing —")
    except Exception as e:
        print(f"  WARNING: value scores failed: {e}")

    # Build active list
    active = []
    for code, entry in latest_by_code.items():
        try:
            last_d = datetime.strptime(entry["last_date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            last_d = date(2000, 1, 1)

        if last_d < cutoff:
            continue  # Skip — expired from active

        dates = code_to_dates.get(code, [])
        first_date = min(dates) if dates else entry["last_date"]
        consecutive_buy = calc_consecutive_buy(trust_cache, code, entry["last_date"])

        # Use recomputed Z if available
        if code in z_cache and z_cache[code] is not None:
            entry["regression_z"] = z_cache[code]

        entry["first_date"] = first_date
        entry["consecutive_buy_days"] = consecutive_buy

        # Recalculate net_shares_10d correctly (buy - sell, not just positive days)
        corrected_shares = calc_net_shares_10d(trust_cache, code, entry["last_date"])
        if corrected_shares > 0:
            entry["net_shares_10d"] = round(corrected_shares)
            entry["net_shares_10d_zhang"] = round(corrected_shares / 1000)
            cur_p = entry.get("cur_price", 0)
            if cur_p > 0:
                entry["net_amount_10d"] = round(corrected_shares * cur_p)
                entry["net_amount_10d_k"] = round(corrected_shares * cur_p / 1000)

        # 最初上榜股價 & 漲跌幅
        first_p = first_price_map.get(code, entry.get("cur_price", 0))
        cur_p = entry.get("cur_price", 0)
        entry["first_price"] = first_p
        if first_p and first_p > 0 and cur_p:
            entry["change_pct"] = round((cur_p - first_p) / first_p * 100, 2)
        else:
            entry["change_pct"] = None

        # Add value scores if available
        if code in value_cache:
            vs = value_cache[code]
            entry["cheap_score"] = vs.get("cheap_score")
            entry["dividend_score"] = vs.get("dividend_score")
        else:
            entry["cheap_score"] = None
            entry["dividend_score"] = None

        active.append(entry)

    # Sort active: by last_date DESC (newest first)
    active.sort(key=lambda x: x["last_date"], reverse=True)

    # Build archive: ALL entries from ALL reports, grouped by date
    # No demotion from active — archive is purely historical record
    # IMPORTANT: make shallow copies so archive mutations don't affect active entries
    archive_date_to_stocks: dict[str, list[dict]] = defaultdict(list)
    for entry in all_entries:
        code = entry["code"]
        dates = code_to_dates.get(code, [])
        first_date = min(dates) if dates else entry["last_date"]
        consecutive_buy = calc_consecutive_buy(trust_cache, code, entry["screening_date"])
        archive_entry = dict(entry)  # Shallow copy
        archive_entry["first_date"] = first_date
        archive_entry["consecutive_buy_days"] = consecutive_buy
        
        # Recalculate net_shares_10d with CORRECT formula (buy - sell, not just positive days)
        corrected_shares = calc_net_shares_10d(trust_cache, code, entry["screening_date"])
        if corrected_shares > 0:
            archive_entry["net_shares_10d"] = round(corrected_shares)
            archive_entry["net_shares_10d_zhang"] = round(corrected_shares / 1000)
            # Recalculate amount using the original price from the report
            price_at_time = entry.get("cur_price", 0)
            if price_at_time > 0:
                archive_entry["net_amount_10d"] = round(corrected_shares * price_at_time)
                archive_entry["net_amount_10d_k"] = round(corrected_shares * price_at_time / 1000)
        
        # Backfill value scores from cache (current snapshot for archive)
        if code in value_cache:
            vs = value_cache[code]
            archive_entry["cheap_score"] = vs.get("cheap_score")
            archive_entry["dividend_score"] = vs.get("dividend_score")
        else:
            archive_entry["cheap_score"] = None
            archive_entry["dividend_score"] = None
        archive_date_to_stocks[archive_entry["screening_date"]].append(archive_entry)

    archive = {}
    for d in sorted(archive_date_to_stocks.keys(), reverse=True):
        stocks = sorted(archive_date_to_stocks[d], key=lambda x: x["net_amount_10d"], reverse=True)
        archive[d] = stocks

    return {"active": active, "archive": archive}


def main():
    reports = load_reports(REPORTS_DIR)
    print(f"Loaded {len(reports)} reports")

    trust_cache = load_trust_cache(TRUST_CACHE_FILE)
    if trust_cache:
        print(f"Loaded trust cache: {len(trust_cache)} stocks")
    else:
        print("WARNING: trust cache not found, consecutive_buy_days will be 0")

    result = consolidate(reports, trust_cache)

    active_count = len(result["active"])
    archive_dates = len(result["archive"])
    archive_entries = sum(len(v) for v in result["archive"].values())

    print(f"\nActive: {active_count} unique stocks")
    for s in result["active"][:8]:
        fp = s.get('first_price', '-')
        cp = s.get('cur_price', '-')
        ch = s.get('change_pct', '-')
        ch_str = f"{ch:+.1f}%" if isinstance(ch, (int, float)) else "-"
        print(f"  {s['code']} {s['name_zh']} | 首次:{s['first_date']} 最新:{s['last_date']} | 連續買超:{s['consecutive_buy_days']}日 | Z={s['regression_z']} | 股價:{fp}>{cp} ({ch_str})")

    print(f"\nArchive: {archive_entries} entries across {archive_dates} dates")

    out_dir = os.path.dirname(OUTPUT_FILE)
    os.makedirs(out_dir, exist_ok=True)
    
    # Debug: check first active entry
    if result["active"]:
        s0 = result["active"][0]
        print(f"  DEBUG before write: {s0['code']} cheap={s0.get('cheap_score')} div={s0.get('dividend_score')}")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"\nWritten: {OUTPUT_FILE} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
