#!/usr/bin/env python3
"""
📊 修正版回測：比照財報狗 — 地雷+成長獨立評分
策略：投信買超 TOP N → 地雷≥80%（排除假帳）→ 成長排序
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
COST = 0.6

print("=" * 120, flush=True)
print("📊 修正版：比照財報狗獨立評分（地雷≥80% + 成長≥60%）")
print(f"📆 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 120, flush=True)

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
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, 'w') as f: json.dump(trust_windows, f)

# ─── Phase 2: 財報狗式評分 ────────────────────────────────────
print(f"\n📡 Phase 2: 財報狗式評分 (成長+地雷獨立)...", flush=True)

def calc_dog_score(sym):
    """
    比照財報狗評分（無便宜股）:
    - 成長股健診(5項): 月營收YOY+毛利+營益+稅前+稅後
    - 地雷股健診(6項): FCF+營運現金流+AR週轉+存貨週轉
    """
    sid = sym.replace(".TW","").replace(".TWO","")
    try:
        info = yf.Ticker(sym).info
    except:
        return 0, 0
    
    g = [False]*5
    l = [False]*6
    
    # g1: 月營收YOY連續三個月>0 (使用 yfinance quarterly revenue)
    try:
        fin = yf.Ticker(sym).financials
        if fin is not None and not fin.empty:
            cols = fin.columns
            if len(cols) >= 5:
                # g2-g5: 毛利/營益/稅前/稅後 YoY
                fields_map = [
                    ('g2', 'Gross Profit'),
                    ('g3', 'Operating Income'),
                    ('g4', 'Pretax Income'),
                    ('g5', 'Net Income')
                ]
                for gkey, field in fields_map:
                    try:
                        if field in fin.index:
                            cur = fin.loc[field, cols[0]]
                            prev = fin.loc[field, cols[4]]
                            if cur is not None and prev is not None and cur > prev:
                                idx = {'g2':1,'g3':2,'g4':3,'g5':4}[gkey]
                                g[idx] = True
                    except:
                        pass
    except:
        pass
    
    # g1: Revenue YoY from income statement
    try:
        if 'Total Revenue' in fin.index:
            cur_r = fin.loc['Total Revenue', cols[0]]
            prev_r = fin.loc['Total Revenue', cols[4]]
            if cur_r is not None and prev_r is not None and cur_r > prev_r:
                g[0] = True
    except:
        pass
    
    # 地雷股健診 (from balance sheet + cash flow)
    try:
        bs = yf.Ticker(sym).balance_sheet
        cf = yf.Ticker(sym).cashflow
        
        if cf is not None and not cf.empty:
            cf_cols = cf.columns
            # l1-l2: Free Cash Flow
            if 'Free Cash Flow' in cf.index:
                fcf_vals = []
                for c in cf_cols[:5]:
                    v = cf.loc['Free Cash Flow', c]
                    if v is not None: fcf_vals.append(v)
                if len(fcf_vals) >= 3:
                    pos = sum(1 for v in fcf_vals if v > 0)
                    if pos >= 3: l[0] = True
                    if sum(fcf_vals)/len(fcf_vals) > 0: l[1] = True
            
            # l3-l4: CFO/NI ratio
            if 'Operating Cash Flow' in cf.index and 'Net Income' in cf.index:
                ratios = []
                for c in cf_cols[:5]:
                    try:
                        cfo = cf.loc['Operating Cash Flow', c]
                        ni = cf.loc['Net Income', c]
                        if ni is not None and ni > 0 and cfo is not None:
                            ratios.append(cfo/ni*100)
                    except: pass
                if len(ratios) >= 3:
                    ok = sum(1 for r in ratios if r > 100)
                    if ok >= 3: l[2] = True
                    if sum(ratios)/len(ratios) > 100: l[3] = True
        
        # l5-l6: AR & Inventory turnover (from balance sheet + income statement)
        if bs is not None and not bs.empty and fin is not None and not fin.empty:
            bs_cols = bs.columns
            for chk_idx, (bs_field, rev_field) in enumerate([
                ('Accounts Receivable', 'Total Revenue'),
                ('Inventory', 'Total Revenue')]):
                try:
                    if bs_field in bs.index:
                        cur_bs = bs.loc[bs_field, bs_cols[0]]
                        prev_bs = bs.loc[bs_field, bs_cols[4]]
                        cur_rev = fin.loc[rev_field, cols[0]] if rev_field in fin.index else None
                        prev_rev = fin.loc[rev_field, cols[4]] if rev_field in fin.index else None
                        if all(v is not None and v != 0 for v in [cur_bs, prev_bs, cur_rev, prev_rev]):
                            d_cur = cur_bs / cur_rev * 365
                            d_prev = prev_bs / prev_rev * 365
                            if d_cur <= d_prev: l[4+chk_idx] = True
                except: pass
    except:
        pass
    
    growth_pct = sum(g) * 20    # 0-100%
    landmine_pct = sum(l) * (100/6)  # 0-100%
    return growth_pct, landmine_pct

# Cache the scores since yfinance calls are slow
SCORE_CACHE = {}
def get_dog_score(sym):
    if sym not in SCORE_CACHE:
        SCORE_CACHE[sym] = calc_dog_score(sym)
    return SCORE_CACHE[sym]

# ─── Phase 3: Backtest ────────────────────────────────────────────
print(f"\n📊 Running backtest...", flush=True)

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
TOP_N_LIST = [10, 20, 50]

# Strategies to test
strategies = [
    # (name, desc, filter_fn)
    ("舊版_總分≥60", "舊版混合≥60", lambda g,l: g + l + 0 >= 60),
    ("地雷≥80_隨機", "財報狗:地雷≥80%，成長隨便", lambda g,l: l >= 80),
    ("地雷≥80_成長≥60", "財報狗:地雷≥80%且成長≥60%", lambda g,l: l >= 80 and g >= 60),
    ("地雷≥80_成長排序", "財報狗:地雷≥80%，按成長排序", lambda g,l: l >= 80),
    ("成長≥60_隨機", "成長≥60%", lambda g,l: g >= 60),
]

results = {}

for top_n in TOP_N_LIST:
    for win_name, win_label in WINDOWS.items():
        for strat_name, strat_desc, filter_fn in strategies:
            key = f"Top{top_n}_{win_label}_{strat_name}"
            results[key] = {"1m": [], "3m": [], "6m": [], "12m": []}
            
            for eval_date in eval_dates:
                ranking = []
                for sym in trust_windows:
                    cum = get_cum_value(trust_windows[sym], eval_date, win_name)
                    if cum is None: continue
                    ranking.append((sym, cum))
                
                ranking.sort(key=lambda x: -x[1])
                if not ranking: continue
                
                # Score candidates
                candidates = []
                for sym, cum in ranking[:top_n]:
                    g_pct, l_pct = get_dog_score(sym)
                    if not filter_fn(g_pct, l_pct): continue
                    if strat_name == "地雷≥80_成長排序":
                        candidates.append((sym, g_pct, cum))
                    else:
                        candidates.append((sym, 0, cum))
                
                # For growth-sorted strategy, take top by growth
                if strat_name == "地雷≥80_成長排序":
                    candidates.sort(key=lambda x: -x[1])
                    # Take top 5 by growth
                    candidates = candidates[:5]
                
                for sym, _, _ in candidates:
                    for hold_name, hold_days in [("1m", 20), ("3m", 60), ("6m", 120), ("12m", 250)]:
                        ret = get_fwd_return(sym, eval_date, hold_days)
                        if ret is not None:
                            results[key][hold_name].append(ret - COST/100)

# ─── Report ────────────────────────────────────────────────────────
print(f"\n{'='*140}", flush=True)
print(f"🏆  修正版：各策略比較（3個月持倉）", flush=True)
print(f"{'='*140}", flush=True)
print(f"{'TOP N':>5s} {'窗口':>6s} {'策略':>18s} {'訊號':>6s} {'勝率':>8s} {'平均':>9s} {'中位數':>9s} {'夏普':>7s} {'盈虧比':>7s}", flush=True)
print(f"{'─'*140}", flush=True)

for top_n in TOP_N_LIST:
    for win_name, win_label in WINDOWS.items():
        for strat_name, strat_desc, _ in strategies:
            key = f"Top{top_n}_{win_label}_{strat_name}"
            arr = np.array(results.get(key, {}).get("3m", []))
            if len(arr) < 3: continue
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            med = np.median(arr)
            wins = arr[arr > 0]; losses = arr[arr < 0]
            rr = abs(np.mean(wins)/np.mean(losses)) if len(losses) > 0 and np.mean(losses) != 0 else float('inf')
            sharpe = np.mean(arr)/np.std(arr)*np.sqrt(252/60) if np.std(arr) > 0 else 0
            print(f"Top{top_n:>2d} {win_label:>6s} {strat_name:>18s} {len(arr):>6d} {wr:>7.1%} {avg:>+8.2%} {med:>+8.2%} {sharpe:>7.2f} {rr:>7.2f}", flush=True)

# Best of each strategy (best window per TOP N)
print(f"\n{'='*140}", flush=True)
print(f"🎯  各TOP N最佳窗口（3個月）", flush=True)
print(f"{'='*140}", flush=True)
print(f"{'TOP N':>5s} {'策略':>18s} {'最佳窗口':>8s} {'訊號':>6s} {'勝率':>8s} {'平均':>9s} {'中位數':>9s} {'夏普':>7s} {'盈虧比':>7s} {'評分':>7s}", flush=True)
print(f"{'─'*140}", flush=True)

for top_n in TOP_N_LIST:
    for strat_name, strat_desc, _ in strategies:
        best = None; best_score = -999
        for win_name, win_label in WINDOWS.items():
            key = f"Top{top_n}_{win_label}_{strat_name}"
            arr = np.array(results.get(key, {}).get("3m", []))
            if len(arr) < 3: continue
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            sharpe = np.mean(arr)/np.std(arr)*np.sqrt(252/60) if np.std(arr) > 0 else 0
            sig_score = min(10, np.log10(len(arr)))
            comp = wr * 30 + (sharpe/2)*30 + (sig_score/10)*20
            if comp > best_score:
                best_score = comp
                best = (win_label, arr)
        if best:
            win_label, arr = best
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            med = np.median(arr)
            sharpe_score = np.mean(arr)/np.std(arr)*np.sqrt(252/60) if np.std(arr) > 0 else 0
            rr = abs(np.mean(arr[arr>0])/np.mean(np.abs(arr[arr<0]))) if np.sum(arr<0)>0 else float('inf')
            print(f"Top{top_n:>2d} {strat_name:>18s} {win_label:>8s} {len(arr):>6d} {wr:>7.1%} {avg:>+8.2%} {med:>+8.2%} {sharpe_score:>7.2f} {rr:>7.2f} {best_score:>6.1f}", flush=True)

# Head-to-head: 舊版 vs 新版
print(f"\n{'='*140}", flush=True)
print(f"⚔️  舊版vs新版（同場較勁，最佳窗口）", flush=True)
print(f"{'='*140}", flush=True)
print(f"{'TOP N':>5s} {'版本':>18s} {'訊號':>6s} {'3月勝率':>9s} {'3月報酬':>9s} {'6月勝率':>9s} {'6月報酬':>9s} {'12月勝率':>9s} {'12月報酬':>9s}", flush=True)
print(f"{'─'*140}", flush=True)

for top_n in [10]:
    hold_configs = [("3m", "3月"), ("6m", "6月"), ("12m", "12月")]
    
    for strat_name, label in [("舊版_總分≥60", "舊版(混合≥60)"), ("地雷≥80_成長≥60", "新版(地雷80+成長60)")]:
        best_win = None
        best_sig = 0
        for win_name, win_label in WINDOWS.items():
            key = f"Top{top_n}_{win_label}_{strat_name}"
            arr = np.array(results.get(key, {}).get("3m", []))
            if len(arr) > best_sig:
                best_sig = len(arr)
                best_win = win_label
        
        if best_win:
            parts = [f"Top{top_n:>2d}", f"{label:>18s}"]
            for hold_key, hold_label in hold_configs:
                key = f"Top{top_n}_{best_win}_{strat_name}"
                arr = np.array(results.get(key, {}).get(hold_key, []))
                if len(arr) >= 3:
                    wr = np.mean(arr > 0)
                    avg = np.mean(arr)
                    parts.append(f"{wr:>8.1%}")
                    parts.append(f"{avg:>+8.2%}")
                else:
                    parts.append(f"{'N/A':>9s}")
                    parts.append(f"{'N/A':>9s}")
            print(' '.join(parts), flush=True)

print(f"\n✅ 完成: {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
