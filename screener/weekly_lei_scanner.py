#!/usr/bin/env python3
"""
📅 雷老闆三條件週末掃描器
每週末自動執行，產出下週法人初建倉候選清單

條件：
1. 大盤條件：TAIEX 週量比 + 投信整體買超
2. 個股條件：週量異常 + 法人買超 + 股價位置
3. 散戶指標：融券變化方向

Output: /tmp/bt.log, also prints to stdout for cron delivery
"""

import sys, os, json, glob
from datetime import datetime, timedelta
from collections import OrderedDict, defaultdict
import numpy as np
from FinMind.data import DataLoader
import re, time, warnings
warnings.filterwarnings('ignore')

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")

# ─── Rate-limited FinMind ──────────────────────────────────────────
_fm_calls = []
def _fm_wait():
    now = time.time()
    while _fm_calls and now - _fm_calls[0] > 3600:
        _fm_calls.pop(0)
    if len(_fm_calls) >= 500:
        wait = _fm_calls[0] + 3600 - now
        if wait > 0: time.sleep(wait + 1)
    if _fm_calls:
        gap = 6.0 - (now - _fm_calls[-1])
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

# ─── Load batch data ───────────────────────────────────────────────
def load_stocks():
    stocks = {}
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "batch_*.json"))):
        with open(f) as fh:
            batch = json.load(fh)
        for sym, d in batch.items():
            if sym not in stocks and len(d.get("dates", [])) >= 260:
                stocks[sym] = d
    return stocks

# ─── Weekly aggregation ────────────────────────────────────────────
def agg_weekly(dates, closes, volumes):
    weekly = OrderedDict()
    for i, d in enumerate(dates):
        dt = datetime.strptime(d, "%Y-%m-%d")
        yr, wk, _ = dt.isocalendar()
        key = f"{yr}-W{wk:02d}"
        if key not in weekly:
            weekly[key] = {"date": d, "close": float(closes[i]), "volume": float(volumes[i])}
        else:
            w = weekly[key]; w["close"] = float(closes[i]); w["volume"] += float(volumes[i]); w["date"] = d
    return weekly

# ─── Condition 1: Market-level ────────────────────────────────────
def check_market(api):
    print("\n" + "=" * 60)
    print("📊 條件一：大盤週線")
    print("=" * 60)
    
    # TAIEX
    import yfinance as yf
    taiex = yf.download("^TWII", period="6mo", auto_adjust=True)
    tc = taiex['Close'].values.flatten()
    tv = taiex['Volume'].values.flatten()
    td = taiex.index.strftime('%Y-%m-%d').tolist()
    
    tw = agg_weekly(td, tc, tv)
    wk = list(tw.keys())
    latest = tw[wk[-1]]; last_key = wk[-1]
    idx = len(wk) - 1
    prev = tw[wk[idx-1]] if idx > 0 else latest
    
    # VR
    avg_vol = np.mean([tw[wk[j]]["volume"] for j in range(max(0,idx-10), idx)])
    vr = latest["volume"] / avg_vol if avg_vol > 0 else 0
    chg = (latest["close"] / prev["close"] - 1) * 100
    
    # 52w position
    high_52w = max(tw[wk[j]]["close"] for j in range(max(0,idx-51), idx+1))
    low_52w = min(tw[wk[j]]["close"] for j in range(max(0,idx-51), idx+1))
    pct_52w = (latest["close"]-low_52w)/(high_52w-low_52w)*100 if high_52w > low_52w else 0
    
    print(f"  📅 {last_key} (截至 {latest['date']})")
    print(f"  TAIEX: {latest['close']:.0f}  ({chg:+.2f}%)")
    print(f"  週量: {latest['volume']/1e8:.1f}億  VR={vr:.2f}")
    print(f"  52w位置: {pct_52w:.0f}%")
    
    # Market condition score
    market_ok = vr >= 1.15 or (chg > 2 and vr >= 1.0)
    print(f"  大盤條件: {'✅ 通過' if market_ok else '❌ 未達標'} (VR≥1.15或大漲+量增)")
    
    return market_ok, {"key": last_key, "close": latest["close"], "vr": vr, "chg": chg}

# ─── Condition 2: Stock-level weekly scan ──────────────────────────
def scan_stocks(api, stocks, top_n=100):
    print("\n" + "=" * 60)
    print("📊 條件二：個股週量異常 + 法人初建倉")
    print("=" * 60)
    
    # Sort by data length, use top liquid stocks
    sorted_syms = sorted(stocks.keys(), key=lambda s: len(stocks[s]["dates"]), reverse=True)
    symbols = sorted_syms[:top_n]
    
    # Phase 1: Compute weekly VR for all
    candidates = []
    for sym in symbols[:80]:  # Limit for speed
        d = stocks[sym]
        weekly = agg_weekly(d["dates"], d["close"], d["volume"])
        wk = list(weekly.keys())
        if len(wk) < 15: continue
        latest_key = wk[-1]
        w = weekly[latest_key]
        
        idx = len(wk) - 1
        if idx >= 10:
            avg_vol = np.mean([weekly[wk[j]]["volume"] for j in range(idx-10, idx)])
            vr = w["volume"] / avg_vol if avg_vol > 0 else 0
        else:
            continue
        
        if vr < 1.8: continue  # near-weekly volume anomaly
        
        # Price position
        pct_52w = None
        if idx >= 51:
            lo = min(weekly[wk[j]]["close"] for j in range(idx-51, idx+1))
            hi = max(weekly[wk[j]]["close"] for j in range(idx-51, idx+1))
            if hi > lo: pct_52w = (w["close"]-lo)/(hi-lo)
        
        # Price vs 10-week MA
        ma10 = np.mean([weekly[wk[j]]["close"] for j in range(idx-9, idx+1)])
        above_ma10 = w["close"] >= ma10
        
        chg_1w = (w["close"]/weekly[wk[idx-1]]["close"]-1)*100 if idx>0 else 0
        
        candidates.append({
            "symbol": sym, "name": d.get("name", sym),
            "date": w["date"], "close": w["close"],
            "vr": vr, "pct_52w": pct_52w,
            "above_ma10": above_ma10, "chg": chg_1w,
            "weekly": weekly, "wk": wk
        })
    
    if not candidates:
        print("  本週無週量異常個股")
        return []
    
    print(f"  篩出 {len(candidates)} 檔週量接近異常 (VR≥1.8)")
    
    # Phase 2: Check institutional data
    print("  📡 查法人買賣超...")
    
    results = []
    for c in candidates:
        _fm_wait()
        sym = c["symbol"]
        sid = sym.replace(".TW","").replace(".TWO","")
        
        try:
            df = api.taiwan_stock_institutional_investors(
                stock_id=sid, start_date=c["date"][:7]+"-01", end_date=c["date"]
            )
            if df is None or df.empty: continue
            
            # Last 5 trading days (1 week)
            recent = df[df["date"] <= c["date"]].sort_values("date").tail(5)
            
            trust_net = (recent[recent["name"]=="Investment_Trust"]["buy"] - 
                        recent[recent["name"]=="Investment_Trust"]["sell"]).sum()
            foreign_net = (recent[recent["name"]=="Foreign_Investor"]["buy"] - 
                          recent[recent["name"]=="Foreign_Investor"]["sell"]).sum()
            
            # Check consecutive buying
            def check_consecutive(df, name, days=3):
                sub = df[df["name"]==name].sort_values("date").tail(days)
                if len(sub) < days: return False
                return (sub["buy"]-sub["sell"] > 0).all()
            
            trust_c3 = check_consecutive(recent, "Investment_Trust", 3)
            foreign_c3 = check_consecutive(recent, "Foreign_Investor", 3)
            
            c["trust_net"] = trust_net
            c["foreign_net"] = foreign_net
            c["trust_c3"] = trust_c3
            c["foreign_c3"] = foreign_c3
            
            if trust_net > 0 or foreign_net > 0:
                results.append(c)
        except Exception:
            pass
    
    if not results:
        print("  無符合法人買超條件的個股")
        return []
    
    # Rank: VR score + institutional score + position score
    for r in results:
        vr_score = min(30, r["vr"]*10)
        inst_score = 30 if r["trust_c3"] else (20 if r["foreign_c3"] else (10 if r["trust_net"]>0 else 5))
        pos_score = 20 if (r["pct_52w"] and 0.20 <= r["pct_52w"] <= 0.60) else 10
        trend_score = 15 if r["above_ma10"] else 5
        r["total_score"] = vr_score + inst_score + pos_score + trend_score
    
    results.sort(key=lambda x: -x["total_score"])
    return results

# ─── Condition 3: Retail sentiment indicator ──────────────────────
def check_retail_sentiment(api):
    print("\n" + "=" * 60)
    print("📊 條件三：散戶情緒指標")
    print("=" * 60)
    
    # Use margin trading data from representative stocks
    # 2330.TW - TSMC as benchmark
    symbols_data = {}
    
    for stock_id, name in [("2330", "台積電"), ("2317", "鴻海")]:
        try:
            df = api.taiwan_stock_margin_purchase_short_sale(
                stock_id=stock_id, start_date="2026-04-01", end_date=datetime.now().strftime("%Y-%m-%d")
            )
            if df is not None and not df.empty:
                df = df.sort_values("date")
                recent = df.tail(10)
                
                short_start = recent.iloc[0]["ShortSaleTodayBalance"]
                short_end = recent.iloc[-1]["ShortSaleTodayBalance"]
                short_chg = (short_end/short_start - 1)*100 if short_start > 0 else 0
                
                symbols_data[name] = {
                    "short_start": short_start,
                    "short_end": short_end,
                    "short_chg": short_chg,
                    "recent": recent
                }
        except:
            pass
    
    for name, data in symbols_data.items():
        sentiment = "偏空 ✅ (法人軋空有利)" if data["short_chg"] > 0 else \
                    "偏多 ❌ (散戶追高)" if data["short_chg"] < -10 else \
                    "中性"
        print(f"  {name} 融券: {data['short_start']:>5,d}→{data['short_end']:>5,d} ({data['short_chg']:+.0f}%) → {sentiment}")
    
    # Composite
    bearish_count = sum(1 for d in symbols_data.values() if d.get("short_chg", 0) > 0)
    retail_ok = bearish_count >= 1  # At least one shows retail bearish
    print(f"  散戶整體: {'✅ 偏空(有利) 法人容易吃貨' if retail_ok else '⚠️ 散戶偏多'}")
    
    return retail_ok

# ─── Output results ───────────────────────────────────────────────
def print_results(market_ok, stocks, retail_ok):
    print("\n" + "=" * 70)
    print("🎯  雷老闆三條件掃描結果")
    print(f"📆  {datetime.now().strftime('%Y-%m-%d %H:%M')} (週報)")
    print("=" * 70)
    
    print(f"\n大盤條件  : {'✅ 通過' if market_ok else '❌ 未達標'}")
    print(f"散戶指標  : {'✅ 偏空有利' if retail_ok else '⚠️ 散戶偏多'}")
    
    if not stocks:
        print("\n❌ 本週無符合條件的法人初建倉標的")
        return
    
    print(f"\n{'='*70}")
    print(f"🏆  法人初建倉候選清單 (依綜合評分排序)")
    print(f"{'='*70}")
    print(f"{'#':>3s} {'股票':>10s} {'名稱':<12s} {'股價':>8s} {'週量VR':>7s} {'投信':>8s} {'外資':>9s} {'52w%':>6s} {'訊號':>12s}")
    print("-" * 70)
    
    for i, s in enumerate(stocks[:20]):
        inst_tag = "🔥投信" if s["trust_c3"] else ("👀外資" if s["foreign_c3"] else "法人買")
        def pct_zone(p):
            if p is None: return "?"
            if p < 0.30: return "低檔"
            if p < 0.60: return "中段"
            return "高檔"
        pos_tag = pct_zone(s.get("pct_52w"))
        vr_tag = f"{s['vr']:.1f}x"
        
        trust_str = f"{s['trust_net']/1e6:.1f}M" if s.get('trust_net') else "0"
        foreign_str = f"{s['foreign_net']/1e6:.1f}M" if s.get('foreign_net') else "0"
        pct_str = f"{s['pct_52w']*100:.0f}%" if s.get('pct_52w') else "?"
        
        print(f"{i+1:3d} {s['symbol'][:10]:>10s} {s['name'][:10]:<12s} {s['close']:>8.1f} {vr_tag:>7s} {trust_str:>8s} {foreign_str:>9s} {pct_str:>6s} {inst_tag+' '+pos_tag:>12s}")
    
    # Detailed analysis for top 5
    print(f"\n{'='*70}")
    print(f"🔍  前5名深度分析")
    print(f"{'='*70}")
    
    for i, s in enumerate(stocks[:5]):
        inst_type = "投信" if s["trust_c3"] else ("外資" if s["foreign_c3"] else "法人")
        action = "連3買🔥" if s["trust_c3"] or s["foreign_c3"] else "買超"
        
        def pct_str_fmt(p):
            if p is None: return "?"
            return f"{p*100:.0f}%"
        pct_str = pct_str_fmt(s.get("pct_52w"))
        
        print(f"")
        print(f"  {i+1}. {s['symbol']} {s['name']}")
        print(f"     股價: {s['close']:.1f} | 週量: {s['vr']:.1f}x | 52w位置: {pct_str}")
        print(f"     法人: {inst_type} {action} (投信{s['trust_net']/1e6:.1f}M, 外資{s['foreign_net']/1e6:.1f}M)")
        print(f"     策略: {'✅ 符合雷老闆初建倉條件' if s['trust_c3'] and s['pct_52w'] and s['pct_52w']<0.60 else '👀 觀察'}")
    
    print(f"\n{'='*70}")
    print(f"📋  本週策略建議")
    print(f"{'='*70}")
    
    if stocks[0].get("trust_c3") and stocks[0].get("pct_52w", 1) < 0.60:
        print(f"  ▶ 首選 {stocks[0]['symbol']} {stocks[0]['name']}：投信連買+量增+位置合理")
        print(f"  ▶ 建議本週分批布局，持有4-8週觀察投信是否續買")
    elif stocks[0].get("foreign_c3"):
        print(f"  ▶ 首選 {stocks[0]['symbol']} {stocks[0]['name']}：外資連買主導")
        print(f"  ▶ 外資主導波動較大，建議等拉回再進")
    else:
        print(f"  ▶ 本週無強法人訊號，建議觀望或減碼")

# ─── Main ──────────────────────────────────────────────────────────
def main():
    print(f"\n📅  雷老闆三條件週末掃描器")
    print(f"🕐  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("-" * 60)
    
    api = get_api()
    
    # Condition 1: Market
    market_ok, market_data = check_market(api)
    
    # Condition 2: Stock scan
    stocks = load_stocks()
    print(f"\n📦 資料庫: {len(stocks)} 檔上市櫃股票")
    candidates = scan_stocks(api, stocks, top_n=200)
    
    # Condition 3: Retail sentiment
    retail_ok = check_retail_sentiment(api)
    
    # Results
    print_results(market_ok, candidates, retail_ok)
    
    print(f"\n✅ 掃描完成")

if __name__ == "__main__":
    main()
