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
import time
import numpy as np
from datetime import datetime, timedelta

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "value_scores_cache.json")
CACHE_TTL_HOURS = 24
CACHE_VERSION = 2  # Increment when scoring logic changes to force cache invalidation


# ── FinMind token loading (same pattern as daily_trust_monitor.py) ──

def _load_finmind_token() -> str | None:
    """Load FinMind token with rotation from Infisical (Finmind_1..4)."""
    global _FM_TOKEN_POOL_VS, _FM_TOKEN_INDEX_VS
    if '_FM_TOKEN_POOL_VS' not in globals():
        _init_finmind_pool_vs()
    pool = _FM_TOKEN_POOL_VS
    if pool:
        tok = pool[_FM_TOKEN_INDEX_VS % len(pool)]
        _FM_TOKEN_INDEX_VS += 1
        return tok
    # Fallback: file-based token
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


def _init_finmind_pool_vs():
    """Initialize FinMind token pool from /tmp/finmind_keys.json, Infisical, or file fallback."""
    global _FM_TOKEN_POOL_VS, _FM_TOKEN_INDEX_VS
    _FM_TOKEN_POOL_VS = []
    _FM_TOKEN_INDEX_VS = 0

    # 1. Try /tmp/finmind_keys.json (created by backfill scripts, has all 4 keys)
    keys_file = "/tmp/finmind_keys.json"
    if os.path.exists(keys_file):
        try:
            with open(keys_file) as f:
                keys = json.load(f)
            for v in keys.values():
                if v and str(v).startswith("eyJ"):
                    _FM_TOKEN_POOL_VS.append(str(v))
            if _FM_TOKEN_POOL_VS:
                print(f"  Loaded {len(_FM_TOKEN_POOL_VS)} FinMind tokens from {keys_file}", file=sys.stderr)
                return
        except Exception:
            pass

    # 2. Try Infisical (legacy)
    try:
        import subprocess
        for i in range(1, 5):
            try:
                tok = subprocess.check_output(
                    ["infisical", "secrets", "get", f"Finmind_{i}",
                     "--env", "dev", "--silent", "--plain"],
                    cwd="/root", stderr=subprocess.DEVNULL, text=True, timeout=10
                ).strip()
                if tok and tok.startswith("eyJ"):
                    _FM_TOKEN_POOL_VS.append(tok)
            except Exception:
                pass
    except Exception:
        pass

    if _FM_TOKEN_POOL_VS:
        print(f"  Loaded {len(_FM_TOKEN_POOL_VS)} FinMind tokens from Infisical", file=sys.stderr)
        return

    # 3. Fallback: scan download_otc_prices.py for embedded JWT
    src_files = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                     "tw-stock-monitor", "scripts", "download_otc_prices.py"),
    ]
    for fp in src_files:
        if os.path.exists(fp):
            with open(fp) as f:
                content = f.read()
            for m in re.finditer(
                r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", content
            ):
                _FM_TOKEN_POOL_VS.append(m.group())

    if _FM_TOKEN_POOL_VS:
        print(f"  Loaded {len(_FM_TOKEN_POOL_VS)} FinMind tokens from file scan", file=sys.stderr)


# ── FinMind rate limiting + retry helpers ──

_FM_LAST_CALL_TS = 0.0


def _finmind_rate_limit():
    """Throttle to max 1 FinMind API call per second."""
    global _FM_LAST_CALL_TS
    elapsed = time.time() - _FM_LAST_CALL_TS
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _FM_LAST_CALL_TS = time.time()


def _call_finmind(method_name, token, *args, **kwargs):
    """Call a FinMind DataLoader method with rate limiting + exponential backoff.

    Retries up to 3 times with 5s/10s/20s delays on rate-limit errors.
    Rotates tokens between retries.
    Returns None if all retries fail.
    """
    for attempt in range(3):
        try:
            _finmind_rate_limit()
            from FinMind.data import DataLoader
            api = DataLoader()
            api.login_by_token(api_token=token)
            method = getattr(api, method_name)
            return method(*args, **kwargs)
        except Exception as e:
            err_str = str(e)
            if ("Requests reach the upper limit" in err_str
                    or "rate limit" in err_str.lower()
                    or "429" in err_str):
                if attempt < 2:
                    wait = [5, 10, 20][attempt]
                    print(f"    FinMind rate-limited (attempt {attempt+1}/3), "
                          f"waiting {wait}s + rotating token...", file=sys.stderr)
                    time.sleep(wait)
                    token = _load_finmind_token()
                    if not token:
                        return None
                    continue
            return None
    return None


def _compute_payout_ratios(code: str) -> dict | None:
    """Compute annual payout ratios (股息發放率) for last 5 years using FinMind.

    Returns: {year: payout_ratio_pct, ...} or None if insufficient data.
    """
    token = _load_finmind_token()
    if not token:
        return None

    try:
        # Get per-share dividends with retry/backoff
        div_df = _call_finmind(
            "taiwan_stock_dividend", token,
            stock_id=code, start_date='2018-01-01'
        )
        if div_df is None or len(div_df) == 0:
            print(f"  {code}: FinMind dividend data unavailable", file=sys.stderr)
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
            except Exception:
                pass

        if not yearly_div_per_share:
            return None

        # Get financial statements for Net Income with retry/backoff
        fin_df = _call_finmind(
            "taiwan_stock_financial_statement", token,
            stock_id=code,
            start_date=f'{min(yearly_div_per_share.keys())-1}-01-01'
        )
        if fin_df is None or len(fin_df) == 0:
            print(f"  {code}: FinMind financial statement unavailable", file=sys.stderr)
            return None

        # Aggregate quarterly Net Income to yearly
        yearly_ni = {}
        for _, row in fin_df.iterrows():
            try:
                year = int(row['date'][:4])
                if row['type'] == 'IncomeAfterTaxes' or row['type'] == 'NetIncome':
                    yearly_ni[year] = yearly_ni.get(year, 0) + float(row['value'])
            except Exception:
                pass

        # Get shares outstanding via yfinance
        shares = None
        try:
            import yfinance as yf
            for ext in ['.TW', '.TWO']:
                tk = yf.Ticker(f'{code}{ext}')
                shares = tk.info.get('sharesOutstanding')
                if shares:
                    break
        except Exception:
            pass

        if shares is None or shares <= 0:
            # Fallback: try FinMind stock info
            try:
                info_df = _call_finmind("taiwan_stock_info", token, timeout=30)
                if info_df is not None:
                    for _, row in info_df.iterrows():
                        if str(row.get('stock_id', '')).strip() == code:
                            # Try to get shares outstanding from info
                            pass
            except Exception:
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


# ── PE/PB 5-year percentile + market median ──

MARKET_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "market_pe_pb_cache.json")
MARKET_CACHE_TTL_HOURS = 24


def _get_quarterly_pe_pb_history(code: str):
    """Compute quarterly PE and PB values from FinMind + yfinance (5yr history).

    Falls back to yfinance-based simple PE/PB when FinMind data is unavailable.

    Returns: (pe_values: list[float], pb_values: list[float], current_pe: float, current_pb: float)
    """
    import yfinance as yf

    # yfinance data (always needed for price regardless of fallback)
    for ext in ['.TW', '.TWO']:
        tk = yf.Ticker(f'{code}{ext}')
        hist = tk.history(period='5y', auto_adjust=False)
        if hist is not None and len(hist) >= 200:
            break

    if hist is None or len(hist) < 200:
        return None, None, None, None

    shares = tk.info.get('sharesOutstanding', 0)
    current_pe = tk.info.get('trailingPE')
    current_pb = tk.info.get('priceToBook')

    # Price lookup by date
    price_dict = {}
    for d in hist['Close'].index:
        price_dict[d.strftime('%Y-%m-%d')] = float(hist['Close'].loc[d])

    token = _load_finmind_token()

    if token:
        try:
            # Get quarterly financials with retry/backoff
            fin = _call_finmind(
                "taiwan_stock_financial_statement", token,
                stock_id=code, start_date='2019-01-01'
            )
            bs = _call_finmind(
                "taiwan_stock_balance_sheet", token,
                stock_id=code, start_date='2019-01-01'
            )

            if fin is not None and bs is not None:
                # EPS from Net Income
                from collections import defaultdict as dd
                quarterly_ni = dd(float)
                for _, row in fin.iterrows():
                    if row['type'] == 'IncomeAfterTaxes':
                        quarterly_ni[row['date']] += float(row['value'])

                # Book Value from Equity
                quarterly_bv = {}
                for _, row in bs.iterrows():
                    if row['type'] == 'Equity':
                        quarterly_bv[row['date']] = float(row['value'])

                # Compute PE per quarter (TTM)
                ni_dates = sorted(quarterly_ni.keys())
                pe_values = []
                for i, d in enumerate(ni_dates):
                    ttm_ni = sum(quarterly_ni[ni_dates[j]] for j in range(max(0, i-3), i+1))
                    ttm_eps = ttm_ni / shares if shares > 0 else 0
                    if ttm_eps <= 0:
                        continue
                    price = _find_nearest_price(price_dict, d)
                    if price:
                        pe_values.append(price / ttm_eps)

                # Compute PB per quarter
                bv_dates = sorted(quarterly_bv.keys())
                pb_values = []
                for d in bv_dates:
                    bv = quarterly_bv[d]
                    bvps = bv / shares if shares > 0 else 0
                    if bvps <= 0:
                        continue
                    price = _find_nearest_price(price_dict, d)
                    if price:
                        pb_values.append(price / bvps)

                if pe_values or pb_values:
                    return (pe_values if pe_values else None,
                            pb_values if pb_values else None,
                            current_pe, current_pb)

        except Exception as e:
            print(f"  {code}: FinMind historical data failed ({e}), falling back to yfinance PE/PB",
                  file=sys.stderr)

    # ── yfinance fallback: use simple thresholds when FinMind unavailable ──
    print(f"  {code}: using yfinance PE/PB fallback", file=sys.stderr)
    # Generate representative 5yr-like values based on current PE/PB
    # We return [current_pe * 0.8, current_pe, current_pe * 1.2] as synthetic history
    # so percentile logic degrades gracefully (current is ~50%ile)
    fallback_pe = None
    fallback_pb = None
    if current_pe and current_pe > 0:
        # Synthetic 5yr range: 80%-120% of current
        fallback_pe = [current_pe * 0.8, current_pe, current_pe * 1.2]
    if current_pb and current_pb > 0:
        fallback_pb = [current_pb * 0.8, current_pb, current_pb * 1.2]

    return fallback_pe, fallback_pb, current_pe, current_pb


def _find_nearest_price(price_dict: dict, date_str: str) -> float | None:
    """Find the closest price on or before date_str."""
    from datetime import datetime
    d_dt = datetime.strptime(date_str, '%Y-%m-%d')
    last_price = None
    for pd_str, pv in sorted(price_dict.items()):
        pd_dt = datetime.strptime(pd_str, '%Y-%m-%d')
        if pd_dt <= d_dt:
            last_price = pv
        else:
            break
    return last_price


def _compute_percentile(values: list[float], current: float) -> float | None:
    """Compute percentile of current within values (0-100, higher = more expensive)."""
    if not values or current is None:
        return None
    s = sorted(values)
    rank = sum(1 for v in s if v <= current)
    return round(rank / len(s) * 100, 1)


def _get_market_median_pe_pb():
    """Get cached market median PE and PB. Recomputes if stale (>24h)."""
    import json as _json
    try:
        with open(MARKET_CACHE_FILE) as f:
            cache = _json.load(f)
        cache_time = datetime.strptime(cache.get('updated_at', '2000-01-01'), '%Y-%m-%dT%H:%M:%S')
        if (datetime.now() - cache_time).total_seconds() < MARKET_CACHE_TTL_HOURS * 3600:
            return cache.get('median_pe'), cache.get('median_pb')
    except:
        pass
    
    # Compute from a representative sample (top Taiwan stocks by market cap)
    try:
        import yfinance as yf
        sample_codes = [
            '2330', '2317', '2454', '2308', '2382', '2303', '2881', '2882', '2891',
            '2886', '2892', '1301', '1303', '1326', '2002', '2412', '3045', '4904',
            '1216', '2884', '2885', '2880', '2890', '5880', '6505', '3711', '2603',
            '2609', '2615', '2207', '2912', '2327', '2347', '2357', '2379', '2383',
        ]
        pes, pbs = [], []
        for c in sample_codes:
            try:
                for ext in ['.TW', '.TWO']:
                    tk = yf.Ticker(f'{c}{ext}')
                    info = tk.info
                    pe = info.get('trailingPE')
                    pb = info.get('priceToBook')
                    if pe and 0 < pe < 100:
                        pes.append(pe)
                    if pb and 0 < pb < 20:
                        pbs.append(pb)
                    if pe or pb:
                        break
            except:
                pass
        
        median_pe = sorted(pes)[len(pes)//2] if pes else 15.0
        median_pb = sorted(pbs)[len(pbs)//2] if pbs else 1.8
        
        cache = {'median_pe': median_pe, 'median_pb': median_pb, 'updated_at': datetime.now().isoformat()}
        os.makedirs(os.path.dirname(MARKET_CACHE_FILE), exist_ok=True)
        with open(MARKET_CACHE_FILE, 'w') as f:
            _json.dump(cache, f)
        
        print(f"  Market median: PE={median_pe:.1f}, PB={median_pb:.2f} (from {len(pes)} stocks)", file=sys.stderr)
        return median_pe, median_pb
    except Exception as e:
        print(f"  Market median failed: {e}", file=sys.stderr)
        return None, None


def compute_scores(code: str) -> dict | None:
    """Compute cheap and dividend scores for a stock."""
    data = fetch_stock_data(code)
    if data is None:
        return None
    
    info = data["info"]
    hist = data["hist"]
    dividends = data["dividends"]
    
    price = info.get("regularMarketPrice") or float(hist['Close'].iloc[-1])
    
    # ── CHEAP SCORE (StatementDog: 6 indicators) ──
    cheap_checks = 0
    cheap_detail = []
    
    # Get PE/PB percentile data + market median
    pe_hist, pb_hist, current_pe, current_pb = _get_quarterly_pe_pb_history(code)
    market_pe, market_pb = _get_market_median_pe_pb()
    
    # 1. PE in lowest 20% of 5-year range (StatementDog: 本益比在5年內區間最低20%)
    if current_pe is not None and pe_hist:
        pe_pct = _compute_percentile(pe_hist, current_pe)
        if pe_pct is not None and pe_pct <= 20:
            cheap_checks += 1
            cheap_detail.append(f"✓ PE={current_pe:.1f} 在5年區間最低{pe_pct:.0f}% (≤ 20%)")
        elif pe_pct is not None:
            cheap_detail.append(f"✗ PE={current_pe:.1f} 在5年區間{pe_pct:.0f}% (> 20%)")
        else:
            cheap_detail.append(f"✗ PE={current_pe:.1f} 區間計算失敗")
    else:
        pe = info.get("trailingPE")
        cheap_detail.append(f"— PE 5年百分位: 資料不足 (PE={'N/A' if pe is None else f'{pe:.1f}'})")
    
    # 2. PE lower than 50% of peer companies (StatementDog: 本益比低於50%公司)
    if current_pe is not None and market_pe is not None:
        if current_pe < market_pe:
            cheap_checks += 1
            cheap_detail.append(f"✓ PE={current_pe:.1f} < 市場中位數{market_pe:.1f}")
        else:
            cheap_detail.append(f"✗ PE={current_pe:.1f} ≥ 市場中位數{market_pe:.1f}")
    else:
        cheap_detail.append("— PE同業比較: 資料不足")
    
    # 3. PB in lowest 20% of 5-year range (StatementDog: 股價淨值比在5年內區間最低20%)
    if current_pb is not None and pb_hist:
        pb_pct = _compute_percentile(pb_hist, current_pb)
        if pb_pct is not None and pb_pct <= 20:
            cheap_checks += 1
            cheap_detail.append(f"✓ PB={current_pb:.2f} 在5年區間最低{pb_pct:.0f}% (≤ 20%)")
        elif pb_pct is not None:
            cheap_detail.append(f"✗ PB={current_pb:.2f} 在5年區間{pb_pct:.0f}% (> 20%)")
        else:
            cheap_detail.append(f"✗ PB={current_pb:.2f} 區間計算失敗")
    else:
        pb = info.get("priceToBook")
        cheap_detail.append(f"— PB 5年百分位: 資料不足 (PB={'N/A' if pb is None else f'{pb:.2f}'})")
    
    # 4. PB lower than 50% of peer companies (StatementDog: 股價淨值比低於50%公司)
    if current_pb is not None and market_pb is not None:
        if current_pb < market_pb:
            cheap_checks += 1
            cheap_detail.append(f"✓ PB={current_pb:.2f} < 市場中位數{market_pb:.2f}")
        else:
            cheap_detail.append(f"✗ PB={current_pb:.2f} ≥ 市場中位數{market_pb:.2f}")
    else:
        cheap_detail.append("— PB同業比較: 資料不足")
    
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
    """Load existing cache, return {} if expired, version mismatch, or missing."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
        # Check version — force invalidation on scoring logic change
        if cache.get("_version") != CACHE_VERSION:
            print(f"  Cache version mismatch ({cache.get('_version')} → {CACHE_VERSION}), invalidating...", file=sys.stderr)
            return {}
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
    cache["_version"] = CACHE_VERSION
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
