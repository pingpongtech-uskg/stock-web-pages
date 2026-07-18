#!/usr/bin/env python3
"""
compute_value_scores.py — Compute 便宜 (cheap) and 定存 (dividend) scores.

Uses yfinance for price/PE/PB/dividends + FinMind for historical payout ratios.

便宜股 (6 indicators, each 1pt):
  1. PE < 15 (trailing PE ratio low)
  2. PB < 1.5 (price-to-book low)
  3. Price in lower 50% of 52-week range
  4. Z < -0.5 (below 樂活五線譜 trend)
  5. Dividend yield > 6%
  6. 5yr avg dividend yield > 6%

定存股 (5 indicators, each 1pt, matching StatementDog):
  1. Dividend yield > 6%
  2. 5yr avg dividend yield > 6%
  3. 5+ consecutive years of dividends
  4. 股息發放率五年內有三年大於 50% (payout >50% in 3 of 5 years)
  5. 股息發放率五年平均大於 50% (avg payout >50% in 5 years)

Output: data/value_scores_cache.json → {code: {cheap_score, cheap_detail, dividend_score, dividend_detail}}
"""
import json
import os
import sys
import re
import numpy as np
from datetime import datetime, timedelta

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "value_scores_cache.json")
CACHE_TTL_HOURS = 24


# ── FinMind token loading (same pattern as daily_trust_monitor.py) ──

def _load_finmind_token() -> str | None:
    """Load FinMind token from existing scripts."""
    src_files = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tw-stock-monitor", "scripts", "download_otc_prices.py"),
    ]
    for fp in src_files:
        if os.path.exists(fp):
            with open(fp) as f:
                content = f.read()
            for m in re.finditer(
                r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", content
            ):
                return m.group()
    return None


def _compute_payout_ratios(code: str) -> dict | None:
    """Compute annual payout ratios (股息發放率) for last 5 years using FinMind.
    
    Returns: {year: payout_ratio_pct, ...} or None if insufficient data.
    """
    token = _load_finmind_token()
    if not token:
        return None
    
    try:
        from FinMind.data import DataLoader
        api = DataLoader()
        api.login_by_token(api_token=token)
        
        # Get per-share dividends
        div_df = api.taiwan_stock_dividend(stock_id=code, start_date='2018-01-01')
        if div_df is None or len(div_df) == 0:
            return None
        
        # Parse dividend years: sum CashEarningsDistribution + CashStatutorySurplus per year
        # FinMind uses ROC year format (e.g. '106年' = 2017)
        yearly_div_per_share = {}
        for _, row in div_df.iterrows():
            try:
                year_str = str(row.get('year', ''))
                # Parse ROC year: '106年' → 2017
                if '年' in year_str:
                    year = 1911 + int(year_str.replace('年', ''))
                else:
                    # Fallback: use date column
                    year = int(str(row['date'])[:4])
                cash = float(row.get('CashEarningsDistribution', 0) or 0) + float(row.get('CashStatutorySurplus', 0) or 0)
                yearly_div_per_share[year] = yearly_div_per_share.get(year, 0) + cash
            except:
                pass
        
        if not yearly_div_per_share:
            return None
        
        # Get financial statements for Net Income
        fin_df = api.taiwan_stock_financial_statement(stock_id=code, start_date=f'{min(yearly_div_per_share.keys())-1}-01-01')
        if fin_df is None or len(fin_df) == 0:
            return None
        
        # Aggregate quarterly Net Income to yearly
        yearly_ni = {}
        for _, row in fin_df.iterrows():
            try:
                year = int(row['date'][:4])
                if row['type'] == 'IncomeAfterTaxes' or row['type'] == 'NetIncome':
                    yearly_ni[year] = yearly_ni.get(year, 0) + float(row['value'])
            except:
                pass
        
        # Get shares outstanding
        info_df = api.taiwan_stock_info(timeout=30)
        shares = None
        if info_df is not None:
            for _, row in info_df.iterrows():
                if str(row.get('stock_id', '')).strip() == code:
                    # Try to get current shares outstanding
                    pass
        
        # Fallback: use yfinance for shares
        if shares is None:
            try:
                import yfinance as yf
                for ext in ['.TW', '.TWO']:
                    tk = yf.Ticker(f'{code}{ext}')
                    shares = tk.info.get('sharesOutstanding')
                    if shares:
                        break
            except:
                pass
        
        if shares is None or shares <= 0:
            return None
        
        # Compute EPS = Net Income / Shares per year
        payout_ratios = {}
        for year in sorted(set(list(yearly_div_per_share.keys()) + list(yearly_ni.keys()))):
            ni = yearly_ni.get(year, 0)
            div = yearly_div_per_share.get(year, 0)
            if ni > 0 and shares > 0:
                eps = ni / shares
                if eps > 0:
                    payout_ratios[year] = round(div / eps * 100, 1)
        
        return payout_ratios if len(payout_ratios) >= 3 else None
        
    except Exception as e:
        print(f"  FinMind payout ratio failed for {code}: {e}", file=sys.stderr)
        return None


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
    
    # 5. Dividend yield > 6%
    div_yield = compute_dividend_yield(code, info, dividends, price)
    if div_yield is not None:
        if div_yield > 6:
            cheap_checks += 1
            cheap_detail.append(f"✓ 殖利率={div_yield:.1f}% > 6%")
        else:
            cheap_detail.append(f"✗ 殖利率={div_yield:.1f}% ≤ 6%")
    else:
        cheap_detail.append("✗ 殖利率不足")
    
    # 6. 5yr avg dividend yield > 6%
    avg5 = compute_5yr_avg_yield(code, info, dividends, price)
    if avg5 is not None:
        if avg5 > 6:
            cheap_checks += 1
            cheap_detail.append(f"✓ 5y均殖利率={avg5:.1f}% > 6%")
        else:
            cheap_detail.append(f"✗ 5y均殖利率={avg5:.1f}% ≤ 6%")
    else:
        cheap_detail.append("✗ 5y均殖利率不足")
    
    cheap_score = round(cheap_checks / 6 * 100, 1)
    
    # ── DIVIDEND SCORE ──
    div_checks = 0
    div_detail = []
    
    # 1. Dividend yield > 6%
    if div_yield is not None:
        if div_yield > 6:
            div_checks += 1
            div_detail.append(f"✓ 殖利率={div_yield:.1f}% > 6%")
        else:
            div_detail.append(f"✗ 殖利率={div_yield:.1f}% ≤ 6%")
    else:
        div_detail.append("✗ 殖利率不足")
    
    # 2. 5yr avg > 6%
    if avg5 is not None:
        if avg5 > 6:
            div_checks += 1
            div_detail.append(f"✓ 5y均殖利率={avg5:.1f}% > 6%")
        else:
            div_detail.append(f"✗ 5y均殖利率={avg5:.1f}% ≤ 6%")
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
    
    # 4. 股息發放率五年內有三年大於 50% (StatementDog)
    # 5. 股息發放率五年平均大於 50% (StatementDog)
    payout_ratios = _compute_payout_ratios(code)
    if payout_ratios is not None and len(payout_ratios) >= 3:
        years = sorted(payout_ratios.keys())[-5:]
        recent_pr = [payout_ratios[y] for y in years]
        # 3 of 5 years > 50%
        ok_count = sum(1 for pr in recent_pr if pr > 50)
        if ok_count >= 3:
            div_checks += 1
            div_detail.append(f"✓ 配息率五年有{ok_count}年>50%")
        else:
            div_detail.append(f"✗ 配息率五年僅{ok_count}年>50% (需≥3)")
        # Average > 50%
        avg_pr = sum(recent_pr) / len(recent_pr)
        if avg_pr > 50:
            div_checks += 1
            div_detail.append(f"✓ 配息率五年平均={avg_pr:.0f}% > 50%")
        else:
            div_detail.append(f"✗ 配息率五年平均={avg_pr:.0f}% ≤ 50%")
    elif payout_ratios is not None:
        div_detail.append(f"✗ 配息率資料不足 ({len(payout_ratios)}年)")
        div_detail.append(f"✗ 配息率資料不足")
    else:
        div_detail.append("— 配息率: FinMind資料不足")
        div_detail.append("— 配息率: FinMind資料不足")
    
    dividend_score = round(div_checks / 5 * 100, 1)
    
    # ── EX-DIVIDEND DATE + PER-SHARE AMOUNT ──
    ex_div_raw = info.get("exDividendDate")
    div_rate = info.get("dividendRate")

    ex_dividend_date = None
    if ex_div_raw is not None:
        try:
            ex_dividend_date = datetime.fromtimestamp(ex_div_raw).strftime("%Y-%m-%d")
        except (ValueError, OSError):
            ex_dividend_date = None

    dividend_per_share = round(div_rate, 2) if div_rate is not None else None
    
    return {
        "cheap_score": cheap_score,
        "cheap_detail": cheap_detail,
        "dividend_score": dividend_score,
        "dividend_detail": div_detail,
        "ex_dividend_date": ex_dividend_date,
        "dividend_per_share": dividend_per_share,
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
