#!/usr/bin/env python3
"""
📊 雷老闆「週線法人初建倉」策略回測

Quantified rules:
  Entry: Weekly VR ≥ 2.0 (量) + 投信/外資 net buy (法人) + 股價位置合理
  Hold: 4/8/12 週
  Compare: VR only vs VR+投信 vs VR+外資 vs 投信 only vs 外資 only

Data:
  - Price/Volume: Local batch JSON (daily, aggregated to weekly)
  - Institutional: FinMind API (taiwan_stock_institutional_investors)
  - Period: 2015-2026 (~11 years)
  - Universe: Top 500 stocks by liquidity
"""

import sys, os, json, glob
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import numpy as np
import pandas as pd
from FinMind.data import DataLoader
import re, time

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
COST = 0.6  # 交易成本 0.6% (來回)

# ─── FinMind setup ───────────────────────────────────────────────────
def get_finmind_api():
    src = os.path.join(BASE, "scripts", "download_otc_prices.py")
    if os.path.exists(src):
        with open(src) as f:
            content = f.read()
        for m in re.finditer(r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+', content):
            token = m.group()
            break
    api = DataLoader()
    api.login_by_token(api_token=token)
    return api

# ─── 1. Load batch data ─────────────────────────────────────────────
def load_stocks():
    stocks = {}
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "batch_*.json"))):
        with open(f) as fh:
            batch = json.load(fh)
        for sym, d in batch.items():
            if sym not in stocks and len(d.get("dates", [])) > 0:
                if len(d.get("dates", [])) >= 260:
                    stocks[sym] = d
    return stocks

# ─── 2. Daily → Weekly aggregation ──────────────────────────────────
def to_weekly(dates, closes, volumes):
    """Aggregate daily → weekly bars. Returns week dict keyed by (year, week)."""
    weekly = {}
    for i, d in enumerate(dates):
        dt = datetime.strptime(d, "%Y-%m-%d")
        yr, wk, _ = dt.isocalendar()
        key = (yr, wk)
        
        if key not in weekly:
            weekly[key] = {
                "date": d, "close": closes[i], "volume": volumes[i],
                "high": closes[i], "low": closes[i],
                "count": 1
            }
        else:
            w = weekly[key]
            w["high"] = max(w["high"], closes[i])
            w["low"] = min(w["low"], closes[i])
            w["close"] = closes[i]
            w["volume"] += volumes[i]
            w["date"] = d
            w["count"] += 1
    
    return weekly

# ─── 3. Compute weekly indicators ───────────────────────────────────
def compute_weekly(weekly):
    """Add VR, MAs, price position to weekly dict. Modifies in place."""
    keys = sorted(weekly.keys())
    n = len(keys)
    
    closes = np.array([weekly[k]["close"] for k in keys])
    volumes = np.array([weekly[k]["volume"] for k in keys])
    dates = [weekly[k]["date"] for k in keys]
    
    if n < 20:
        return [], []
    
    # Volume MA10 (exclusive - no look-ahead)
    vol_ma10 = np.full(n, np.nan)
    for i in range(10, n):
        vol_ma10[i] = np.mean(volumes[i-10:i])
    
    # Volume Ratio
    vr = np.full(n, np.nan)
    for i in range(10, n):
        vr[i] = volumes[i] / vol_ma10[i] if vol_ma10[i] > 0 else 0
    
    # Price MAs
    ma5 = np.full(n, np.nan)
    ma10 = np.full(n, np.nan)
    ma20 = np.full(n, np.nan)
    for i in range(4, n):
        ma5[i] = np.mean(closes[i-4:i+1])
    for i in range(9, n):
        ma10[i] = np.mean(closes[i-9:i+1])
    for i in range(19, n):
        ma20[i] = np.mean(closes[i-19:i+1])
    
    # Price position in 52-week range
    pct_52w = np.full(n, np.nan)
    for i in range(51, n):
        lo = np.min(closes[i-51:i+1])
        hi = np.max(closes[i-51:i+1])
        if hi > lo:
            pct_52w[i] = (closes[i] - lo) / (hi - lo)
    
    # Forward returns (4, 8, 12 weeks)
    fwd_4 = np.full(n, np.nan)
    fwd_8 = np.full(n, np.nan)
    fwd_12 = np.full(n, np.nan)
    for i in range(n - 12):
        fwd_4[i] = closes[i+4] / closes[i] - 1 if i+4 < n else np.nan
        fwd_8[i] = closes[i+8] / closes[i] - 1 if i+8 < n else np.nan
        fwd_12[i] = closes[i+12] / closes[i] - 1 if i+12 < n else np.nan
    
    return {
        "keys": keys, "dates": dates, "closes": closes, "volumes": volumes,
        "vr": vr, "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "pct_52w": pct_52w,
        "fwd_4": fwd_4, "fwd_8": fwd_8, "fwd_12": fwd_12,
    }, keys

# ─── 4. Main backtest ────────────────────────────────────────────────
def backtest():
    print("=" * 80)
    print("📊 雷老闆週線法人初建倉 — 量化回測")
    print(f"📆 開始: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)
    
    # Load stocks (limit to 500 for speed since FinMind is the bottleneck)
    print("\n📦 Loading stock data...")
    stocks = load_stocks()
    print(f"   Loaded {len(stocks)} stocks with 260+ days of data")
    
    # Pick universe: ~300 stocks - prioritize those with good data
    # Sort by data length, take top 300
    sorted_syms = sorted(stocks.keys(), key=lambda s: len(stocks[s]["dates"]), reverse=True)
    symbols = sorted_syms[:300]
    print(f"   Using top {len(symbols)} stocks by data length")
    
    # ── Phase 1: Compute all weekly VR signals (no API calls) ──
    print("\n📐 Computing weekly VR signals for all stocks...")
    
    all_signals = []  # [(symbol, signal_date, vr, price, pct_52w)]
    
    for sym in symbols:
        d = stocks[sym]
        weekly = to_weekly(d["dates"], d["close"], d["volume"])
        result, keys = compute_weekly(weekly)
        if not keys or not result:
            continue
        
        dates = result["dates"]
        
        # Find signal weeks (last 5 years: 2021-2026)
        # Also check a decade: 2015-2026
        for i in range(20, len(keys)):
            dt_str = dates[i]
            # Only check 2015-2025 for backtest (leave 2026 for live)
            if dt_str < "2015-01-01" or dt_str > "2025-12-31":
                continue
            
            vr_val = result["vr"][i]
            if np.isnan(vr_val) or vr_val < 2.0:
                continue
            
            pct = result["pct_52w"][i]
            close = result["closes"][i]
            
            # Get price position info
            above_ma5 = not np.isnan(result["ma5"][i]) and close >= result["ma5"][i]
            
            all_signals.append({
                "symbol": sym,
                "date": dt_str,
                "vr": round(vr_val, 2),
                "close": round(close, 2),
                "pct_52w": round(pct, 3) if not np.isnan(pct) else None,
                "above_ma5": bool(above_ma5),
                "idx": i,  # index in the weekly array for forward returns
                "result": result,
            })
    
    print(f"   Found {len(all_signals)} weekly VR≥2.0 signals across {len(symbols)} stocks")
    
    # ── Phase 2: Batch query FinMind for institutional data ──
    print("\n📡 Fetching institutional data from FinMind (rate-limited to 400/hr)...")
    api = get_finmind_api()
    
    # Rate limiter: max 400 calls per hour (safe for 600/hr limit)
    import time as _time_module
    inst_call_times = []
    def _fm_wait_rate():
        now = _time_module.time()
        while inst_call_times and now - inst_call_times[0] > 3600:
            inst_call_times.pop(0)
        if len(inst_call_times) >= 400:
            wait = inst_call_times[0] + 3600 - now
            if wait > 0:
                print(f"      ⏳ Rate limit nearly reached, waiting {wait:.0f}s...")
                _time_module.sleep(wait)
        # Also ensure 7s between calls
        if inst_call_times:
            gap = 7.0 - (now - inst_call_times[-1])
            if gap > 0:
                _time_module.sleep(gap)
        inst_call_times.append(_time_module.time())
    
    # Group signals by symbol to batch API calls
    sym_signals = defaultdict(list)
    for sig in all_signals:
        sym_signals[sig["symbol"]].append(sig)
    
    # For each symbol with signals, get the full institutional history in one call
    inst_cache = {}  # {symbol: DataFrame}
    sig_symbols = list(sym_signals.keys())
    
    batch_start = datetime.now()
    for idx, sym in enumerate(sig_symbols):
        if idx % 50 == 0:
            elapsed = (datetime.now() - batch_start).total_seconds()
            print(f"   [{idx}/{len(sym_signals)}] symbols processed... ({elapsed:.0f}s)")
        
        stock_id = sym.replace(".TW", "").replace(".TWO", "")
        _fm_wait_rate()  # respect FinMind rate limit
        try:
            df = api.taiwan_stock_institutional_investors(
                stock_id=stock_id,
                start_date="2015-01-01",
                end_date="2025-12-31"
            )
            if df is not None and not df.empty:
                inst_cache[sym] = df
        except Exception as e:
            pass  # Skip this symbol if API fails
        
        # Rate limit: sleep every 50 calls
        if idx > 0 and idx % 50 == 0:
            time.sleep(2)
    
    print(f"   Got institutional data for {len(inst_cache)} symbols")
    
    # ── Phase 3: Classify each signal by institutional activity ──
    print("\n🔬 Classifying signals by institutional activity...")
    
    classified = defaultdict(list)  # strategy → list of forward returns
    
    strategies = {
        "VR≥2 (全體)": lambda sym, date, df: True,
        "VR+投信買超": lambda sym, date, df: check_institutional(df, date, "Investment_Trust", "buy"),
        "VR+投信連3買": lambda sym, date, df: check_inst_consecutive(df, date, "Investment_Trust", 3),
        "VR+外資買超": lambda sym, date, df: check_institutional(df, date, "Foreign_Investor", "buy"),
        "VR+外資連3買": lambda sym, date, df: check_inst_consecutive(df, date, "Foreign_Investor", 3),
        "VR+投信or外資買超": lambda sym, date, df: check_institutional(df, date, "Investment_Trust", "buy") or check_institutional(df, date, "Foreign_Investor", "buy"),
        "VR+投信連5買": lambda sym, date, df: check_inst_consecutive(df, date, "Investment_Trust", 5),
    }
    
    for sig in all_signals:
        sym = sig["symbol"]
        date = sig["date"]
        df = inst_cache.get(sym)
        
        if df is None:
            continue
        
        # Get forward returns
        r = sig["result"]
        i = sig["idx"]
        
        r4 = r["fwd_4"][i]
        r8 = r["fwd_8"][i]
        r12 = r["fwd_12"][i]
        
        if np.isnan(r12):
            continue  # no enough forward data
        
        # Also classify by position zone
        zone = "low(0-30%)" if sig["pct_52w"] is not None and sig["pct_52w"] < 0.30 else \
               "mid(30-60%)" if sig["pct_52w"] is not None and sig["pct_52w"] < 0.60 else \
               "high(60%+)" if sig["pct_52w"] is not None else "unknown"
        
        for strategy_name, check_fn in strategies.items():
            try:
                passes = check_fn(sym, date, df) if df is not None else False
                if passes:
                    classified[strategy_name].append({
                        "symbol": sym, "date": date, "vr": sig["vr"],
                        "close": sig["close"], "pct_52w": sig["pct_52w"],
                        "r4": r4, "r8": r8, "r12": r12,
                        "zone": zone,
                    })
            except Exception:
                pass
    
    # ── Phase 4: Report results ──
    print("\n" + "=" * 100)
    print(f"🏆  雷老闆週線法人初建倉 — 回測結果 (2015-2025)")
    print("=" * 100)
    print(f"{'策略':<25s} {'訊號數':>7s} {'勝率4w':>8s} {'均報酬4w':>10s} {'勝率8w':>8s} {'均報酬8w':>10s} {'勝率12w':>9s} {'均報酬12w':>11s}")
    print("-" * 100)
    
    results = []
    for strategy_name in strategies:
        sigs = classified.get(strategy_name, [])
        if len(sigs) < 10:
            continue
        
        r4_arr = np.array([s["r4"] for s in sigs])
        r8_arr = np.array([s["r8"] for s in sigs])
        r12_arr = np.array([s["r12"] for s in sigs])
        
        wr4 = np.mean(r4_arr > 0)
        wr8 = np.mean(r8_arr > 0)
        wr12 = np.mean(r12_arr > 0)
        
        avg4 = np.mean(r4_arr)
        avg8 = np.mean(r8_arr)
        avg12 = np.mean(r12_arr)
        
        results.append((strategy_name, len(sigs), wr4, avg4, wr8, avg8, wr12, avg12))
        
        print(f"{strategy_name:<25s} {len(sigs):>7d} "
              f"{wr4:>7.1%} {avg4:>+9.2%} "
              f"{wr8:>7.1%} {avg8:>+9.2%} "
              f"{wr12:>8.1%} {avg12:>+10.2%}")
    
    # ── Phase 5: Price position analysis ──
    print("\n" + "=" * 100)
    print(f"📊  股價位置分析 (VR+投信or外資買超)")
    print("=" * 100)
    
    sigs = classified.get("VR+投信or外資買超", [])
    if sigs:
        for zone_name in ["low(0-30%)", "mid(30-60%)", "high(60%+)"]:
            zone_sigs = [s for s in sigs if s["zone"] == zone_name]
            if len(zone_sigs) < 5:
                continue
            r12_arr = np.array([s["r12"] for s in zone_sigs])
            wr = np.mean(r12_arr > 0)
            avg = np.mean(r12_arr)
            med = np.median(r12_arr)
            print(f"  {zone_name:<20s}: n={len(zone_sigs):>5d}  勝率12w={wr:>7.1%}  均={avg:>+8.2%}  中位數={med:>+8.2%}")
    
    # ── Phase 6: 初建倉 vs 連續買超 vs 首周買超 ──
    print("\n" + "=" * 100)
    print(f"🔬  初建倉模式分析 (VR+投信)")
    print("=" * 100)
    
    # Check for "first week of institutional buying" (初建倉)
    first_buy_sigs = []
    for sig in all_signals:
        sym = sig["symbol"]
        date = sig["date"]
        df = inst_cache.get(sym)
        if df is None:
            continue
        
        r = sig["result"]
        i = sig["idx"]
        r12 = r["fwd_12"][i]
        if np.isnan(r12):
            continue
        
        # Check if this is a "first institutional buy" week
        # (no institutional buying in prior 4 weeks, then buy this week)
        is_first_buy = check_first_inst_buy(df, date, "Investment_Trust")
        
        if is_first_buy:
            first_buy_sigs.append({
                "symbol": sym, "date": date, "vr": sig["vr"],
                "close": sig["close"], "pct_52w": sig["pct_52w"],
                "r12": r12,
            })
    
    if first_buy_sigs:
        r12_arr = np.array([s["r12"] for s in first_buy_sigs])
        wr = np.mean(r12_arr > 0)
        avg = np.mean(r12_arr)
        med = np.median(r12_arr)
        print(f"  📌 投信初建倉(4週內首次買超+VR≥2):")
        print(f"     訊號={len(first_buy_sigs):>5d}  勝率12w={wr:>7.1%}  均={avg:>+8.2%}  中位數={med:>+8.2%}")
        
        # Split by price position
        low_sigs = [s for s in first_buy_sigs if s["pct_52w"] is not None and s["pct_52w"] < 0.30]
        mid_sigs = [s for s in first_buy_sigs if s["pct_52w"] is not None and 0.30 <= s["pct_52w"] < 0.60]
        high_sigs = [s for s in first_buy_sigs if s["pct_52w"] is not None and s["pct_52w"] >= 0.60]
        
        for name, zs in [("低檔<30%", low_sigs), ("中檔30-60%", mid_sigs), ("高檔>60%", high_sigs)]:
            if len(zs) >= 5:
                r12z = np.array([s["r12"] for s in zs])
                print(f"     {name:<15s}: n={len(zs):>4d}  勝率={np.mean(r12z>0):>7.1%}  均={np.mean(r12z):>+8.2%}  中位數={np.median(r12z):>+8.2%}")
    
    # ── Phase 7: Monthly vs quarterly analysis ──
    print("\n" + "=" * 100)
    print(f"📅  持倉週期比較 (VR+投信or外資)")
    print("=" * 100)
    
    sigs = classified.get("VR+投信or外資買超", [])
    if sigs:
        # Best holding period
        r4_arr = np.array([s["r4"] for s in sigs])
        r8_arr = np.array([s["r8"] for s in sigs])
        r12_arr = np.array([s["r12"] for s in sigs])
        
        print(f"  {'持倉':>8s} {'勝率':>7s} {'均報酬':>9s} {'中位數':>9s} {'夏普':>7s} {'盈虧比':>8s}")
        print(f"  {'-'*48}")
        
        for period, pr_name, r_arr in [(4, "4w(1月)", r4_arr), (8, "8w(2月)", r8_arr), (12, "12w(3月)", r12_arr)]:
            wr = np.mean(r_arr > 0)
            avg = np.mean(r_arr)
            med = np.median(r_arr)
            rr = abs(np.mean(r_arr[r_arr > 0]) / np.mean(np.abs(r_arr[r_arr < 0]))) if np.sum(r_arr < 0) > 0 else float('inf')
            sharpe = np.mean(r_arr) / np.std(r_arr) * np.sqrt(52/period) if np.std(r_arr) > 0 else 0
            print(f"  {pr_name:>8s} {wr:>7.1%} {avg:>+8.2%} {med:>+8.2%} {sharpe:>6.2f} {rr:>7.2f}")
    
    print(f"\n✅ 回測完成: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ─── Helper functions for institutional checking ──────────────────────
def check_institutional(df, signal_date, name, side="buy"):
    """Check if institution bought on the signal week's Friday."""
    df = df[df["date"] <= signal_date].copy()
    if df.empty:
        return False
    
    df = df[df["name"] == name]
    if df.empty:
        return False
    
    df = df.sort_values("date")
    recent = df.tail(5)  # last 5 trading days (1 week)
    
    # Check if net buy > 0 in this period
    recent["net_buy"] = recent["buy"] - recent["sell"]
    
    if side == "buy":
        return recent["net_buy"].sum() > 0
    else:
        return recent["net_buy"].sum() < 0

def check_inst_consecutive(df, signal_date, name, days=3):
    """Check if institution has been buying for consecutive days."""
    df = df[df["date"] <= signal_date].copy()
    if df.empty:
        return False
    
    df = df[df["name"] == name]
    if df.empty:
        return False
    
    df = df.sort_values("date")
    df["net_buy"] = df["buy"] - df["sell"]
    
    recent = df.tail(days)
    if len(recent) < days:
        return False
    
    return (recent["net_buy"] > 0).all()

def check_first_inst_buy(df, signal_date, name):
    """Check if this is the FIRST institutional buy in 4+ weeks."""
    df = df[df["date"] <= signal_date].copy()
    if df.empty:
        return False
    
    df = df[df["name"] == name]
    if df.empty:
        return False
    
    df = df.sort_values("date")
    df["net_buy"] = df["buy"] - df["sell"]
    
    # Recent week (last 5 days) - should have buying
    recent = df.tail(5)
    if (recent["net_buy"] <= 0).all():  # no buying this week
        return False
    
    # Prior 4 weeks - should have NO buying or very minimal
    if len(df) > 25:
        prior = df.iloc[-26:-5]  # 4 weeks before (20 trading days)
    else:
        return False
    
    # Check: no strong buying in prior period
    prior_total_buy = prior["net_buy"].sum()
    recent_total_buy = recent["net_buy"].sum()
    
    # First buy = recent buying > 2x average of prior 4 weeks
    avg_prior = prior_total_buy / max(1, len(prior))
    avg_recent = recent_total_buy / len(recent)
    
    return avg_recent > avg_prior * 3 and avg_recent > 0

if __name__ == "__main__":
    backtest()
