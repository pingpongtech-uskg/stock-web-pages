#!/usr/bin/env python3
"""
📈 各 TOP N 一年內翻倍機率分析
"""
import sys, os, json, glob
from datetime import datetime, timedelta
import numpy as np
from bisect import bisect_left

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
CACHE_FILE = os.path.join(BASE, "output", "trust_cache.json")
FUND_CACHE = os.path.join(BASE, "output", "fund_cache.json")
COST = 0.6

print("=" * 120, flush=True)
print("📈 投信買超 TOP N — 一年內翻倍機率分析")
print(f"📆 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 120, flush=True)

# ─── Load data ──────────────────────────────────────────────────
print("\n📦 Loading stock data...", flush=True)
stocks = {}
for f in sorted(glob.glob(os.path.join(DATA_DIR, "batch_*.json"))):
    with open(f) as fh:
        batch = json.load(fh)
    for sym, d in batch.items():
        if sym not in stocks and len(d.get("dates", [])) >= 500:  # need >=1yr of data
            stocks[sym] = d

sorted_syms = sorted(stocks.keys(), key=lambda s: len(stocks[s]["dates"]), reverse=True)
symbols = sorted_syms[:100]
print(f"   {len(symbols)} stocks", flush=True)

stock_prices = {sym: {stocks[sym]["dates"][i]: float(stocks[sym]["close"][i]) 
                      for i in range(len(stocks[sym]["dates"]))} 
                for sym in symbols}
stock_dates = {sym: stocks[sym]["dates"] for sym in symbols}

def get_fwd_returns(sym, date_str, max_hold=250):
    """Returns all forward returns at various horizons up to max_hold business days."""
    dates = stock_dates.get(sym, [])
    prices = stock_prices.get(sym, {})
    i = bisect_left(dates, date_str)
    if i >= len(dates) or dates[i] != date_str: return {}
    
    entry = prices[dates[i]]
    if entry <= 0: return {}
    
    returns = {}
    for h in [20, 60, 120, 250]:  # 1mo, 3mo, 6mo, 12mo
        j = i + h
        if j < len(dates) and entry > 0:
            returns[h] = prices[dates[j]] / entry - 1
    return returns

# ─── Load cached 投信 data ─────────────────────────────────
print("\n📦 Loading cached 投信 data...", flush=True)
with open(CACHE_FILE) as f:
    trust_windows = json.load(f)
print(f"   {len(trust_windows)} stocks loaded", flush=True)

# ─── Load fundamental scores ───────────────────────────────
print("\n📦 Loading cached fundamental data...", flush=True)
with open(FUND_CACHE) as f:
    fundamental_scores = json.load(f)
print(f"   {len(fundamental_scores)} stocks loaded", flush=True)

# ─── Monthly evaluation dates ──────────────────────────────
print("\n📐 Building evaluation dates...", flush=True)
eval_dates = []
dates_set = set(stock_dates.get(symbols[0], []))
from calendar import monthrange
for year in range(2015, 2026):
    for month in range(1, 13):
        last_day = monthrange(year, month)[1]
        candidate = f"{year}-{month:02d}-{last_day:02d}"
        while candidate not in dates_set and int(candidate[-2:]) > 0:
            d = datetime.strptime(candidate, "%Y-%m-%d") - timedelta(days=1)
            candidate = d.strftime("%Y-%m-%d")
        if candidate in dates_set:
            eval_dates.append(candidate)
print(f"   {len(eval_dates)} months", flush=True)

def get_cum_value(trust_data, date_str, window_name):
    dates = trust_data["dates"]
    vals = trust_data[window_name]
    i = bisect_left(dates, date_str)
    if i >= len(dates) or dates[i] != date_str:
        if i > 0: i -= 1
        else: return None
    v = vals[i]
    return v if v is not None and v > 0 else None

WINDOWS = {"d20": "20日", "d10": "10日"}
TOP_N_LIST = [10, 20, 50]

# ─── Run analysis ───────────────────────────────────────────
print(f"\n📊 Running analysis...", flush=True)

results = {}
for top_n in TOP_N_LIST:
    for win_name, win_label in WINDOWS.items():
        key = f"Top{top_n}_{win_label}"
        # Track all forward returns
        results[key] = {"1m": [], "3m": [], "6m": [], "12m": [], "max_ret_12m": [], "high_water_mark": []}
        
        for eval_date in eval_dates:
            ranking = []
            for sym in trust_windows:
                cum = get_cum_value(trust_windows[sym], eval_date, win_name)
                if cum is None: continue
                ranking.append((sym, cum))
            
            ranking.sort(key=lambda x: -x[1])
            if not ranking: continue
            
            for sym, cum in ranking[:top_n]:
                fs = fundamental_scores.get(sym, 0)
                if fs < 60: continue  # 基本面≥60
                
                rets = get_fwd_returns(sym, eval_date)
                if 250 in rets:
                    results[key]["12m"].append(rets[250] - COST/100)
                    results[key]["max_ret_12m"].append(max(rets.values()) - COST/100)
                
                if 60 in rets:
                    results[key]["3m"].append(rets[60] - COST/100)
                if 120 in rets:
                    results[key]["6m"].append(rets[120] - COST/100)
                if 20 in rets:
                    results[key]["1m"].append(rets[20] - COST/100)

# ─── Report ─────────────────────────────────────────────────
for win_name, win_label in WINDOWS.items():
    print(f"\n{'='*120}", flush=True)
    print(f"🎯  窗口: {win_label}（基本面≥60）", flush=True)
    print(f"{'='*120}", flush=True)
    
    print(f"{'TOP N':>6s} {'指標':>12s} {'訊號':>7s} {'勝率':>9s} {'均報酬':>9s} {'中位數':>9s} {'最大值':>9s} {'翻倍率':>9s} {'翻倍數':>8s}", flush=True)
    print(f"{'─'*120}", flush=True)
    
    for top_n in TOP_N_LIST:
        key = f"Top{top_n}_{win_label}"
        r = results[key]
        
        for label, arr_key in [("1個月", "1m"), ("3個月", "3m"), ("6個月", "6m"), ("12個月", "12m")]:
            arr = np.array(r.get(arr_key, []))
            if len(arr) < 3: continue
            
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            med = np.median(arr)
            mx = np.max(arr)
            double_rate = np.mean(arr >= 1.0)  # 100%+ = 翻倍
            double_count = int(np.sum(arr >= 1.0))
            
            print(f"Top{top_n:>3d} {label:>12s} {len(arr):>7d} {wr:>8.1%} {avg:>+8.2%} {med:>+8.2%} {mx:>+8.2%} {double_rate:>8.1%} {double_count:>6d}", flush=True)
        
        # Also show best-case analysis
        arr_max = np.array(r.get("max_ret_12m", []))
        if len(arr_max) >= 3:
            best_double = np.mean(arr_max >= 1.0)
            best_avg = np.mean(arr_max)
            best_med = np.median(arr_max)
            print(f"{'':>6s} {'最高(12m內)':>12s} {len(arr_max):>7d} {'':>9s} {best_avg:>+8.2%} {best_med:>+8.2%} {'':>9s} {best_double:>8.1%}", flush=True)

# ─── Summary comparison across windows ──────────────────────
print(f"\n{'='*120}", flush=True)
print(f"🏆  翻倍機率總評比（12個月）", flush=True)
print(f"{'='*120}", flush=True)
print(f"{'TOP N':>6s} {'窗口':>6s} {'訊號':>7s} {'12月勝率':>9s} {'12月報酬':>9s} {'翻倍率':>9s} {'翻倍數':>8s} {'最大12月報酬':>11s}", flush=True)
print(f"{'─'*120}", flush=True)

for win_name, win_label in WINDOWS.items():
    for top_n in TOP_N_LIST:
        key = f"Top{top_n}_{win_label}"
        r = results[key]
        arr = np.array(r.get("12m", []))
        arr_max = np.array(r.get("max_ret_12m", []))
        if len(arr) < 3: continue
        
        wr = np.mean(arr > 0)
        avg = np.mean(arr)
        mx = np.max(arr)
        double_rate = np.mean(arr >= 1.0)
        double_count = int(np.sum(arr >= 1.0))
        
        print(f"Top{top_n:>3d} {win_label:>6s} {len(arr):>7d} {wr:>8.1%} {avg:>+8.2%} {double_rate:>8.1%} {double_count:>6d} {mx:>+10.1%}", flush=True)

# ─── Additional: Distribution of best trades ─────────────────
print(f"\n{'='*120}", flush=True)
print(f"📊  翻倍交易分布（Top10 + 20日 + 基本面≥60）", flush=True)
print(f"{'='*120}", flush=True)

key = "Top10_20日"
arr = np.array(results[key].get("12m", []))
arr_max = np.array(results[key].get("max_ret_12m", []))

if len(arr) > 0:
    buckets = [(-1, -0.3), (-0.3, -0.1), (-0.1, 0), (0, 0.1), (0.1, 0.3), (0.3, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, float('inf'))]
    labels = ["<-30%", "-30~-10%", "-10~0%", "0~10%", "10~30%", "30~50%", "50~100%", "100~200%", "200~500%", ">500%"]
    print(f"\n   12個月實際報酬分布（{len(arr)} 筆交易）:")
    for (lo, hi), lb in zip(buckets, labels):
        cnt = np.sum((arr > lo) & (arr <= hi))
        bar = "█" * max(1, cnt)
        print(f"   {lb:>12s}: {cnt:>4d}筆 {bar}", flush=True)
    
    print(f"\n   12個月內最高報酬分布（{len(arr_max)} 筆）:")
    for (lo, hi), lb in zip(buckets, labels):
        cnt = np.sum((arr_max > lo) & (arr_max <= hi))
        bar = "█" * max(1, cnt)
        print(f"   {lb:>12s}: {cnt:>4d}筆 {bar}", flush=True)

print(f"\n✅ 完成: {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
