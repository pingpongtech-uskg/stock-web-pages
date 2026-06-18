#!/usr/bin/env python3
"""
📊 投信買超 TOP N 比較：10 vs 20 vs 50 vs 100
+ 基本面綜合分數 ≥ 60 篩選
"""
import sys, os, json, glob, time
from datetime import datetime, timedelta
from collections import OrderedDict, defaultdict
import numpy as np
from FinMind.data import DataLoader
import yfinance as yf
import re, warnings
from bisect import bisect_left
warnings.filterwarnings('ignore')

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
CACHE_FILE = os.path.join(BASE, "output", "trust_cache.json")
FUND_CACHE = os.path.join(BASE, "output", "fund_cache.json")
COST = 0.6

print("=" * 100, flush=True)
print("📊 投信買超 TOP N 比較：10 vs 20 vs 50 vs 100")
print(f"📆 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 100, flush=True)

# ─── Rate-limited API ──────────────────────────────────────────────
_fm_calls = []
def fm_wait():
    now = time.time()
    while _fm_calls and now - _fm_calls[0] > 3600: _fm_calls.pop(0)
    if len(_fm_calls) >= 500:
        wait = _fm_calls[0] + 3600 - now
        if wait > 0: time.sleep(wait + 1)
    if _fm_calls:
        gap = 5.0 - (now - _fm_calls[-1])
        if gap > 0: time.sleep(gap)
    _fm_calls.append(time.time())

def get_api():
    src = os.path.join(BASE, "scripts", "download_otc_prices.py")
    with open(src) as f:
        content = f.read()
    for m in re.finditer(r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+', content):
        token = m.group(); break
    api = DataLoader(); api.login_by_token(api_token=token)
    return api

# ─── Data Loading ──────────────────────────────────────────────────
print("\n📦 Loading stock data...", flush=True)
stocks = {}
for f in sorted(glob.glob(os.path.join(DATA_DIR, "batch_*.json"))):
    with open(f) as fh:
        batch = json.load(fh)
    for sym, d in batch.items():
        if sym not in stocks and len(d.get("dates", [])) >= 260:
            stocks[sym] = d

sorted_syms = sorted(stocks.keys(), key=lambda s: len(stocks[s]["dates"]), reverse=True)
symbols = sorted_syms[:100]
print(f"   {len(symbols)} stocks", flush=True)

# ─── Forward returns lookup ────────────────────────────────────────
print("\n📐 Building price lookup...", flush=True)
stock_prices = {sym: {stocks[sym]["dates"][i]: float(stocks[sym]["close"][i]) 
                      for i in range(len(stocks[sym]["dates"]))} 
                for sym in symbols}
stock_dates = {sym: stocks[sym]["dates"] for sym in symbols}

def get_fwd_return(sym, date_str, hold_days):
    dates = stock_dates.get(sym, [])
    prices = stock_prices.get(sym, {})
    i = bisect_left(dates, date_str)
    if i >= len(dates) or dates[i] != date_str: return None
    j = i + hold_days
    if j >= len(dates): return None
    entry = prices[dates[i]]
    return prices[dates[j]] / entry - 1 if entry > 0 else None

# ─── Phase 1: Get 投信 data ──────────────────────────────────────
if os.path.exists(CACHE_FILE):
    print(f"\n📦 Loading cached 投信 data...", flush=True)
    with open(CACHE_FILE) as f:
        trust_windows = json.load(f)
    print(f"   {len(trust_windows)} stocks loaded from cache", flush=True)
else:
    print(f"\n📡 Phase 1: 查 投信 買賣超 (100 stocks)...", flush=True)
    api = get_api()
    trust_windows = {}
    
    for idx, sym in enumerate(symbols):
        fm_wait()
        sid = sym.replace(".TW","").replace(".TWO","")
        if idx % 20 == 0: print(f"   [{idx}/100]", flush=True)
        
        try:
            df = api.taiwan_stock_institutional_investors(
                stock_id=sid, start_date="2014-01-01", end_date="2025-12-31"
            )
            if df is not None and not df.empty:
                trust_df = df[df['name']=='Investment_Trust'].sort_values('date').copy()
                trust_df['net_buy'] = trust_df['buy'] - trust_df['sell']
                
                for window, name in [(3,"d3"),(5,"d5"),(10,"d10"),(20,"d20")]:
                    trust_df[name] = trust_df['net_buy'].rolling(window, min_periods=max(2, window//3)).sum()
                
                trust_windows[sym] = {
                    "dates": trust_df['date'].tolist(),
                    "d3": [v if not np.isnan(v) else None for v in trust_df['d3'].tolist()],
                    "d5": [v if not np.isnan(v) else None for v in trust_df['d5'].tolist()],
                    "d10": [v if not np.isnan(v) else None for v in trust_df['d10'].tolist()],
                    "d20": [v if not np.isnan(v) else None for v in trust_df['d20'].tolist()],
                }
        except: pass
    
    print(f"   Saving cache ({len(trust_windows)} stocks)...", flush=True)
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'w') as f: json.dump(trust_windows, f)

# ─── Phase 2: Get fundamental data ────────────────────────────────
if os.path.exists(FUND_CACHE):
    print(f"\n📦 Loading cached fundamental data...", flush=True)
    with open(FUND_CACHE) as f:
        fundamental_scores = json.load(f)
    print(f"   {len(fundamental_scores)} stocks loaded from cache", flush=True)
else:
    print(f"\n📡 Phase 2: 查 基本面...", flush=True)
    fundamental_scores = {}
    for idx, sym in enumerate(trust_windows):
        if idx % 20 == 0: print(f"   [{idx}/{len(trust_windows)}]", flush=True)
        time.sleep(0.3)
        try:
            info = yf.Ticker(sym).info
            score = 0
            roe = info.get('returnOnEquity')
            if roe: score += min(25, max(0, roe * 100))
            rg = info.get('revenueGrowth')
            if rg: score += min(20, max(0, rg * 100))
            pm = info.get('profitMargins')
            if pm: score += min(15, max(0, pm * 100))
            cr = info.get('currentRatio')
            if cr: score += 10 if 1.5 <= cr <= 3.0 else (5 if cr >= 1.0 else 0)
            de = info.get('debtToEquity')
            if de: score += 15 if de < 30 else (10 if de < 100 else (5 if de < 200 else 0))
            pe = info.get('trailingPE')
            if pe: score += 15 if 10 <= pe <= 20 else (10 if pe < 30 else (5 if pe > 0 else 0))
            fundamental_scores[sym] = min(100, score)
        except: 
            fundamental_scores[sym] = 0
    
    with open(FUND_CACHE, 'w') as f: json.dump(fundamental_scores, f)

# ─── Phase 3: Backtest ────────────────────────────────────────────
print(f"\n📊 Running backtest...", flush=True)

# Monthly evaluation dates
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

print(f"   評估點: {len(eval_dates)} 個月", flush=True)

def get_cum_value(trust_data, date_str, window_name):
    dates = trust_data["dates"]
    vals = trust_data[window_name]
    i = bisect_left(dates, date_str)
    if i >= len(dates) or dates[i] != date_str:
        if i > 0: i -= 1
        else: return None
    v = vals[i]
    return v if v is not None and v > 0 else None

WINDOWS = {"d20": "20日", "d10": "10日", "d5": "5日", "d3": "3日"}
TOP_N_LIST = [10, 20, 50, 100]

results = {}

for top_n in TOP_N_LIST:
    for win_name, win_label in WINDOWS.items():
        for filter_type, min_score in [("投信only", 0), ("基本≥60", 60)]:
            key = f"Top{top_n}_{win_label}_{filter_type}"
            results[key] = {h: [] for h in ["1個月", "3個月", "6個月"]}
            
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
                    if fs < min_score: continue
                    
                    for hold_name, hold_days in [("1個月", 20), ("3個月", 60), ("6個月", 120)]:
                        ret = get_fwd_return(sym, eval_date, hold_days)
                        if ret is not None:
                            results[key][hold_name].append(ret - COST/100)

# ─── Report ────────────────────────────────────────────────────────
# Part 1: Per-TopN detailed table (3-month only)
print(f"\n{'='*140}", flush=True)
print(f"🏆  TOP N 比較：各窗口 3個月持倉（基本≥60）", flush=True)
print(f"{'='*140}", flush=True)
print(f"{'TOP N':>6s} {'窗口':>8s} {'訊號':>6s} {'勝率':>8s} {'均報酬':>9s} {'中位數':>9s} {'夏普':>7s} {'盈虧比':>7s}", flush=True)
print(f"{'─'*140}", flush=True)

for top_n in TOP_N_LIST:
    for win_name, win_label in WINDOWS.items():
        for filter_type, min_score in [("基本≥60", 60)]:
            key = f"Top{top_n}_{win_label}_{filter_type}"
            strat = results.get(key, {})
            arr = np.array(strat.get("3個月", []))
            if len(arr) < 3: continue
            
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            med = np.median(arr)
            wins = arr[arr > 0]; losses = arr[arr < 0]
            avg_win = np.mean(wins) if len(wins) > 0 else 0
            avg_loss = np.mean(losses) if len(losses) > 0 else 0
            rr = abs(avg_win/avg_loss) if avg_loss != 0 else float('inf')
            sharpe = np.mean(arr)/np.std(arr)*np.sqrt(252/60) if np.std(arr) > 0 else 0
            
            print(f"Top{top_n:>4d} {win_label:>8s} {len(arr):>6d} {wr:>7.1%} {avg:>+8.2%} {med:>+8.2%} {sharpe:>7.2f} {rr:>7.2f}", flush=True)

# Part 2: Best of each TopN
print(f"\n{'='*140}", flush=True)
print(f"🎯  各 TOP N 最佳窗口評比（3個月持倉，基本≥60）", flush=True)
print(f"{'='*140}", flush=True)
print(f"{'TOP N':>6s} {'最佳窗口':>10s} {'訊號':>6s} {'勝率':>9s} {'均報酬':>9s} {'中位數':>9s} {'夏普':>7s} {'盈虧比':>7s} {'評分':>7s}", flush=True)
print(f"{'─'*140}", flush=True)

for top_n in TOP_N_LIST:
    best = None
    best_score = -999
    for win_name, win_label in WINDOWS.items():
        key = f"Top{top_n}_{win_label}_基本≥60"
        strat = results.get(key, {})
        arr = np.array(strat.get("3個月", []))
        if len(arr) < 3: continue
        
        wr = np.mean(arr > 0)
        avg = np.mean(arr)
        sharpe = np.mean(arr)/np.std(arr)*np.sqrt(252/60) if np.std(arr) > 0 else 0
        rr = abs(np.mean(arr[arr>0])/np.mean(np.abs(arr[arr<0]))) if np.sum(arr<0)>0 else float('inf')
        sig_score = min(10, np.log10(len(arr)))
        comp = wr * 30 + (sharpe/2)*30 + (rr/3)*20 + (sig_score/10)*20
        
        if comp > best_score:
            best_score = comp
            best = (win_label, arr, wr, avg, rr, sharpe, sig_score)
    
    if best:
        win_label, arr, wr, avg, rr, sharpe, sig_score = best
        med = np.median(arr)
        print(f"Top{top_n:>4d} {win_label:>10s} {len(arr):>6d} {wr:>8.1%} {avg:>+8.2%} {med:>+8.2%} {sharpe:>7.2f} {rr:>7.2f} {best_score:>6.1f}", flush=True)

# Part 3: With vs Without fundamental for each TopN
print(f"\n{'='*140}", flush=True)
print(f"⚠️  投信only vs 基本≥60（各TOP N，最佳窗口，3個月）", flush=True)
print(f"{'='*140}", flush=True)
print(f"{'TOP N':>6s} {'篩選':>10s} {'訊號':>6s} {'勝率':>9s} {'均報酬':>9s} {'夏普':>7s} {'盈虧比':>7s}", flush=True)
print(f"{'─'*140}", flush=True)

for top_n in TOP_N_LIST:
    # Find best window
    for win_name, win_label in WINDOWS.items():
        for filter_type, min_score, flabel in [("投信only", 0, "純投信"), ("基本≥60", 60, "+基本面≥60")]:
            key = f"Top{top_n}_{win_label}_{filter_type}"
            strat = results.get(key, {})
            arr = np.array(strat.get("3個月", []))
            if len(arr) < 3: continue
            
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            sharpe = np.mean(arr)/np.std(arr)*np.sqrt(252/60) if np.std(arr) > 0 else 0
            rr = abs(np.mean(arr[arr>0])/np.mean(np.abs(arr[arr<0]))) if np.sum(arr<0)>0 else float('inf')
            
            print(f"Top{top_n:>4d} {flabel:>10s} {len(arr):>6d} {wr:>8.1%} {avg:>+8.2%} {sharpe:>7.2f} {rr:>7.2f}", flush=True)

# Part 4: Same but for 1-month and 6-month, best of each top N
print(f"\n{'='*140}", flush=True)
print(f"📈  各 TOP N 最佳 — 1個月 vs 3個月 vs 6個月（基本≥60）", flush=True)
print(f"{'='*140}", flush=True)
print(f"{'TOP N':>6s} {'持倉':>6s} {'最佳窗口':>10s} {'訊號':>6s} {'勝率':>9s} {'均報酬':>9s}", flush=True)
print(f"{'─'*140}", flush=True)

for top_n in TOP_N_LIST:
    for hold_name, hold_days in [("1個月", 20), ("3個月", 60), ("6個月", 120)]:
        best = None
        best_wr = -1
        for win_name, win_label in WINDOWS.items():
            key = f"Top{top_n}_{win_label}_基本≥60"
            arr = np.array(results.get(key, {}).get(hold_name, []))
            if len(arr) < 3: continue
            wr = np.mean(arr > 0)
            if wr > best_wr:
                best_wr = wr
                best = (win_label, arr)
        if best:
            win_label, arr = best
            avg = np.mean(arr)
            print(f"Top{top_n:>4d} {hold_name:>6s} {win_label:>10s} {len(arr):>6d} {wr:>8.1%} {avg:>+8.2%}", flush=True)

print(f"\n✅ 完成: {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
