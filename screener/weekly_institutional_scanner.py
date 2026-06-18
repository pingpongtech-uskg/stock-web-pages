#!/usr/bin/env python3
"""
📅 週線法人初建倉掃描器 (Weekly Institutional Accumulation Scanner)

雷老闆找法：
1. 週線為主 — 趨勢看週線才有意義
2. 週量異常 — 本週成交量是過去10週均量的2倍以上
3. 法人初建倉 — 投信/外資在近2-4週持續買超
4. 股價位置合理 — 還在低檔或剛突破，還沒大漲

Data flow:
  batch JSON (daily) → weekly aggregation → VR filter → FinMind check → ranking
"""

import sys, os, json, glob
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")

# ─── 1. Load daily data ────────────────────────────────────────────────
def load_all_stocks():
    """Load all batch JSON files, return {symbol: {dates, close, volume, name}}."""
    stocks = {}
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "batch_*.json"))):
        with open(f) as fh:
            batch = json.load(fh)
        for sym, d in batch.items():
            if sym not in stocks and len(d.get("dates", [])) > 0:
                stocks[sym] = d
    return stocks

# ─── 2. Daily → Weekly aggregation ─────────────────────────────────────
def to_weekly(dates, closes, volumes):
    """
    Aggregate daily bars to weekly bars.
    Week = Mon-Fri. Week label = Friday's date (YYYY-MM-DD).
    
    Returns: (week_dates, week_opens, week_highs, week_lows, week_closes, week_volumes)
    """
    if not dates:
        return [], [], [], [], [], [], []
    
    from datetime import datetime
    
    # Group by ISO week number
    weekly = {}  # (year, week) -> {opens, highs, lows, close, volume, dates}
    
    for i, d in enumerate(dates):
        dt = datetime.strptime(d, "%Y-%m-%d")
        wk = dt.isocalendar()
        key = (wk[0], wk[1])  # (year, week)
        
        if key not in weekly:
            weekly[key] = {
                "open": closes[i],
                "high": closes[i],
                "low": closes[i],
                "close": closes[i],
                "volume": volumes[i],
                "date": d,  # last day in the week
                "count": 1,
            }
        else:
            w = weekly[key]
            w["high"] = max(w["high"], closes[i])
            w["low"] = min(w["low"], closes[i])
            w["close"] = closes[i]
            w["volume"] += volumes[i]
            w["date"] = d  # keep updating to friday
            w["count"] += 1
    
    # Sort by week
    sorted_weeks = sorted(weekly.keys())
    
    week_dates = []
    week_opens = []
    week_highs = []
    week_lows = []
    week_closes = []
    week_volumes = []
    week_counts = []
    
    for key in sorted_weeks:
        w = weekly[key]
        week_dates.append(w["date"])
        week_opens.append(w["open"])
        week_highs.append(w["high"])
        week_lows.append(w["low"])
        week_closes.append(w["close"])
        week_volumes.append(w["volume"])
        week_counts.append(w["count"])
    
    return week_dates, week_opens, week_highs, week_lows, week_closes, week_volumes, week_counts

# ─── 3. Weekly indicators ───────────────────────────────────────────────
def compute_weekly_indicators(week_closes, week_volumes):
    """Compute weekly MAs and Volume Ratio."""
    n = len(week_closes)
    if n < 12:
        return None
    
    closes = np.array(week_closes, dtype=float)
    volumes = np.array(week_volumes, dtype=float)
    
    # Weekly MAs (using cumsum for speed)
    def wk_sma(data, window):
        out = np.full(n, np.nan)
        cs = np.zeros(n + 1)
        cs[1:] = np.cumsum(data)
        out[window-1:n] = (cs[window:] - cs[:n-window+1]) / window
        return out
    
    ma5 = wk_sma(closes, 5)
    ma10 = wk_sma(closes, 10)
    ma20 = wk_sma(closes, 20)
    
    # Weekly Volume Ratio: this week's vol / avg vol of past 10 weeks
    # Using EXCLUSIVE avg (past weeks only, no look-ahead)
    vol_ma10 = np.full(n, np.nan)
    cs = np.zeros(n + 1)
    cs[1:] = np.cumsum(volumes)
    for i in range(10, n):
        vol_ma10[i] = (cs[i] - cs[i-10]) / 10  # avg of weeks [i-10, i-1]
    
    vr = np.full(n, np.nan)
    for i in range(10, n):
        if vol_ma10[i] > 0:
            vr[i] = volumes[i] / vol_ma10[i]
        else:
            vr[i] = 0
    
    # Price position: current vs recent 52-week range
    price_pct_52w = np.full(n, np.nan)
    for i in range(52, n):
        low_52w = np.min(closes[i-51:i+1])
        high_52w = np.max(closes[i-51:i+1])
        if high_52w > low_52w:
            price_pct_52w[i] = (closes[i] - low_52w) / (high_52w - low_52w)
    
    # Price vs MA5 (how far above/below 5-week MA)
    price_vs_ma5 = np.full(n, np.nan)
    for i in range(4, n):
        if not np.isnan(ma5[i]) and ma5[i] > 0:
            price_vs_ma5[i] = (closes[i] - ma5[i]) / ma5[i]
    
    return {
        "closes": closes,
        "volumes": volumes,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "vol_ma10": vol_ma10,
        "vr": vr,
        "price_pct_52w": price_pct_52w,
        "price_vs_ma5": price_vs_ma5,
    }

# ─── 4. Screen candidates ──────────────────────────────────────────────
def screen_weekly(stock_data, max_candidates=50):
    """
    Screen stocks for weekly VR anomaly + trend conditions.
    Returns list of (symbol, name, week_date, score, details).
    """
    candidates = []
    
    for sym, d in stock_data.items():
        dates = d.get("dates", [])
        closes = d.get("close", [])
        volumes = d.get("volume", [])
        name = d.get("name", sym)
        
        if len(dates) < 260:  # need ~5 years for weekly
            continue
        
        # Aggregate to weekly
        wd, wo, wh, wl, wc, wv, wcnt = to_weekly(dates, closes, volumes)
        
        if len(wc) < 12:
            continue
        
        ind = compute_weekly_indicators(wc, wv)
        if ind is None:
            continue
        
        # Look at the most recent 2 weeks
        i = len(wc) - 1  # latest week
        i_prev = i - 1   # previous week
        
        if i < 10:
            continue
        
        # ── Primary filter: Weekly VR ≥ 2.0 (this week or last week) ──
        vr_latest = ind["vr"][i]
        vr_prev = ind["vr"][i_prev] if i_prev >= 10 else 0
        
        if vr_latest < 2.0 and vr_prev < 2.0:
            continue
        
        best_vr_week = i if vr_latest >= vr_prev else i_prev
        best_vr = max(vr_latest, vr_prev)
        best_date = wd[best_vr_week]
        
        # ── Secondary: Price uptrend check ──
        # Price should be ABOVE weekly MA10 (not in deep downtrend)
        close = wc[best_vr_week]
        sma10 = ind["ma10"][best_vr_week]
        sma20 = ind["ma20"][best_vr_week]
        
        if np.isnan(sma10) or np.isnan(sma20):
            continue
        
        below_ma10 = close < sma10
        below_ma20 = close < sma20
        
        # For 初建倉: price can be just below MA10/MA20 (accumulation zone)
        # but should not be in severe downtrend
        if below_ma20 and close < sma20 * 0.85:
            continue  # too deep in downtrend, not accumulation
        
        # ── Price position: not over-extended ──
        pct_52w = ind["price_pct_52w"][best_vr_week]
        if np.isnan(pct_52w):
            continue
        
        # 初建倉 zone: 30-70% of 52w range (not too low, not too high)
        # Allow wider range for 初建倉: up to 80%
        in_position_zone = 0.20 <= pct_52w <= 0.80
        
        # ── Compute score ──
        score = 0
        details = {}
        
        # VR score (max 30)
        vr_score = min(30, int(best_vr * 10))
        score += vr_score
        
        # Price position score (max 20)
        # Sweet spot: 30-60% of 52w range (accumulation zone)
        if 0.30 <= pct_52w <= 0.60:
            pos_score = 20
        elif 0.20 <= pct_52w <= 0.80:
            pos_score = 10
        else:
            pos_score = 0
        score += pos_score
        
        # Trend score (max 20)
        trend_score = 0
        if not below_ma10:
            trend_score += 10  # above weekly MA10
        if not below_ma20:
            trend_score += 10  # above weekly MA20
        score += trend_score
        
        # Recent performance (max 15)
        # Check if price is rising over last 3 weeks
        if best_vr_week >= 3:
            p3 = wc[best_vr_week] / wc[best_vr_week - 3] - 1
            if p3 > 0.02:  # slight uptrend
                score += 15
            elif p3 > -0.03:  # flat
                score += 5
        
        # Volume consistency (max 15)
        # Check if volume has been elevated for multiple weeks
        if best_vr_week >= 4:
            recent_vrs = [ind["vr"][j] for j in range(best_vr_week - 3, best_vr_week + 1) 
                         if not np.isnan(ind["vr"][j])]
            if recent_vrs:
                avg_recent_vr = np.mean(recent_vrs)
                if avg_recent_vr > 1.5:
                    score += 15
                elif avg_recent_vr > 1.2:
                    score += 8
        
        # Price change from VR event
        price_chg_vr = None
        if best_vr_week == i and i_prev >= 0:
            # This week has VR - how much did it move?
            pass  # will compute later
        
        details = {
            "date": best_date,
            "close": round(close, 2),
            "vr": round(best_vr, 2),
            "ma10": round(sma10, 2),
            "ma20": round(sma20, 2),
            "pct_52w": round(pct_52w, 3),
            "below_ma10": bool(below_ma10),
            "below_ma20": bool(below_ma20),
            "vr_week": "current" if best_vr_week == i else "last",
            "price_chg_vr": round(price_chg_vr, 4) if price_chg_vr else None,
        }
        
        candidates.append((sym, name, score, details))
    
    # Sort by score descending, take top N
    candidates.sort(key=lambda x: -x[2])
    return candidates[:max_candidates]

# ─── 5. Institutional check (FinMind) ──────────────────────────────────
def check_institutional(symbols, max_api_calls=100):
    """
    Check FinMind for institutional buying data on candidate stocks.
    Returns {symbol: {score, trust_buy, foreign_buy, ...}}
    
    Uses the existing chip_scorer module.
    """
    sys.path.insert(0, BASE)
    
    results = {}
    calls_made = 0
    
    try:
        from chip_scorer import score_chip, _create_finmind_api
        api = _create_finmind_api()
        if api is None:
            print("  ⚠️  FinMind API unavailable (no token or connection failed)")
            return results
        
        today = datetime.now().strftime("%Y-%m-%d")
        
        for sym, name, score, details in symbols[:max_api_calls]:
            try:
                chip = score_chip(sym, today, api)
                calls_made += 1
                results[sym] = chip
            except Exception as e:
                print(f"  ⚠️  FinMind error for {sym}: {e}")
                results[sym] = {"institutional_score": 0, "total": 0}
            
            if calls_made >= max_api_calls:
                break
        
        print(f"  📡 FinMind API calls: {calls_made}")
    except Exception as e:
        print(f"  ❌ Failed to initialize FinMind: {e}")
    
    return results

# ─── 6. Main ────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("📅  週線法人初建倉掃描器 (Weekly Institutional Scanner)")
    print(f"📆  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    
    print("\n📦 Loading stock data...")
    stocks = load_all_stocks()
    print(f"   Loaded {len(stocks)} stocks")
    
    print("\n🔍 Screening for weekly VR anomaly...")
    candidates = screen_weekly(stocks, max_candidates=50)
    print(f"   Found {len(candidates)} candidates with weekly VR ≥ 2.0")
    
    if not candidates:
        print("\n❌ No candidates found.")
        return
    
    print(f"\n🏆 Top 50 Weekly VR Candidates (pre-institutional check):")
    print(f"{'#':>3s} {'Symbol':>10s} {'Name':<20s} {'Score':>6s} {'VR':>6s} {'Close':>8s} {'52w%':>7s} {'MA10':>8s}")
    print("-" * 72)
    for i, (sym, name, score, det) in enumerate(candidates[:15]):
        print(f"{i+1:3d} {sym:>10s} {name[:18]:<20s} {score:6d} {det['vr']:>6.1f} {det['close']:>8.1f} {det['pct_52w']:>7.0%} {det['ma10']:>8.1f}")
    
    # Check institutional data (limit to top 30 to save API calls)
    print(f"\n📡 Checking institutional buying data (top 30)...")
    inst_results = check_institutional(candidates[:30], max_api_calls=30)
    
    if inst_results:
        print(f"\n{'#'*3} {'Symbol':>10s} {'Name':<20s} {'Score':>6s} {'VR':>5s} {'InstSc':>7s} {'TotalChip':>10s} {'Position':>10s}")
        print("-" * 72)
        for i, (sym, name, score, det) in enumerate(candidates[:30]):
            chip = inst_results.get(sym, {})
            inst_sc = chip.get("institutional_score", 0)
            total_chip = chip.get("total", 0)
            pos = "🟢 初建倉" if (inst_sc >= 15 and det["pct_52w"] < 0.65) else \
                  "🟡 觀察" if inst_sc >= 5 else \
                  "⚪ 無法人"
            print(f"{i+1:3d} {sym:>10s} {name[:18]:<20s} {score:6d} {det['vr']:>5.1f} {inst_sc:>7d} {total_chip:>10d} {pos:>10s}")
    
    # ── Final ranking: combine VR score + institutional score ──
    print(f"\n{'='*70}")
    print(f"🏆  最終推薦排序 (VR + 法人初建倉)")
    print(f"{'='*70}")
    
    ranked = []
    for sym, name, score, det in candidates[:30]:
        chip = inst_results.get(sym, {})
        inst_sc = chip.get("institutional_score", 0)
        total_chip = chip.get("total", 0)
        
        # Combined score: 50% VR + 50% institutional
        vr_norm = min(1.0, det["vr"] / 5.0)
        inst_norm = min(1.0, inst_sc / 30.0)
        
        # Bonus for position zone
        pos_bonus = 0
        if 0.25 <= det["pct_52w"] <= 0.60:
            pos_bonus = 0.2  # sweet spot for institutional accumulation
        elif det["pct_52w"] < 0.80:
            pos_bonus = 0.1
        
        combined = vr_norm * 0.35 + inst_norm * 0.35 + pos_bonus
        ranked.append((combined, sym, name, score, det, inst_sc, total_chip))
    
    ranked.sort(key=lambda x: -x[0])
    
    print(f"{'#':>3s} {'Symbol':>10s} {'Name':<20s} {'Score':>5s} {'VR':>5s} {'Inst':>5s} {'52w%':>7s} {'建議':>10s}")
    print("-" * 70)
    for i, (comb, sym, name, score, det, inst_sc, total_chip) in enumerate(ranked[:15]):
        if inst_sc >= 15:
            rec = "🔥 買入觀察"
        elif inst_sc >= 5:
            rec = "👀 追蹤"
        else:
            rec = "📋 量異常常"
        print(f"{i+1:3d} {sym:>10s} {name[:18]:<20s} {score:5d} {det['vr']:>5.1f} {inst_sc:>5d} {det['pct_52w']:>7.0%} {rec:>10s}")

if __name__ == "__main__":
    main()
