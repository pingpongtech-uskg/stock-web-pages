#!/usr/bin/env python3
"""
compute_value_scores.py — Compute 便宜 (cheap) and 定存 (dividend) scores from yfinance.

No scraping. Uses yfinance info + dividend history + 3.5yr regression.

便宜股 (6 indicators, each 1pt):
  1. PE < 15 (trailing PE ratio low)
  2. PB < 1.5 (price-to-book low)
  3. Price in lower 50% of 52-week range
  4. Z < -0.5 (below 樂活五線譜 trend)
  5. Dividend yield > 4%
  6. 5yr avg dividend yield > 3%

定存股 (5 indicators, each 1pt):
  1. Dividend yield > 4%
  2. 5yr avg dividend yield > 3%
  3. 5+ consecutive years of dividends
  4. Dividend stable (no cut >30% in last 3 years)
  5. Payout ratio 30-90% (from yfinance, may be unreliable)

Output: data/value_scores_cache.json → {code: {cheap_score, cheap_detail, dividend_score, dividend_detail}}
"""
import json
import os
import sys
import numpy as np
from datetime import datetime, timedelta

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "value_scores_cache.json")
CACHE_TTL_HOURS = 24


def fetch_stock_data(code: str) -> dict | None:
    """Fetch yfinance data for a Taiwan stock."""
    try:
        import yfinance as yf
        for ext in [".TW", ".TWO"]:
            tk = yf.Ticker(f"{code}{ext}")
            hist = tk.history(period="5y", auto_adjust=False)
            if hist is not None and len(hist) >= 100:
                break
        if hist is None or len(hist) < 100:
            return None
        
        info = tk.info
        divs = tk.dividends
        
        return {
            "info": info,
            "hist": hist,
            "dividends": divs,
        }
    except Exception as e:
        print(f"  {code}: yfinance error: {e}", file=sys.stderr)
        return None


def compute_dividend_yield(code: str, info: dict, dividends, price: float) -> float | None:
    """Compute trailing dividend yield. Falls back to manual calculation."""
    dy = info.get("dividendYield")
    if dy is not None:
        # Normalize: yfinance sometimes returns decimal (0.05), sometimes percent (5.0)
        return dy * 100 if dy < 1 else dy
    
    # Manual: sum of last year's dividends / current price
    if len(dividends) > 0 and price > 0:
        last_year = datetime.now().year - 1
        total = sum(amt for d, amt in dividends.items() if d.year == last_year)
        if total > 0:
            return round(total / price * 100, 2)
    
    return None


def compute_5yr_avg_yield(code: str, info: dict, dividends, price: float) -> float | None:
    """Compute 5-year average dividend yield."""
    avg5 = info.get("fiveYearAvgDividendYield")
    if avg5 is not None:
        return avg5 if avg5 > 1 else avg5 * 100
    
    # Manual
    if len(dividends) > 0 and price > 0:
        this_year = datetime.now().year
        yearly = {}
        for d, amt in dividends.items():
            y = d.year
            if y < this_year:
                yearly[y] = yearly.get(y, 0) + amt
        
        recent_years = sorted(yearly.items())[-5:]
        if len(recent_years) >= 3 and price > 0:
            yields = [amt / price * 100 for _, amt in recent_years]
            return round(sum(yields) / len(yields), 2)
    
    return None


def compute_z(hist) -> float | None:
    """3.5yr raw-price regression Z (matches 樂活五線譜)."""
    p = hist['Close'].values[-882:]
    if len(p) < 100:
        return None
    x = np.arange(len(p))
    slope, intercept = np.polyfit(x, p, 1)
    trend = slope * x + intercept
    sigma = np.std(p - trend)
    if sigma <= 0:
        return None
    return round(float((p[-1] - trend[-1]) / sigma), 2)


def compute_scores(code: str) -> dict | None:
    """Compute cheap and dividend scores for a stock."""
    data = fetch_stock_data(code)
    if data is None:
        return None
    
    info = data["info"]
    hist = data["hist"]
    dividends = data["dividends"]
    
    price = info.get("regularMarketPrice") or float(hist['Close'].iloc[-1])
    
    # ── CHEAP SCORE ──
    cheap_checks = 0
    cheap_detail = []
    
    # 1. PE < 15
    pe = info.get("trailingPE")
    if pe is not None and pe < 15:
        cheap_checks += 1
        cheap_detail.append(f"✓ PE={pe:.1f} < 15")
    else:
        cheap_detail.append(f"✗ PE={'N/A' if pe is None else f'{pe:.1f}'} ≥ 15")
    
    # 2. PB < 1.5
    pb = info.get("priceToBook")
    if pb is not None and pb < 1.5:
        cheap_checks += 1
        cheap_detail.append(f"✓ PB={pb:.2f} < 1.5")
    else:
        cheap_detail.append(f"✗ PB={'N/A' if pb is None else f'{pb:.2f}'} ≥ 1.5")
    
    # 3. Price in lower 50% of 52-week range
    low52 = info.get("fiftyTwoWeekLow")
    high52 = info.get("fiftyTwoWeekHigh")
    if low52 and high52 and high52 > low52:
        pct = round((price - low52) / (high52 - low52) * 100)
        if pct < 50:
            cheap_checks += 1
            cheap_detail.append(f"✓ 股價在52週低點{pct}% (< 50%)")
        else:
            cheap_detail.append(f"✗ 股價在52週低點{pct}% (≥ 50%)")
    else:
        cheap_detail.append("✗ 52週高低點不足")
    
    # 4. Z < -0.5
    z = compute_z(hist)
    if z is not None:
        if z < -0.5:
            cheap_checks += 1
            cheap_detail.append(f"✓ Z={z:.2f} < -0.5")
        else:
            cheap_detail.append(f"✗ Z={z:.2f} ≥ -0.5")
    else:
        cheap_detail.append("✗ Z計算失敗")
    
    # 5. Dividend yield > 4%
    div_yield = compute_dividend_yield(code, info, dividends, price)
    if div_yield is not None:
        if div_yield > 4:
            cheap_checks += 1
            cheap_detail.append(f"✓ 殖利率={div_yield:.1f}% > 4%")
        else:
            cheap_detail.append(f"✗ 殖利率={div_yield:.1f}% ≤ 4%")
    else:
        cheap_detail.append("✗ 殖利率不足")
    
    # 6. 5yr avg dividend yield > 3%
    avg5 = compute_5yr_avg_yield(code, info, dividends, price)
    if avg5 is not None:
        if avg5 > 3:
            cheap_checks += 1
            cheap_detail.append(f"✓ 5y均殖利率={avg5:.1f}% > 3%")
        else:
            cheap_detail.append(f"✗ 5y均殖利率={avg5:.1f}% ≤ 3%")
    else:
        cheap_detail.append("✗ 5y均殖利率不足")
    
    cheap_score = round(cheap_checks / 6 * 100, 1)
    
    # ── DIVIDEND SCORE ──
    div_checks = 0
    div_detail = []
    
    # 1. Dividend yield > 4%
    if div_yield is not None:
        if div_yield > 4:
            div_checks += 1
            div_detail.append(f"✓ 殖利率={div_yield:.1f}% > 4%")
        else:
            div_detail.append(f"✗ 殖利率={div_yield:.1f}% ≤ 4%")
    else:
        div_detail.append("✗ 殖利率不足")
    
    # 2. 5yr avg > 3%
    if avg5 is not None:
        if avg5 > 3:
            div_checks += 1
            div_detail.append(f"✓ 5y均殖利率={avg5:.1f}% > 3%")
        else:
            div_detail.append(f"✗ 5y均殖利率={avg5:.1f}% ≤ 3%")
    else:
        div_detail.append("✗ 5y均殖利率不足")
    
    # 3. 5+ consecutive years of dividends
    if len(dividends) > 0:
        years_with_divs = set(d.year for d in dividends.index)
        recent = sorted(years_with_divs, reverse=True)
        consecutive = 1
        for i in range(1, len(recent)):
            if recent[i-1] - recent[i] == 1:
                consecutive += 1
            else:
                break
        if consecutive >= 5:
            div_checks += 1
            div_detail.append(f"✓ 連續{consecutive}年發股息 (≥ 5)")
        else:
            div_detail.append(f"✗ 連續{consecutive}年發股息 (< 5)")
    else:
        div_detail.append("✗ 無股利紀錄")
    
    # 4. Dividend stable in last 3 years (no cut > 30%)
    if len(dividends) > 0:
        yearly = {}
        for d, amt in dividends.items():
            yearly[d.year] = yearly.get(d.year, 0) + amt
        recent = sorted(yearly.items())[-3:]
        if len(recent) >= 3:
            stable = True
            for i in range(1, len(recent)):
                prev = recent[i-1][1]
                curr = recent[i][1]
                if prev > 0 and curr < prev * 0.7:  # >30% cut
                    stable = False
                    break
            if stable:
                div_checks += 1
                div_detail.append("✓ 近3年股利穩定 (無減>30%)")
            else:
                div_detail.append("✗ 近3年股利不穩定")
        else:
            div_detail.append("✗ 股利紀錄<3年")
    else:
        div_detail.append("✗ 無股利紀錄")
    
    # 5. Payout ratio check (from yfinance — may be unreliable for TW stocks)
    payout = info.get("payoutRatio")
    if payout is not None and 0.3 <= payout <= 0.9:
        div_checks += 1
        div_detail.append(f"✓ 配息率={payout*100:.0f}% 在30-90%")
    elif payout is not None:
        div_detail.append(f"✗ 配息率={payout*100:.0f}% 不在30-90%")
    else:
        div_detail.append("— 配息率: 無資料 (yfinance TW限制)")
    
    dividend_score = round(div_checks / 5 * 100, 1)
    
    return {
        "cheap_score": cheap_score,
        "cheap_detail": cheap_detail,
        "dividend_score": dividend_score,
        "dividend_detail": div_detail,
        "updated_at": datetime.now().isoformat(),
    }


def load_cache() -> dict:
    """Load existing cache, return {} if expired or missing."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
        # Check TTL
        updated = cache.get("_updated_at", "")
        if updated:
            cache_time = datetime.fromisoformat(updated)
            if datetime.now() - cache_time > timedelta(hours=CACHE_TTL_HOURS):
                return {}  # Expired
        return cache
    except (json.JSONDecodeError, ValueError):
        return {}


def save_cache(cache: dict):
    """Save cache to file."""
    cache["_updated_at"] = datetime.now().isoformat()
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def get_scores(codes: list[str], force: bool = False) -> dict[str, dict]:
    """Get scores for a list of stock codes. Uses cache if fresh."""
    cache = {} if force else load_cache()
    results = {}
    
    for code in codes:
        if code in cache and code not in ("_updated_at",):
            results[code] = cache[code]
            continue
        
        print(f"  Computing {code}...")
        scores = compute_scores(code)
        if scores:
            results[code] = scores
            cache[code] = scores
        else:
            print(f"  {code}: FAILED, skipping")
    
    save_cache(cache)
    return results


if __name__ == "__main__":
    # Test with active stocks
    codes = ["2105", "1216", "1513", "2633", "2006", "6191", "2618", "2610",
             "3014", "3045", "4904", "3015", "2377", "1229", "2548"]
    
    print(f"Computing value scores for {len(codes)} stocks...")
    results = get_scores(codes)
    
    for code, s in sorted(results.items()):
        print(f"\n{code}: Cheap={s['cheap_score']}% Dividend={s['dividend_score']}%")
        for d in s.get("cheap_detail", []):
            print(f"  {d}")
        for d in s.get("dividend_detail", []):
            print(f"  {d}")
