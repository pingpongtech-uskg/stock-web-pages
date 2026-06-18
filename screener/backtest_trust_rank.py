#!/usr/bin/env python3
"""
📊 投信買超排行深度比較：TOP 10/20/50/100 + 窗口 3/5/10/20日 + 基本面
使用已快取資料重新計算，不查 API
"""
import sys, os, json, glob, time
from datetime import datetime, timedelta
from collections import OrderedDict, defaultdict
import numpy as np
from bisect import bisect_left
import warnings
warnings.filterwarnings('ignore')

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
CACHE_FILE = os.path.join(BASE, "output", "trust_cache.json")
FUND_CACHE = os.path.join(BASE, "output", "fund_cache.json")
COST = 0.6

print("=" * 110, flush=True)
print("📊 投信買超排行深度比較：TOP 10 vs 20 vs 50 vs 100")
print(f"📆 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("=" * 110, flush=True)

# ─── Load stock price data ──────────────────────────────────────────
print("\n📦 Loading stock data...", flush=True)
stocks = {}
for f in sorted(glob.glob(os.path.join(DATA_DIR, "batch_*.json"))):
    with open(f) as fh:
        batch = json.load(fh)
    for sym, d in batch.items():
        if sym not in stocks and len(d.get("dates", [])) >= 260:
            stocks[sym] = d

sorted_syms = sorted(stocks.keys(), key=lambda s: len(stocks[s]["dates"]), reverse=True)
print(f"   {len(sorted_syms)} stocks in database", flush=True)

# ─── Price lookup ──────────────────────────────────────────────────
print("\n📐 Building price lookup...", flush=True)
stock_prices = {sym: {stocks[sym]["dates"][i]: float(stocks[sym]["close"][i])
                      for i in range(len(stocks[sym]["dates"]))}
                for sym in sorted_syms}
stock_dates = {sym: stocks[sym]["dates"] for sym in sorted_syms}

def get_fwd_return(sym, date_str, hold_days):
    dates = stock_dates.get(sym, [])
    prices = stock_prices.get(sym, {})
    i = bisect_left(dates, date_str)
    if i >= len(dates) or dates[i] != date_str: return None
    j = i + hold_days
    if j >= len(dates): return None
    entry = prices[dates[i]]
    return prices[dates[j]] / entry - 1 if entry > 0 else None

# ─── Load cached 投信 data ─────────────────────────────────────────
print(f"\n📦 Loading cached 投信 data...", flush=True)
with open(CACHE_FILE) as f:
    trust_windows = json.load(f)
print(f"   {len(trust_windows)} stocks loaded from cache", flush=True)

# Load cached fundamental data
with open(FUND_CACHE) as f:
    fundamental_scores = json.load(f)
print(f"   {len(fundamental_scores)} fundamentals loaded", flush=True)

# ─── Monthly evaluation dates ──────────────────────────────────────
eval_dates = []
dates_set = set(stock_dates.get(sorted_syms[0], []))
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

print(f"   評估點: {len(eval_dates)} 個月 (2015-2025)", flush=True)

def get_cum_value(trust_data, date_str, window_name):
    dates = trust_data["dates"]
    vals = trust_data[window_name]
    i = bisect_left(dates, date_str)
    if i >= len(dates) or dates[i] != date_str:
        if i > 0: i -= 1
        else: return None
    v = vals[i]
    return v if v is not None and v > 0 else None

WINDOWS = {"d3": "3日", "d5": "5日", "d10": "10日", "d20": "20日"}
TOP_LIST = [10, 20, 50, 100]
HOLDINGS = [("1個月", 20), ("3個月", 60), ("6個月", 120)]

# ─── Run backtest for all rank thresholds ──────────────────────────
print(f"\n{'='*110}", flush=True)
print("🏆  全部組合測試中...", flush=True)
print(f"{'='*110}", flush=True)

results = {}

for win_name, win_label in WINDOWS.items():
    for top_n in TOP_LIST:
        for filter_type, min_score in [("投信only", 0), ("基本≥60", 60)]:
            key = f"Top{top_n}_{win_label}_{filter_type}"
            results[key] = {h: [] for h, _ in HOLDINGS}
            
            for eval_date in eval_dates:
                # Rank by this window's cumulative 投信 net buy
                ranking = []
                for sym in trust_windows:
                    cum = get_cum_value(trust_windows[sym], eval_date, win_name)
                    if cum is None: continue
                    ranking.append((sym, cum))
                
                ranking.sort(key=lambda x: -x[1])
                if not ranking: continue
                
                # Take top N
                count = 0
                for sym, cum in ranking:
                    fs = fundamental_scores.get(sym, 0)
                    if fs < min_score: continue
                    count += 1
                    if count > top_n: break  # 排名限制是對「通過基本面篩選後的股票」
                    
                    for hold_name, hold_days in HOLDINGS:
                        ret = get_fwd_return(sym, eval_date, hold_days)
                        if ret is not None:
                            results[key][hold_name].append(ret - COST/100)

# ═══ REPORT: ALL RANKS COMPARISON ═══════════════════════════════════
print(f"\n{'='*110}", flush=True)
print(f"📊 【主要：所有排名區間對比 — 持有3個月】", flush=True)
print(f"{'='*110}", flush=True)

hdr = f"{'窗口':>4s} {'排名':>5s} {'篩選':>10s}"
hdr += f" {'訊號':>6s} {'勝率':>8s} {'均報酬':>10s} {'中位數':>10s} {'夏普':>8s} {'盈虧比':>8s} {'EV/月':>8s}"
print(hdr)
print(f"{'─'*110}")

all_scores = []
for win_name, win_label in WINDOWS.items():
    for top_n in TOP_LIST:
        for filter_type, min_score in [("投信only", 0), ("基本≥60", 60)]:
            key = f"Top{top_n}_{win_label}_{filter_type}"
            strat = results.get(key, {})
            arr = np.array(strat.get("3個月", []))
            if len(arr) < 5: continue
            
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            med = np.median(arr)
            wins = arr[arr > 0]; losses = arr[arr < 0]
            avg_win = np.mean(wins) if len(wins) > 0 else 0
            avg_loss = np.mean(losses) if len(losses) > 0 else 0
            rr = abs(avg_win/avg_loss) if avg_loss != 0 else float('inf')
            sharpe = np.mean(arr)/np.std(arr)*np.sqrt(252/60) if np.std(arr) > 0 else 0
            ev_monthly = np.mean(arr) / 3  # 3-month → monthly
            
            # Composite score (0-100)
            sig_score = min(10, max(0, np.log10(len(arr)) / np.log10(300) * 10))  # normalized
            wr_score = wr * 50
            ev_score = min(30, ev_monthly * 100 * 10)  # 1% monthly = 10pts
            rr_score = min(20, rr * 5)
            comp = wr_score + ev_score + rr_score
            
            all_scores.append((comp, win_label, top_n, filter_type, len(arr), wr, avg, med, sharpe, rr, ev_monthly))
            
            print(f"{win_label:>4s} Top{top_n:>3d} {filter_type:>10s} {len(arr):>6d} {wr:>7.1%} {avg:>+9.2%} {med:>+9.2%} {sharpe:>7.2f} {rr:>7.2f} {ev_monthly:>+7.2%}")

# ═══ RANKING ═══
print(f"\n{'='*110}", flush=True)
print(f"🏆 【總排名：所有組合評分排序】", flush=True)
print(f"{'='*110}", flush=True)

all_scores.sort(key=lambda x: -x[0])

medals = ["🥇", "🥈", "🥉"]
for rank, (comp, win_label, top_n, filter_type, n, wr, avg, med, sharpe, rr, ev_m) in enumerate(all_scores):
    if rank < 10:  # top 10 overall
        medal = medals[rank] if rank < 3 else f"  #{rank+1}"
        print(f"{medal} Win={win_label:>4s} Top{top_n:>3d} {filter_type:>10s}: 綜合{comp:>5.1f}分 | n={n:>4d} | 勝率={wr:>5.1%} | 報酬={avg:>+7.2%}/季 | 夏普={sharpe:.2f} | EV={ev_m:>+5.2%}/月")

# ═══ BEST BY RANK THRESHOLD ═══
print(f"\n{'='*110}", flush=True)
print(f"🎯 【最佳窗口 for each TOP_N 門檻 — 含基本面≥60】", flush=True)
print(f"{'='*110}", flush=True)

for top_n in TOP_LIST:
    best = None
    best_comp = -999
    for win_name, win_label in WINDOWS.items():
        key = f"Top{top_n}_{win_label}_基本≥60"
        strat = results.get(key, {})
        arr = np.array(strat.get("3個月", []))
        if len(arr) < 5: continue
        wr = np.mean(arr > 0)
        avg = np.mean(arr)
        sharpe = np.mean(arr)/np.std(arr)*np.sqrt(252/60) if np.std(arr) > 0 else 0
        wr_score = wr * 50
        ev_score = min(30, (avg/3) * 100 * 10)
        comp = wr_score + ev_score + min(10, np.log10(len(arr))/np.log10(300)*10)
        if comp > best_comp:
            best_comp = comp
            best = (win_label, len(arr), wr, avg, sharpe, comp)
    
    if best:
        print(f"  Top{top_n:>3d} 最佳窗口: {best[0]:>4s} | n={best[1]:>4d} | 勝率={best[2]:>5.1%} | 報酬={best[3]:>+7.2%}/季 | 夏普={best[4]:.2f} | 綜合{best[5]:.1f}分")

# ═══ KEY INSIGHT: RANK vs WIN RATE ─────────────────────────────────
print(f"\n{'='*110}", flush=True)
print(f"🔑 【關鍵發現：排名門檻 vs 勝率趨勢 (基本≥60)】", flush=True)
print(f"{'='*110}", flush=True)

for win_name, win_label in WINDOWS.items():
    line = f"  {win_label}: "
    for top_n in TOP_LIST:
        key = f"Top{top_n}_{win_label}_基本≥60"
        arr = np.array(results.get(key, {}).get("3個月", []))
        if len(arr) >= 5:
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            line += f"Top{top_n:>3d}=勝率{wr:>4.1%}({avg:>+5.2%})  "
        else:
            line += f"Top{top_n:>3d}=N/A  "
    print(line)

# ═══ WITHOUT FUNDAMENTAL ───────────────────────────────────────────
print(f"\n{'='*110}", flush=True)
print(f"🔍 【對照：純投信買超（無基本面）】", flush=True)
print(f"{'='*110}", flush=True)

for win_name, win_label in WINDOWS.items():
    line = f"  {win_label}: "
    for top_n in TOP_LIST:
        key = f"Top{top_n}_{win_label}_投信only"
        arr = np.array(results.get(key, {}).get("3個月", []))
        if len(arr) >= 5:
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            line += f"Top{top_n:>3d}=勝率{wr:>4.1%}({avg:>+5.2%})  "
        else:
            line += f"Top{top_n:>3d}=N/A  "
    print(line)

# ═══ DECAY ANALYSIS ────────────────────────────────────────────────
print(f"\n{'='*110}", flush=True)
print(f"📉 【衰減分析：從 TOP10 → 100 的勝率衰減】", flush=True)
print(f"{'='*110}", flush=True)

for win_name, win_label in WINDOWS.items():
    base_key = f"Top10_{win_label}_基本≥60"
    base_arr = np.array(results.get(base_key, {}).get("3個月", []))
    base_wr = np.mean(base_arr > 0) if len(base_arr) >= 5 else 0
    
    line = f"  {win_label}: Top10={base_wr:.1%}"
    for top_n in TOP_LIST:
        if top_n == 10: continue
        key = f"Top{top_n}_{win_label}_基本≥60"
        arr = np.array(results.get(key, {}).get("3個月", []))
        if len(arr) >= 5:
            wr = np.mean(arr > 0)
            delta = wr - base_wr
            arrow = "📈" if delta > 0 else "📉"
            line += f" → Top{top_n}={wr:.1%}({delta:+.1%}{arrow})"
    print(line)

# ═══ MONTHLY EVOLUTION ─────────────────────────────────────────────
print(f"\n{'='*110}", flush=True)
print(f"📅 【年度績效：20日窗口 + 基本≥60】", flush=True)
print(f"{'='*110}", flush=True)

years = list(range(2015, 2026))
for top_n in TOP_LIST:
    line = f"  Top{top_n:>3d}: "
    for year in years:
        key = f"Top{top_n}_20日_基本≥60"
        strat = results.get(key, {})
        arr = np.array([r for i, r in enumerate(strat.get("3個月", []))
                        if i < len(eval_dates) and eval_dates[i][:4] == str(year)])
        if len(arr) >= 3:
            line += f"{year}={np.mean(arr>0):.0%}({np.mean(arr):+.1%}) "
    print(line)

print(f"\n✅ 完成: {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
