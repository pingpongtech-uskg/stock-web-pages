#!/usr/bin/env python3
"""
📊 投信20日買超排行 + 基本面綜合篩選 — 量化回測

策略：
1. 每月底，計算所有股票 20 日投信累積買超金額
2. 取買超金額 Top 20 名
3. 篩選基本面綜合評分 ≥ 60（銀獎標準）
4. 持有 1個月 / 3個月 / 6個月
5. 比較：有基本面 vs 無基本面 filter
"""

import sys, os, json, glob, time
from datetime import datetime, timedelta
from collections import OrderedDict, defaultdict
import numpy as np
from FinMind.data import DataLoader
import yfinance as yf
import re, warnings
warnings.filterwarnings('ignore')

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
COST = 0.6

print("=" * 100, flush=True)
print("📊 投信20日買超排行 + 基本面綜合篩選 — 回測")
print(f"📆 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 100, flush=True)

# ─── Rate-limited API ──────────────────────────────────────────────
_fm_calls = []
def fm_wait():
    now = time.time()
    while _fm_calls and now - _fm_calls[0] > 3600:
        _fm_calls.pop(0)
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

# ─── 1. Data Loading ──────────────────────────────────────────────
print("\n📦 Loading stock data...", flush=True)
stocks = {}
for f in sorted(glob.glob(os.path.join(DATA_DIR, "batch_*.json"))):
    with open(f) as fh:
        batch = json.load(fh)
    for sym, d in batch.items():
        if sym not in stocks and len(d.get("dates", [])) >= 260:
            stocks[sym] = d

sorted_syms = sorted(stocks.keys(), key=lambda s: len(stocks[s]["dates"]), reverse=True)
symbols = sorted_syms[:100]  # 100 stocks for speed
print(f"   {len(stocks)} total, using top {len(symbols)}", flush=True)

# ─── 2. Forward Returns from Batch Data ──────────────────────────
print("\n📐 Computing forward returns...", flush=True)
# Build a date→stock→price lookup for fast forward return computation
# We need: for any stock at any date, what's the price N days later?
# Strategy: pre-compute a price matrix

from bisect import bisect_left

stock_prices = {}  # {symbol: {date: close}}
stock_dates = {}   # {symbol: [sorted_dates]}

for sym in symbols:
    d = stocks[sym]
    prices = {d["dates"][i]: float(d["close"][i]) for i in range(len(d["dates"]))}
    stock_prices[sym] = prices
    stock_dates[sym] = d["dates"]

def get_fwd_return(sym, date_str, hold_days):
    """Get forward return for holding N trading days."""
    dates = stock_dates.get(sym, [])
    prices = stock_prices.get(sym, {})
    if not dates or not prices:
        return None
    
    i = bisect_left(dates, date_str)
    if i >= len(dates) or dates[i] != date_str:
        return None  # exact date not found
    
    j = i + hold_days
    if j >= len(dates):
        return None  # not enough forward data
    
    entry = prices[dates[i]]
    exit_p = prices[dates[j]]
    if entry <= 0:
        return None
    
    return exit_p / entry - 1

# ─── 3. Phase 1: Get 投信 data from FinMind ─────────────────────
print("\n📡 Phase 1: 查 投信 買賣超歷史 (150 stocks)...", flush=True)
api = get_api()

trust_history = {}  # {symbol: DataFrame with date, cum_20d_net_buy}

for idx, sym in enumerate(symbols):
    fm_wait()
    sid = sym.replace(".TW","").replace(".TWO","")
    
    if idx % 20 == 0:
        print(f"   [{idx}/{len(symbols)}] 投信 queries...", flush=True)
    
    try:
        df = api.taiwan_stock_institutional_investors(
            stock_id=sid, start_date="2014-01-01", end_date="2025-12-31"
        )
        if df is not None and not df.empty:
            trust_df = df[df['name']=='Investment_Trust'].copy()
            if not trust_df.empty:
                trust_df = trust_df.sort_values('date')
                trust_df['net_buy'] = trust_df['buy'] - trust_df['sell']
                trust_df['20d_cum'] = trust_df['net_buy'].rolling(20, min_periods=10).sum()
                trust_history[sym] = trust_df[['date','net_buy','20d_cum']]
    except:
        pass

print(f"   取得 {len(trust_history)}/{len(symbols)} 檔投信資料", flush=True)

# ─── 4. Phase 2: Get fundamental data from yfinance ──────────────
print("\n📡 Phase 2: 查 基本面 數據...", flush=True)

def quick_fundamental_score(sym):
    """Compute a quick fundamental score from yfinance.info (0-100)."""
    try:
        time.sleep(0.3)  # rate limit
        t = yf.Ticker(sym)
        info = t.info
        
        score = 0
        details = {}
        
        # ROE (max 25 pts)
        roe = info.get('returnOnEquity')
        if roe:
            roe_score = min(25, max(0, roe * 100))
            score += roe_score
            details['ROE'] = f"{roe*100:.0f}%"
        else:
            details['ROE'] = "N/A"
        
        # Revenue Growth (max 20 pts)
        rg = info.get('revenueGrowth')
        if rg:
            rg_score = min(20, max(0, rg * 100))
            score += rg_score
            details['RG'] = f"{rg*100:.0f}%"
        else:
            details['RG'] = "N/A"
        
        # Profit Margin (max 15 pts)
        pm = info.get('profitMargins')
        if pm:
            pm_score = min(15, max(0, pm * 100))
            score += pm_score
            details['PM'] = f"{pm*100:.0f}%"
        else:
            details['PM'] = "N/A"
        
        # Current Ratio (max 10 pts, ideal 1.5-3.0)
        cr = info.get('currentRatio')
        if cr:
            if 1.5 <= cr <= 3.0:
                cr_score = 10
            elif cr >= 1.0:
                cr_score = 5
            else:
                cr_score = 0
            score += cr_score
            details['CR'] = f"{cr:.1f}"
        else:
            details['CR'] = "N/A"
        
        # Debt/Equity (max 15 pts, lower is better)
        de = info.get('debtToEquity')
        if de:
            if de < 30:
                de_score = 15
            elif de < 100:
                de_score = 10
            elif de < 200:
                de_score = 5
            else:
                de_score = 0
            score += de_score
            details['D/E'] = f"{de:.0f}"
        else:
            details['D/E'] = "N/A"
        
        # PE ratio (max 15 pts, 10-20 is ideal)
        pe = info.get('trailingPE')
        if pe:
            if 10 <= pe <= 20:
                pe_score = 15
            elif pe < 30:
                pe_score = 10
            elif pe > 0:
                pe_score = 5
            else:
                pe_score = 0
            score += pe_score
            details['PE'] = f"{pe:.0f}"
        else:
            details['PE'] = "N/A"
        
        return min(100, score), details
    except:
        return 0, {}

# Compute scores for top 100 stocks (skip the rest for speed)
fundamental_scores = {}
target_syms = [s for s in symbols if s in trust_history][:100]
for idx, sym in enumerate(target_syms):
    if idx % 20 == 0:
        print(f"   [{idx}/{len(target_syms)}] fundamental queries...", flush=True)
    score, details = quick_fundamental_score(sym)
    fundamental_scores[sym] = {"score": score, "details": details}

print(f"   取得 {len(fundamental_scores)} 檔基本面分數", flush=True)

# ─── 5. Backtest ──────────────────────────────────────────────────
print("\n" + "=" * 100, flush=True)
print("📊 階段 3: 執行策略回測", flush=True)
print("=" * 100, flush=True)

# Generate monthly evaluation dates
# Last trading day of each month, 2015-2025
from calendar import monthrange

eval_dates = []
dates_set = set(stock_dates[symbols[0]])  # use first stock's dates as reference
for year in range(2015, 2026):
    for month in range(1, 13):
        last_day = monthrange(year, month)[1]
        candidate = f"{year}-{month:02d}-{last_day:02d}"
        # Walk backwards to last trading day
        while candidate not in dates_set and int(candidate[-2:]) > 0:
            d = datetime.strptime(candidate, "%Y-%m-%d")
            d -= timedelta(days=1)
            candidate = d.strftime("%Y-%m-%d")
        if candidate in dates_set:
            eval_dates.append(candidate)

print(f"   月評估點: {len(eval_dates)} 個月 ({eval_dates[0]}~{eval_dates[-1]})", flush=True)

# Categories to test
results = defaultdict(lambda: defaultdict(list))

for eval_idx, eval_date in enumerate(eval_dates):
    if eval_idx % 24 == 0:
        print(f"   [{eval_idx}/{len(eval_dates)}] months processed...", flush=True)
    
    # For each stock with 投信 data, get 20-day cumulative net buy on this date
    trust_rank = []
    for sym in trust_history:
        df = trust_history[sym]
        row = df[df['date'] == eval_date]
        if row.empty:
            # Find the nearest date before eval_date
            sub = df[df['date'] <= eval_date]
            if sub.empty: continue
            row = sub.tail(1)
        
        cum = row['20d_cum'].values[0]
        if np.isnan(cum) or cum <= 0:
            continue  # no 投信 buying
        
        trust_rank.append((sym, cum))
    
    # Sort by 20-day cumulative 投信 net buy
    trust_rank.sort(key=lambda x: -x[1])
    
    if not trust_rank:
        continue
    
    # Take top 20
    top20 = trust_rank[:20]
    
    # Also take top 10 for comparison
    top10 = trust_rank[:10]
    
    for top_stocks, label in [(top10, "Top10"), (top20, "Top20")]:
        # Strategy A: Just 投信 (no fundamental filter)
        for sym, cum in top_stocks:
            for hold_name, hold_days in [("1個月", 20), ("3個月", 60), ("6個月", 120)]:
                ret = get_fwd_return(sym, eval_date, hold_days)
                if ret is not None:
                    net_ret = ret - COST/100  # 0.6% round-trip cost
                    results[f"{label}_投信only"][hold_name].append(net_ret)
        
        # Strategy B: 投信 + 基本面 filter ≥ 60
        qualified = [(sym, cum) for sym, cum in top_stocks 
                     if sym in fundamental_scores and fundamental_scores[sym]["score"] >= 60]
        
        for sym, cum in qualified:
            for hold_name, hold_days in [("1個月", 20), ("3個月", 60), ("6個月", 120)]:
                ret = get_fwd_return(sym, eval_date, hold_days)
                if ret is not None:
                    net_ret = ret - COST/100
                    results[f"{label}_投信+基本≥60"][hold_name].append(net_ret)
        
        # Strategy C: 投信 + 基本面 filter ≥ 80 (金獎)
        qualified_80 = [(sym, cum) for sym, cum in top_stocks 
                        if sym in fundamental_scores and fundamental_scores[sym]["score"] >= 80]
        
        for sym, cum in qualified_80:
            for hold_name, hold_days in [("1個月", 20), ("3個月", 60), ("6個月", 120)]:
                ret = get_fwd_return(sym, eval_date, hold_days)
                if ret is not None:
                    net_ret = ret - COST/100
                    results[f"{label}_投信+基本≥80"][hold_name].append(net_ret)

# ─── 6. Report ────────────────────────────────────────────────────
print("\n" + "=" * 120, flush=True)
print("🏆  投信20日買超排行 + 基本面篩選 — 11年回測結果", flush=True)
print(f"   期程: {eval_dates[0]} ~ {eval_dates[-1]}", flush=True)
print("=" * 120, flush=True)

for strategy_label in ["Top10_投信only", "Top10_投信+基本≥60", "Top10_投信+基本≥80",
                       "Top20_投信only", "Top20_投信+基本≥60", "Top20_投信+基本≥80"]:
    strat = results.get(strategy_label, {})
    if not strat:
        continue
    
    print(f"\n{'─'*80}")
    print(f"📌 {strategy_label}")
    print(f"{'─'*80}")
    print(f"{'持倉':>6s} {'訊號':>6s} {'勝率':>8s} {'均報酬':>9s} {'中位數':>9s} {'夏普':>8s} {'盈虧比':>8s} {'均贏':>9s} {'均損':>9s}")
    print(f"{'─'*80}")
    
    for hold_name in ["1個月", "3個月", "6個月"]:
        arr = strat.get(hold_name, [])
        if len(arr) < 3:
            print(f"  {hold_name:>6s} 樣本不足 ({len(arr)})")
            continue
        
        arr_np = np.array(arr)
        wr = np.mean(arr_np > 0)
        avg = np.mean(arr_np)
        med = np.median(arr_np)
        wins = arr_np[arr_np > 0]
        losses = arr_np[arr_np < 0]
        avg_win = np.mean(wins) if len(wins) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0
        rr = abs(avg_win/avg_loss) if avg_loss != 0 else float('inf')
        
        # Annualized Sharpe (rough approximation)
        n_days = {"1個月": 20, "3個月": 60, "6個月": 120}[hold_name]
        sharpe = (np.mean(arr_np) / np.std(arr_np)) * np.sqrt(252/n_days) if np.std(arr_np) > 0 else 0
        
        print(f"  {hold_name:>6s} {len(arr):>6d} {wr:>7.1%} {avg:>+8.2%} {med:>+8.2%} {sharpe:>7.2f} {rr:>7.2f} {avg_win:>+8.2%} {avg_loss:>+8.2%}", flush=True)

# Essential comparison
print(f"\n{'='*120}", flush=True)
print(f"🎯 核心比較：投信Top20 + 基本面 filter 效果", flush=True)
print(f"{'='*120}", flush=True)
print(f"{'策略':<35s} {'1月勝率':>8s} {'1月報酬':>9s} {'3月勝率':>8s} {'3月報酬':>9s} {'6月勝率':>8s} {'6月報酬':>10s} {'訊號':>8s}")
print(f"{'─'*120}", flush=True)

for strategy_label in ["Top10_投信only", "Top10_投信+基本≥60", "Top10_投信+基本≥80",
                       "Top20_投信only", "Top20_投信+基本≥60", "Top20_投信+基本≥80"]:
    strat = results.get(strategy_label, {})
    if not strat:
        continue
    sigs = len(strat.get("1個月", []))
    wr1 = np.mean(np.array(strat["1個月"]) > 0) if len(strat.get("1個月", [])) > 0 else 0
    avg1 = np.mean(strat["1個月"]) if len(strat.get("1個月", [])) > 0 else 0
    wr3 = np.mean(np.array(strat["3個月"]) > 0) if len(strat.get("3個月", [])) > 0 else 0
    avg3 = np.mean(strat["3個月"]) if len(strat.get("3個月", [])) > 0 else 0
    wr6 = np.mean(np.array(strat["6個月"]) > 0) if len(strat.get("6個月", [])) > 0 else 0
    avg6 = np.mean(strat["6個月"]) if len(strat.get("6個月", [])) > 0 else 0
    print(f"{strategy_label:<35s} {wr1:>7.1%} {avg1:>+8.2%} {wr3:>7.1%} {avg3:>+8.2%} {wr6:>7.1%} {avg6:>+9.2%} {sigs:>7d}", flush=True)

print(f"\n✅ 完成: {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
