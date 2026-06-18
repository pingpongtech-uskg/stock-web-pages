#!/usr/bin/env python3
"""
📊 雷老闆「週線法人初建倉」策略回測 v2 — 更高效
"""
import sys, os, json, glob, time
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
from FinMind.data import DataLoader
import re

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
COST = 0.6

def get_finmind_api():
    src = os.path.join(BASE, "scripts", "download_otc_prices.py")
    with open(src) as f:
        content = f.read()
    for m in re.finditer(r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+', content):
        token = m.group(); break
    api = DataLoader(); api.login_by_token(api_token=token)
    return api

def load_stocks():
    stocks = {}
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "batch_*.json"))):
        with open(f) as fh:
            batch = json.load(fh)
        for sym, d in batch.items():
            if sym not in stocks and len(d.get("dates", [])) >= 260:
                stocks[sym] = d
    return stocks

def to_weekly(dates, closes, volumes):
    weekly = {}
    for i, d in enumerate(dates):
        dt = datetime.strptime(d, "%Y-%m-%d")
        yr, wk, _ = dt.isocalendar()
        key = (yr, wk)
        if key not in weekly:
            weekly[key] = {"date": d, "close": closes[i], "volume": volumes[i], "count": 1}
        else:
            w = weekly[key]; w["close"] = closes[i]; w["volume"] += volumes[i]; w["date"] = d; w["count"] += 1
    return weekly

def compute_weekly_returns(symbols, stocks):
    """Compute VR and forward returns for all symbols. No API calls."""
    all_results = []
    for sym in symbols:
        d = stocks[sym]
        weekly = to_weekly(d["dates"], d["close"], d["volume"])
        keys = sorted(weekly.keys())
        n = len(keys)
        if n < 30: continue
        
        closes = np.array([weekly[k]["close"] for k in keys])
        volumes = np.array([weekly[k]["volume"] for k in keys])
        dates = [weekly[k]["date"] for k in keys]
        
        # Exclusive volume MA10
        vol_ma10 = np.full(n, np.nan)
        for i in range(10, n):
            vol_ma10[i] = np.mean(volumes[i-10:i])
        
        # Volume Ratio
        vr = np.full(n, np.nan)
        for i in range(10, n):
            vr[i] = volumes[i] / vol_ma10[i] if vol_ma10[i] > 0 else 0
        
        # Forward returns
        fwd_4 = np.full(n, np.nan)
        fwd_8 = np.full(n, np.nan)
        fwd_12 = np.full(n, np.nan)
        for i in range(n - 12):
            fwd_4[i] = closes[i+4]/closes[i] - 1
            fwd_8[i] = closes[i+8]/closes[i] - 1
            fwd_12[i] = closes[i+12]/closes[i] - 1
        
        # Price position in 52w
        pct_52w = np.full(n, np.nan)
        for i in range(51, n):
            lo, hi = np.min(closes[i-51:i+1]), np.max(closes[i-51:i+1])
            if hi > lo: pct_52w[i] = (closes[i]-lo)/(hi-lo)
        
        # Collect signals
        for i in range(20, n):
            if dates[i] < "2015-01-01" or dates[i] > "2025-12-31":
                continue
            if np.isnan(vr[i]) or vr[i] < 2.0:
                continue
            if np.isnan(fwd_12[i]):
                continue
            
            all_results.append({
                "symbol": sym,
                "date": dates[i],
                "vr": round(vr[i], 2),
                "close": round(closes[i], 2),
                "pct_52w": round(pct_52w[i], 3) if not np.isnan(pct_52w[i]) else None,
                "r4": round(fwd_4[i], 4),
                "r8": round(fwd_8[i], 4),
                "r12": round(fwd_12[i], 4),
            })
    
    return all_results

def get_institutional_data(symbols, api):
    """Query FinMind for institutional data. Returns {symbol: DataFrame}."""
    result = {}
    rate_times = []
    total = len(symbols)
    
    for idx, sym in enumerate(symbols):
        # Rate limiter
        now = time.time()
        while rate_times and now - rate_times[0] > 3600:
            rate_times.pop(0)
        if len(rate_times) >= 400:
            wait = rate_times[0] + 3600 - now
            if wait > 0: time.sleep(wait)
        if rate_times:
            gap = 5.0 - (now - rate_times[-1])
            if gap > 0: time.sleep(gap)
        rate_times.append(time.time())
        
        if idx % 10 == 0:
            print(f"   [{idx}/{total}] institutional queries...", flush=True)
        
        stock_id = sym.replace(".TW", "").replace(".TWO", "")
        try:
            df = api.taiwan_stock_institutional_investors(
                stock_id=stock_id, start_date="2015-01-01", end_date="2025-12-31"
            )
            if df is not None and not df.empty:
                result[sym] = df
        except Exception:
            pass
    
    print(f"   Got institutional data for {len(result)}/{total} symbols", flush=True)
    return result

def check_inst_week(df, date_str, name):
    """Check if a specific institution net bought in the week of date_str."""
    df = df[df["date"] <= date_str].copy()
    if df.empty: return 0
    df = df[df["name"] == name]
    if df.empty: return 0
    df = df.sort_values("date")
    recent = df.tail(5)
    net = (recent["buy"] - recent["sell"]).sum()
    return max(0, net)  # Only positive net buy counts

def check_inst_consecutive(df, date_str, name, days=3):
    """Check consecutive net buying."""
    df = df[df["date"] <= date_str].copy()
    if df.empty: return False
    df = df[df["name"] == name]
    if df.empty: return False
    df = df.sort_values("date")
    recent = df.tail(days)
    if len(recent) < days: return False
    return (recent["buy"] - recent["sell"] > 0).all()

def check_inst_accumulating(df, date_str, name, lookback_weeks=8):
    """Check if institution is ACCUMULATING over recent weeks (not just 1 week).
    Returns True if cumulative net buy over lookback weeks is > 0 and trending up."""
    df = df[df["date"] <= date_str].copy()
    if df.empty: return False
    df = df[df["name"] == name]
    if df.empty: return False
    df = df.sort_values("date")
    
    # Last lookback_weeks * 5 trading days
    n_days = lookback_weeks * 5
    recent = df.tail(n_days)
    if len(recent) < n_days // 2: return False  # need at least half
    
    recent["net_buy"] = recent["buy"] - recent["sell"]
    total_net = recent["net_buy"].sum()
    
    # Check if recent buying trend is positive
    # Split into 2 halves and compare
    mid = len(recent) // 2
    first_half = recent.iloc[:mid]["net_buy"].sum()
    second_half = recent.iloc[mid:]["net_buy"].sum()
    
    return total_net > 0 and second_half > first_half

def main():
    print("=" * 100, flush=True)
    print("📊 雷老闆週線法人初建倉 — 量化回測 v2", flush=True)
    print(f"📆 {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)
    print("=" * 100, flush=True)
    
    print("\n📦 Loading data...", flush=True)
    stocks = load_stocks()
    sorted_syms = sorted(stocks.keys(), key=lambda s: len(stocks[s]["dates"]), reverse=True)
    symbols = sorted_syms[:80]  # 80 stocks for speed
    print(f"   {len(stocks)} total, using top {len(symbols)}", flush=True)
    
    print("\n📐 Computing weekly VR signals...", flush=True)
    signals = compute_weekly_returns(symbols, stocks)
    print(f"   Found {len(signals)} VR≥2.0 signals across {200} stocks (2015-2025)", flush=True)
    
    # Group by symbol
    sym_signals = defaultdict(list)
    for s in signals:
        sym_signals[s["symbol"]].append(s)
    
    print(f"   Affected symbols: {len(sym_signals)}", flush=True)
    
    # ── Phase 2: Get institutional data ──
    print("\n📡 Fetching institutional data (rate-limited)...", flush=True)
    api = get_finmind_api()
    sig_symbols = list(sym_signals.keys())
    inst_cache = get_institutional_data(sig_symbols, api)
    
    # ── Phase 3: Classify signals by institutional activity ──
    print("\n🔬 Classifying signals...", flush=True)
    
    classifications = defaultdict(list)
    
    for s in signals:
        sym = s["symbol"]
        date = s["date"]
        df = inst_cache.get(sym)
        if df is None:
            continue
        
        inst_trust_buy = check_inst_week(df, date, "Investment_Trust")
        foreign_buy = check_inst_week(df, date, "Foreign_Investor")
        trust_consec3 = check_inst_consecutive(df, date, "Investment_Trust", 3)
        trust_consec5 = check_inst_consecutive(df, date, "Investment_Trust", 5)
        foreign_consec3 = check_inst_consecutive(df, date, "Foreign_Investor", 3)
        trust_accum = check_inst_accumulating(df, date, "Investment_Trust", 8)
        foreign_accum = check_inst_accumulating(df, date, "Foreign_Investor", 8)
        
        # Determine zone
        pct = s["pct_52w"]
        zone = "mid(30-60%)" if pct and 0.30 <= pct < 0.60 else \
               "low(0-30%)" if pct and pct < 0.30 else \
               "high(60%+)" if pct else "unknown"
        
        base = {"symbol": sym, "date": date, "vr": s["vr"], "close": s["close"],
                "pct": pct, "zone": zone, "r4": s["r4"], "r8": s["r8"], "r12": s["r12"]}
        
        # Various strategy classifications
        if trust_consec5:
            classifications["VR+投信連5買"].append({**base, "inst_type": "投信"})
        if trust_consec3:
            classifications["VR+投信連3買"].append({**base, "inst_type": "投信"})
        if foreign_consec3:
            classifications["VR+外資連3買"].append({**base, "inst_type": "外資"})
        if trust_accum:
            classifications["VR+投信累積8w"].append({**base, "inst_type": "投信"})
        if foreign_accum:
            classifications["VR+外資累積8w"].append({**base, "inst_type": "外資"})
        if trust_consec3 or foreign_consec3:
            classifications["VR+法人連3買"].append({**base, "inst_type": "投信or外資"})
        if trust_accum or foreign_accum:
            classifications["VR+法人累積8w"].append({**base, "inst_type": "投信or外資"})
        if inst_trust_buy > 500000:  # 投信買超>50萬
            classifications["VR+投信大買"].append({**base, "inst_type": "投信"})
        
        # Control: VR only (no institutional filter)
        classifications["VR≥2 (全體)"].append({**base, "inst_type": ""})
    
    # ── Phase 4: Results ──
    print("\n" + "=" * 120, flush=True)
    print("🏆  回測結果 — 週量異常 + 法人初建倉 (2015-2025, 200 stocks)", flush=True)
    print("=" * 120, flush=True)
    
    print(f"{'策略':<22s} {'訊號':>6s} {'4w勝率':>8s} {'4w均%':>9s} {'8w勝率':>8s} {'8w均%':>9s} {'12w勝率':>9s} {'12w均%':>10s} {'12w盈虧比':>10s}")
    print("-" * 120, flush=True)
    
    results = []
    for name in sorted(classifications.keys(), key=lambda n: -(
        (classifications[n][12]["r12"] if len(classifications[n]) > 12 else 0) if False else len(classifications[n])
    )):
        sigs = classifications[name]
        if len(sigs) < 10: continue
        
        r4_arr = np.array([s["r4"] for s in sigs])
        r8_arr = np.array([s["r8"] for s in sigs])
        r12_arr = np.array([s["r12"] for s in sigs])
        
        wr4 = np.mean(r4_arr > 0)
        wr8 = np.mean(r8_arr > 0)
        wr12 = np.mean(r12_arr > 0)
        avg4 = np.mean(r4_arr)
        avg8 = np.mean(r8_arr)
        avg12 = np.mean(r12_arr)
        
        # Win/Loss Ratio for 12w
        wins = r12_arr[r12_arr > 0]
        losses = r12_arr[r12_arr < 0]
        rr12 = abs(np.mean(wins)/np.mean(losses)) if len(losses) > 0 else float('inf')
        
        results.append((name, len(sigs), wr4, avg4, wr8, avg8, wr12, avg12, rr12))
        
        # Sort results by 12w win rate descending
        results.sort(key=lambda x: -x[6])  # sort by 12w WR
    
    for name, n, wr4, avg4, wr8, avg8, wr12, avg12, rr12 in results:
        print(f"{name:<22s} {n:>6d} {wr4:>7.1%} {avg4:>+8.2%} {wr8:>7.1%} {avg8:>+8.2%} {wr12:>8.1%} {avg12:>+9.2%} {rr12:>9.2f}", flush=True)
    
    # ── Phase 5: By price position ──
    print("\n" + "=" * 120, flush=True)
    print("📊  股價位置分析 (VR+法人連3買)", flush=True)
    print("=" * 120, flush=True)
    
    for strategy in ["VR+法人連3買", "VR+法人累積8w"]:
        sigs = classifications.get(strategy, [])
        if not sigs: continue
        print(f"\n  {strategy} — 總訊號: {len(sigs)}", flush=True)
        for zone_name in ["low(0-30%)", "mid(30-60%)", "high(60%+)"]:
            zs = [s for s in sigs if s["zone"] == zone_name]
            if len(zs) < 5: continue
            r12z = np.array([s["r12"] for s in zs])
            print(f"    {zone_name:<20s}: n={len(zs):>5d}  12w勝率={np.mean(r12z>0):>7.1%}  均={np.mean(r12z):>+8.2%}  中位數={np.median(r12z):>+8.2%}", flush=True)
    
    # ── Phase 6: Holding period analysis ──
    print("\n" + "=" * 120, flush=True)
    print("📅  最佳持倉週期分析 (VR+法人連3買)", flush=True)
    print("=" * 120, flush=True)
    
    sigs = classifications.get("VR+法人連3買", [])
    if sigs:
        print(f"  {'週期':>8s} {'勝率':>7s} {'均報酬':>9s} {'中位數':>9s} {'夏普':>7s}", flush=True)
        print(f"  {'-'*45}", flush=True)
        for wk, key in [(4, "r4"), (8, "r8"), (12, "r12")]:
            arr = np.array([s[key] for s in sigs])
            wr = np.mean(arr > 0)
            avg = np.mean(arr)
            med = np.median(arr)
            sharpe = np.mean(arr)/np.std(arr)*np.sqrt(52/wk) if np.std(arr) > 0 else 0
            print(f"  {wk:>3d}w {'':>3s} {wr:>7.1%} {avg:>+8.2%} {med:>+8.2%} {sharpe:>6.2f}", flush=True)
    
    # ── Phase 7: 投信 vs 外資 ──
    print("\n" + "=" * 120, flush=True)
    print("🥊  投信 vs 外資 初建倉效果比較 (連3買)", flush=True)
    print("=" * 120, flush=True)
    
    trust_sigs = classifications.get("VR+投信連3買", [])
    foreign_sigs = classifications.get("VR+外資連3買", [])
    
    for label, sigs in [("投信連3買", trust_sigs), ("外資連3買", foreign_sigs)]:
        if len(sigs) >= 10:
            r12_arr = np.array([s["r12"] for s in sigs])
            print(f"  {label:<20s}: n={len(sigs):>5d}  12w勝率={np.mean(r12_arr>0):>7.1%}  均={np.mean(r12_arr):>+8.2%}  中位數={np.median(r12_arr):>+8.2%}", flush=True)
    
    # ── Phase 8: 初建倉 (首次買入) ──
    print("\n" + "=" * 120, flush=True)
    print("🔬  「初建倉」分析 (連3買且pct_52w<50%)", flush=True)
    print("=" * 120, flush=True)
    
    for strategy in ["VR+法人連3買", "VR+投信連3買"]:
        sigs = classifications.get(strategy, [])
        first_build = [s for s in sigs if s["pct"] is not None and s["pct"] < 0.50]
        if len(first_build) >= 10:
            r12_arr = np.array([s["r12"] for s in first_build])
            print(f"  {strategy:<22s} 初建倉(n={len(first_build):>4d}): 12w勝率={np.mean(r12_arr>0):>7.1%}  均={np.mean(r12_arr):>+8.2%}  中位數={np.median(r12_arr):>+8.2%}", flush=True)
    
    print(f"\n✅ 完成: {datetime.now().strftime('%Y-%m-%d %H:%M')}", flush=True)

if __name__ == "__main__":
    main()
