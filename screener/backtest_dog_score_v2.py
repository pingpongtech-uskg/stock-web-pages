#!/usr/bin/env python3
"""
📊 修正版回測 v2：比照財報狗 — 地雷+成長獨立評分
使用 FinMind API（與 cronjob 一致），只評分進過 TOP N 的股票
"""
import sys, os, json, glob, time
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
from FinMind.data import DataLoader
import yfinance as yf
import re, warnings
from bisect import bisect_left
warnings.filterwarnings('ignore')

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
CACHE_FILE = os.path.join(BASE, "output", "trust_cache.json")
FUND_CACHE_NEW = os.path.join(BASE, "output", "dog_score_cache.json")
COST = 0.6

print("=" * 120, flush=True)
print("📊 v2：比照財報狗獨立評分（FinMind API，與 cronjob 一致）")
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

# ─── Phase 2: 財報狗式評分（FinMind API）────────────────────────
print(f"\n📡 Phase 2: 財報狗式評分（FinMind API）...", flush=True)

def fetch_fm(api, table, stock_id, start_date='2019-01-01'):
    fm_wait()
    try:
        return api.taiwan_stock_financial_statement(stock_id=stock_id, start_date=start_date)
    except:
        return None

def fetch_cf(api, stock_id, start_date='2019-01-01'):
    fm_wait()
    try:
        return api.taiwan_stock_cash_flows_statement(stock_id=stock_id, start_date=start_date)
    except:
        return None

def fetch_bs(api, stock_id, start_date='2019-01-01'):
    fm_wait()
    try:
        return api.taiwan_stock_balance_sheet(stock_id=stock_id, start_date=start_date)
    except:
        return None

def fetch_rev(api, stock_id, start_date='2024-01-01'):
    fm_wait()
    try:
        return api.taiwan_stock_month_revenue(stock_id=stock_id, start_date=start_date)
    except:
        return None

# 跟 daily_monitor.py 一致的評分邏輯
def calc_dog_score_fm(api, stock_id):
    """比照財報狗評分（使用 FinMind，與 cronjob 一致）"""
    result = {'g': [False]*5, 'l': [False]*6}
    
    fin = fetch_fm(api, 'financial_statement', stock_id, '2023-01-01')
    cf = fetch_cf(api, stock_id, '2019-01-01')
    bs = fetch_bs(api, stock_id, '2019-01-01')
    rev = fetch_rev(api, stock_id, '2024-01-01')
    
    # g1: 月營收YOY連續三個月>0
    if rev is not None and len(rev) >= 6:
        rs = rev.sort_values('date')
        recent = rs.tail(3)
        yoy_ok = 0
        for _, row in recent.iterrows():
            d = row['date']
            yr_ago = f"{int(d[:4])-1}-{d[5:]}"
            prev = rs[rs['date'] == yr_ago]
            if len(prev) > 0:
                cur_r = float(row['revenue'])
                prev_r = float(prev.iloc[0]['revenue'])
                if prev_r > 0 and cur_r > prev_r:
                    yoy_ok += 1
        if yoy_ok >= 3:
            result['g'][0] = True
    
    # g2-g5: 損益表年增
    if fin is not None and len(fin) > 0:
        fp = defaultdict(dict)
        for _, row in fin.iterrows():
            fp[row['date']][row['type']] = row['value']
        dates = sorted(fp.keys())
        growth_checks = {'g2': 'GrossProfit', 'g3': 'OperatingIncome',
                         'g4': 'PreTaxIncome', 'g5': 'IncomeAfterTaxes'}
        if len(dates) >= 5:
            latest = dates[-1]
            prev_year = dates[-5]
            if prev_year in fp:
                cur, prev = fp[latest], fp[prev_year]
                for key, field in growth_checks.items():
                    if field in cur and field in prev:
                        try:
                            cur_v = float(cur[field])
                            prev_v = float(prev[field])
                            if cur_v > 0 and cur_v > prev_v:
                                idx = {'g2':1,'g3':2,'g4':3,'g5':4}[key]
                                result['g'][idx] = True
                        except: pass
    
    # l1-l4: 現金流
    if cf is not None and len(cf) > 0:
        cfp = defaultdict(dict)
        for _, row in cf.iterrows():
            cfp[row['date']][row['type']] = row['value']
        cf_dates = sorted(cfp.keys())
        
        # FreeCashFlow or CFO - CapEx
        if 'FreeCashFlow' in cfp.get(cf_dates[-1] if cf_dates else '', {}):
            annual_fcf = {}
            for d in cf_dates:
                year = d[:4]
                fcf = float(cfp[d].get('FreeCashFlow', 0) or 0)
                annual_fcf[year] = fcf
            fcf_values = list(annual_fcf.values())
        else:
            annual_fcf = {}
            quarter_counts = {}
            for d in cf_dates:
                year = d[:4]
                cfo = float(cfp[d].get('CashFlowsFromOperatingActivities', 0) or 0)
                capex = float(cfp[d].get('PropertyPlantAndEquipment', 0) or 0)
                fcf = cfo - abs(capex)
                annual_fcf[year] = annual_fcf.get(year, 0) + fcf
                quarter_counts[year] = quarter_counts.get(year, 0) + 1
            fcf_values = [v for y, v in annual_fcf.items() if quarter_counts.get(y, 0) >= 3]
        
        if len(fcf_values) >= 3:
            pos = sum(1 for v in fcf_values if v > 0)
            if pos >= 3: result['l'][0] = True
            if sum(fcf_values)/len(fcf_values) > 0: result['l'][1] = True
        
        # CFO/NI ratio
        if fin is not None and len(fin) > 0:
            fp = defaultdict(dict)
            for _, row in fin.iterrows():
                fp[row['date']][row['type']] = row['value']
            ni_pairs = []
            for d in cf_dates:
                if d in fp:
                    try:
                        cfo = float(cfp[d].get('CashFlowsFromOperatingActivities', 0) or 0)
                        ni = float(fp[d].get('IncomeAfterTaxes', 0) or 0)
                        if ni > 0:
                            ni_pairs.append(cfo / ni * 100)
                    except: pass
            if len(ni_pairs) >= 3:
                ok = sum(1 for r in ni_pairs if r > 100)
                if ok >= 3: result['l'][2] = True
                if sum(ni_pairs)/len(ni_pairs) > 100: result['l'][3] = True
    
    # l5-l6: AR & Inventory turnover
    if bs is not None and len(bs) > 0 and fin is not None and len(fin) > 0:
        bsp = defaultdict(dict)
        for _, row in bs.iterrows():
            bsp[row['date']][row['type']] = row['value']
        bs_dates = sorted(bsp.keys())
        
        fp = defaultdict(dict)
        for _, row in fin.iterrows():
            fp[row['date']][row['type']] = row['value']
        
        for chk_idx, (bs_field, rev_field) in enumerate([
            ('AccountsReceivableNet', 'Revenue'), ('Inventories', 'Revenue')]):
            try:
                l_d = bs_dates[-1]
                l_ym = l_d[:7]
                p_ym = f"{int(l_d[:4])-1}{l_d[4:7]}"
                prev = None
                for d in bs_dates:
                    if d.startswith(p_ym):
                        prev = d; break
                if prev and bs_field in bsp[l_d] and bs_field in bsp[prev]:
                    cur_v = float(bsp[l_d][bs_field])
                    prev_v = float(bsp[prev][bs_field])
                    cur_rev_d = next((d for d in fp if d.startswith(l_ym) and rev_field in fp[d]), None)
                    prev_rev_d = next((d for d in fp if d.startswith(p_ym) and rev_field in fp[d]), None)
                    if cur_rev_d and prev_rev_d:
                        r_cur = float(fp[cur_rev_d][rev_field])
                        r_prev = float(fp[prev_rev_d][rev_field])
                        if r_cur > 0 and r_prev > 0:
                            d_cur = cur_v / r_cur * 365
                            d_prev = prev_v / r_prev * 365
                            if d_cur <= d_prev: result['l'][4+chk_idx] = True
            except: pass
    
    growth_pct = sum(result['g']) * 20
    landmine_pct = sum(result['l']) * (100/6)
    return growth_pct, landmine_pct

# Cache the scores
SCORE_CACHE = {}
def get_dog_score(api, sym):
    if sym not in SCORE_CACHE:
        sid = sym.replace(".TW","").replace(".TWO","")
        SCORE_CACHE[sym] = calc_dog_score_fm(api, sid)
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

WINDOWS = {"d20": "20日", "d10": "10日"}
TOP_N_LIST = [10, 20]

# Strategy filters (比照財報狗獨立評分)
strategies = [
    ("舊版_總分≥60", "舊版混合", lambda g, l: g + l >= 60),
    ("地雷≥80_成長≥60", "財報狗雙門檻", lambda g, l: l >= 80 and g >= 60),
    ("地雷≥80_成長排序", "地雷過濾+成長排序", None),  # special handling
    ("地雷≥80", "僅地雷≥80", lambda g, l: l >= 80),
    ("成長≥60", "僅成長≥60", lambda g, l: g >= 60),
    ("地雷≥60_成長≥40", "寬鬆版", lambda g, l: l >= 60 and g >= 40),
]

results = {}
api = get_api()
scored = 0

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
                
                # Score and filter
                candidates = []
                for sym, cum in ranking[:top_n]:
                    g_pct, l_pct = get_dog_score(api, sym)
                    scored += 1
                    
                    if strat_name == "地雷≥80_成長排序":
                        if l_pct >= 80:
                            candidates.append((sym, g_pct))
                    elif filter_fn(g_pct, l_pct):
                        candidates.append((sym, 0))
                
                # For growth-sorted: take top 5 by growth score
                if strat_name == "地雷≥80_成長排序":
                    candidates.sort(key=lambda x: -x[1])
                    candidates = candidates[:5]
                
                for sym, _, in candidates:
                    for hold_name, hold_days in [("1m", 20), ("3m", 60), ("6m", 120)]:
                        ret = get_fwd_return(sym, eval_date, hold_days)
                        if ret is not None:
                            results[key][hold_name].append(ret - COST/100)

# ─── Report ────────────────────────────────────────────────────────
print(f"\n{'='*130}", flush=True)
print(f"🏆  各策略比較（最佳窗口，3個月持倉）", flush=True)
print(f"{'='*130}", flush=True)
print(f"{'TOP N':>5s} {'策略':>20s} {'窗口':>6s} {'訊號':>6s} {'勝率':>8s} {'平均':>9s} {'中位數':>9s}", flush=True)
print(f"{'─'*130}", flush=True)

for top_n in TOP_N_LIST:
    for strat_name, _, _ in strategies:
        best = None; best_sig = 0
        for win_name, win_label in WINDOWS.items():
            key = f"Top{top_n}_{win_label}_{strat_name}"
            arr = np.array(results.get(key, {}).get("3m", []))
            if len(arr) > best_sig:
                best_sig = len(arr)
                best = (win_label, arr)
        if best and best_sig >= 3:
            win_label, arr = best
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            med = np.median(arr)
            print(f"Top{top_n:>2d} {strat_name:>20s} {win_label:>6s} {len(arr):>6d} {wr:>7.1%} {avg:>+8.2%} {med:>+8.2%}", flush=True)

# 舊版vs新版對決（TOP 10）
print(f"\n{'='*130}", flush=True)
print(f"⚔️  舊版 vs 新版 對決（TOP 10）", flush=True)
print(f"{'='*130}", flush=True)
print(f"{'窗口':>6s} {'策略':>20s} {'3月訊號':>8s} {'3月勝率':>9s} {'3月報酬':>9s} {'6月勝率':>9s} {'6月報酬':>9s}", flush=True)
print(f"{'─'*130}", flush=True)

for win_name, win_label in WINDOWS.items():
    for strat_name, strat_desc, _ in strategies:
        key = f"Top10_{win_label}_{strat_name}"
        for hold_key, hold_label in [("3m", "3月"), ("6m", "6月")]:
            arr = np.array(results.get(key, {}).get(hold_key, []))
            if len(arr) >= 3:
                wr = np.mean(arr > 0)
                avg = np.mean(arr)
                if hold_key == "3m":
                    sig = len(arr)
                    wr3, avg3 = wr, avg
                else:
                    print(f"{win_label:>6s} {strat_name:>20s} {sig:>8d} {wr3:>8.1%} {avg3:>+8.2%} {wr:>8.1%} {avg:>+8.2%}", flush=True)

print(f"\n✅ 完成: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print(f"   評分次數: {scored}")
