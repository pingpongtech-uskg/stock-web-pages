#!/usr/bin/env python3
"""
📡 每日監控：52週高點跌40%+ 買入訊號
Phase 0: 檢查上市櫃總數變動
Phase 1: 52週高點跌幅掃描 (yfinance → FinMind fallback)
Phase 2: 3.5年回歸線篩選
Phase 3: 基本面評分 (省API快取模式)
Phase 4: 出榜檢查
Phase 5: 輸出報告
Phase 6: 資料庫增量更新

排程: 每交易日 14:00 UTC (22:00 TST)
"""

import json, os, time, warnings, sys
from datetime import datetime, timedelta
from collections import defaultdict
warnings.filterwarnings('ignore')
import yfinance as yf
import numpy as np
import urllib.request, urllib.error
from _data_fetcher import fetch_data, yf_quarterly_revenue, fm_sg

# ─── Config ───
BASE_DIR = os.path.expanduser("~/tw-stock-monitor")
DATA_DIR = f"{BASE_DIR}/data"
OUTPUT_DIR = f"{BASE_DIR}/output"
SCORE_DIR = f"{OUTPUT_DIR}/scores"
SCRIPT_DIR = f"{BASE_DIR}/scripts"
LOG_DIR = f"{BASE_DIR}/logs"
os.makedirs(SCORE_DIR, exist_ok=True)
os.makedirs(f"{OUTPUT_DIR}/reports", exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

FINMIND_TOKEN = None
FINMIND_TOKEN_EXPIRED = False
SKIP_LIST_PATH = f"{OUTPUT_DIR}/skip_list.json"

log = lambda m: print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

# ─── Load FinMind token from original file ───
def load_finmind_token():
    global FINMIND_TOKEN
    if FINMIND_TOKEN:
        return FINMIND_TOKEN
    import re
    src_files = [
        f"{SCRIPT_DIR}/download_otc_prices.py",
        f"{SCRIPT_DIR}/full_scoring_v2.py",
    ]
    for fp in src_files:
        if os.path.exists(fp):
            with open(fp) as f:
                content = f.read()
            for m in re.finditer(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", content):
                FINMIND_TOKEN = m.group()
                return FINMIND_TOKEN
    raise RuntimeError("無法找到 FinMind token")


# ─── FinMind reachability 檢查 ───
def check_finmind_token():
    """測試 FinMind 是否可達（非真正過期，單純看 rate limit 狀況）"""
    global FINMIND_TOKEN_EXPIRED
    if not FINMIND_TOKEN:
        FINMIND_TOKEN_EXPIRED = True
        return False
    try:
        from FinMind.data import DataLoader
        api = DataLoader()
        api.login_by_token(api_token=FINMIND_TOKEN)
        from _data_fetcher import _fm_wait, _fm_register
        w = _fm_wait()
        if w > 0:
            time.sleep(w)
        _fm_register()
        df = api.taiwan_stock_month_revenue(stock_id='2330', start_date='2026-05-01')
        FINMIND_TOKEN_EXPIRED = False
        return df is not None and len(df) > 0
    except Exception as e:
        err = str(e)
        if 'illegal' in err.lower():
            log("⚠️ FinMind rate limit 擁擠，暫時改用 yfinance")
        FINMIND_TOKEN_EXPIRED = False  # token 不會過期，永不設 true
        return False


# ─── Skip list for stocks that can't be downloaded ───
def load_skip_list():
    if os.path.exists(SKIP_LIST_PATH):
        with open(SKIP_LIST_PATH) as f:
            return set(json.load(f))
    return set()

def save_skip_list(skip_set):
    with open(SKIP_LIST_PATH, 'w') as f:
        json.dump(sorted(skip_set), f)


# ═══════════════════════════════════════════
# PHASE 0: 檢查上市櫃總數變動
# ═══════════════════════════════════════════

def phase0_check_new_listings():
    """比對 TWSE/TPEx API 清單，找出新股"""
    log("📡 Phase 0: 檢查上市櫃總數變動...")
    
    # TWSE 上市
    try:
        req = urllib.request.Request(
            'https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=json',
            headers={'User-Agent': 'Mozilla/5.0'})
        twse = json.loads(urllib.request.urlopen(req, timeout=15).read())
        twse_codes = [r[0] for r in twse['data'] 
                      if r[0].isdigit() and len(r[0])==4 and not r[0].startswith('0')]
    except Exception as e:
        log(f"   TWSE API 失敗: {e}")
        twse_codes = []
    
    # TPEx 上櫃
    try:
        req = urllib.request.Request(
            'https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d=2026/05/22&s=0,asc,0',
            headers={'User-Agent': 'Mozilla/5.0'})
        otc = json.loads(urllib.request.urlopen(req, timeout=15).read())
        otc_codes = [r[0] for r in otc['tables'][0]['data']
                     if r[0].isdigit() and len(r[0])==4 and not r[0].startswith('0')]
    except Exception as e:
        log(f"   TPEx API 失敗: {e}")
        otc_codes = []
    
    api_codes = set(twse_codes) | set(otc_codes)
    log(f"   TWSE {len(twse_codes)} + TPEx {len(otc_codes)} = {len(api_codes)} 檔")
    
    # 比對現有資料庫
    existing = set()
    for i in range(1, 26):
        p = f"{DATA_DIR}/batch_{i:03d}.json"
        if os.path.exists(p):
            with open(p) as f:
                for sym in json.load(f):
                    existing.add(sym.split('.')[0])
    
    new_codes = sorted(api_codes - existing)
    
    # 也檢查已下市的（在資料庫但不在 API）
    removed = existing - api_codes
    if removed:
        log(f"   已下市/不存在: {len(removed)} 檔（資料庫仍保留）")
    
    if not new_codes:
        log(f"   無新股，資料庫已是最新")
        return []
    
    log(f"   發現 {len(new_codes)} 檔新股！")
    return new_codes


def download_new_stock(code, suffix):
    """用 yfinance 或 FinMind 下載單一新股歷史資料"""
    # yfinance first
    for s in ['.TWO', '.TW']:
        try:
            raw = yf.download(f"{code}{s}", period="max", progress=False, auto_adjust=False)
            if raw is not None and len(raw) > 200:
                c = raw['Close']
                c = c.iloc[:, 0] if hasattr(c, 'iloc') and c.ndim > 1 else c
                v = raw['Volume']
                v = v.iloc[:, 0] if hasattr(v, 'iloc') and v.ndim > 1 else v
                return {
                    'dates': raw.index.strftime('%Y-%m-%d').tolist(),
                    'close': [round(float(x),2) for x in c.values],
                    'volume': [int(x) for x in v.values],
                    'start': str(raw.index[0].date()),
                    'end': str(raw.index[-1].date()),
                    'days': len(raw), 'name': ''
                }, suffix
        except:
            pass
    
    # FinMind fallback
    try:
        from FinMind.data import DataLoader
        api = DataLoader()
        api.login_by_token(api_token=FINMIND_TOKEN)
        df = api.taiwan_stock_price(stock_id=code, start_date='2010-01-01')
        if df is not None and len(df) > 200:
            df = df.sort_values('date')
            return {
                'dates': df['date'].tolist(),
                'close': [float(x) for x in df['close']],
                'volume': [int(x) for x in df['volume']],
                'start': df['date'].iloc[0],
                'end': df['date'].iloc[-1],
                'days': len(df), 'name': ''
            }, suffix
    except:
        pass
    
    return None, suffix


def phase0_add_new_listings(new_codes, skip_list):
    """下載新股資料並合併到資料庫，跳過黑名單"""
    added = 0
    for code in new_codes:
        if code in skip_list:
            log(f"   ⏭️ {code} 在黑名單中，跳過")
            continue
        
        # Determine exchange
        suffix = '.TW'  # default
        
        # For better exchange detection - check first digit
        code_first = int(code[0])
        if code_first >= 2 or code_first == 0:
            suffix = '.TWO'  # Most 2xxx+ are OTC
        if code_first == 1:
            suffix = '.TW'   # 1xxx are TSE
        # 6xxx can be either - check against cached API results
        if code_first == 6:
            suffix = '.TW'  # try TSE first for 6xxx
        
        result, _ = download_new_stock(code, suffix)
        if not result and suffix == '.TW':
            # Try OTC
            result, _ = download_new_stock(code, '.TWO')
        if result:
            # Merge into batch files
            all_stocks = {}
            for i in range(1, 26):
                p = f"{DATA_DIR}/batch_{i:03d}.json"
                if os.path.exists(p):
                    with open(p) as f:
                        all_stocks.update(json.load(f))
            
            all_stocks[f"{code}{suffix}"] = result
            
            tickers = sorted(all_stocks.keys())
            chunks = [tickers[i:i+100] for i in range(0, len(tickers), 100)]
            for ci, chunk in enumerate(chunks):
                cd = {t: all_stocks[t] for t in chunk}
                p = f"{DATA_DIR}/batch_{ci+1:03d}.json"
                with open(p, 'w') as f:
                    json.dump(cd, f, ensure_ascii=False)
            
            added += 1
            log(f"   ✅ {code} 加入資料庫")
        else:
            log(f"   ⚠️ {code} 無法下載資料（加入黑名單）")
            skip_list.add(code)
            save_skip_list(skip_list)
    
    return added


# ═══════════════════════════════════════════
# PHASE 1: 52週高點跌幅掃描
# ═══════════════════════════════════════════

def calc_drawdown(close_series, high_series):
    """計算距 252 天最高跌幅"""
    if len(close_series) < 50:
        return None, None
    current = float(close_series[-1])
    high_52w = float(high_series[-252:].max()) if len(high_series) >= 252 else float(high_series.max())
    if high_52w <= 0:
        return None, None
    dd = (current - high_52w) / high_52w * 100
    return dd, current


def fetch_price_stock(code, suffix):
    """抓單股 1y 價格，yfinance 優先，FinMind 備援"""
    # yfinance
    try:
        raw = yf.download(f"{code}{suffix}", period="1y", progress=False, auto_adjust=False)
        if raw is not None and len(raw) >= 50:
            close = raw['Close'].iloc[:, 0] if hasattr(raw['Close'], 'iloc') and raw['Close'].ndim > 1 else raw['Close']
            close = close.dropna()
            high = raw['High'].iloc[:, 0] if hasattr(raw['High'], 'iloc') and raw['High'].ndim > 1 else raw['High']
            high = high.dropna()
            vol = raw['Volume'].iloc[:, 0] if hasattr(raw['Volume'], 'iloc') and raw['Volume'].ndim > 1 else raw['Volume']
            vol = vol.dropna()
            return close, high, vol
    except:
        pass
    
    # FinMind fallback
    try:
        from FinMind.data import DataLoader
        api = DataLoader()
        api.login_by_token(api_token=FINMIND_TOKEN)
        df = api.taiwan_stock_price(stock_id=code, start_date=(datetime.now()-timedelta(days=400)).strftime('%Y-%m-%d'))
        if df is not None and len(df) >= 50:
            df = df.sort_values('date').tail(365)
            close = df['close'].values
            high = df['max_price'].values if 'max_price' in df else df['close'].values
            import pandas as pd
            return pd.Series(close), pd.Series(high), pd.Series([0]*len(close))  # vol proxy
    except:
        pass
    
    return None, None, None


def phase1_scan(all_codes):
    """掃描所有股票，找出跌40%+的"""
    log("📡 Phase 1: 52週高點跌幅掃描...")
    hits = []
    failed_fetch = set()
    total = len(all_codes)
    
    for i, sym in enumerate(all_codes):
        if (i+1) % 200 == 0:
            log(f"   [{i+1}/{total}] {len(hits)} hits")
        
        code = sym.split('.')[0]
        suffix = '.TWO' if sym.endswith('.TWO') else '.TW'
        exchange = 'OTC' if suffix == '.TWO' else 'TSE'
        
        close, high, vol = fetch_price_stock(code, suffix)
        if close is None:
            failed_fetch.add(code)
            continue
        
        dd, cur_price = calc_drawdown(close, high)
        if dd is None:
            continue
        
        if dd <= -40:
            avg_vol_5d = int(vol.tail(5).mean()) if len(vol) >= 5 else 0
            hits.append({
                'code': code, 'exchange': exchange,
                'price': round(cur_price, 2) if cur_price else 0,
                'high_52w': round(float(high[-252:].max()) if len(high) >= 252 else float(high.max()), 2),
                'dd_pct': round(dd, 2),
                'avg_vol_5d': avg_vol_5d,
            })
    
    log(f"   ✅ 完成: {len(hits)} 檔跌40%+")
    return hits, failed_fetch


# ═══════════════════════════════════════════
# PHASE 2: 回歸線篩選
# ═══════════════════════════════════════════

def calc_regression(prices):
    """3.5年(882天)回歸線 — 使用對數價格解決乘數效應"""
    p = prices[-882:] if len(prices) >= 882 else prices
    log_p = np.log(p)  # log transform: 價格乘數變加法, 殘差變%
    x = np.arange(len(log_p))
    slope, intercept = np.polyfit(x, log_p, 1)
    residuals = log_p - (slope * x + intercept)
    std = np.std(residuals)
    z = (log_p[-1] - (slope * (len(log_p)-1) + intercept)) / std if std > 0 else 0
    # Return log-slope (可轉年化報酬) and z-score
    return slope, z


def fetch_prices_for_regression(code, suffix, lookback=400):
    """抓足夠的價格資料做回歸"""
    # Try database first
    for i in range(1, 26):
        p = f"{DATA_DIR}/batch_{i:03d}.json"
        if os.path.exists(p):
            with open(p) as f:
                batch = json.load(f)
            key = f"{code}{suffix}"
            if key in batch:
                data = batch[key]
                if len(data['close']) >= 200:
                    prices = np.array(data['close'])
                    return prices
    
    # yfinance
    try:
        raw = yf.download(f"{code}{suffix}", period="max", progress=False, auto_adjust=False)
        if raw is not None and len(raw) >= 200:
            close = raw['Close'].iloc[:, 0] if hasattr(raw['Close'], 'iloc') and raw['Close'].ndim > 1 else raw['Close']
            return close.dropna().values
    except:
        pass
    
    return None


# Load all prices from batch files into memory
def load_all_prices():
    prices = {}
    for i in range(1, 26):
        p = f"{DATA_DIR}/batch_{i:03d}.json"
        if os.path.exists(p):
            with open(p) as f:
                batch = json.load(f)
            for sym, data in batch.items():
                if len(data['close']) >= 200:
                    prices[sym] = np.array(data['close'])
    return prices


def phase2_regression_filter(hits, all_prices):
    """回歸線斜率≥0 且 Z≤-1（使用預載價格）"""
    if not hits:
        return []
    log(f"📡 Phase 2: 回歸線篩選 ({len(hits)} 檔)...")
    passed = []
    for s in hits:
        suffix = '.TWO' if s['exchange'] == 'OTC' else '.TW'
        key = f"{s['code']}{suffix}"
        prices = all_prices.get(key)
        if prices is None or len(prices) < 200:
            # Fallback to yfinance
            prices = fetch_prices_for_regression(s['code'], suffix)
        if prices is None or len(prices) < 200:
            continue
        slope, z = calc_regression(prices)
        s['regression_slope'] = round(slope, 6)
        s['regression_z'] = round(z, 2)
        if slope >= 0 and z <= -1:
            passed.append(s)
    log(f"   ✅ 通過: {len(passed)} / {len(hits)}")
    return passed


# ═══════════════════════════════════════════
# PHASE 3: 基本面評分（省API快取模式）
# ═══════════════════════════════════════════

def load_score_cache(code):
    path = f"{SCORE_DIR}/{code}.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def save_score_cache(code, data):
    path = f"{SCORE_DIR}/{code}.json"
    with open(path, 'w') as f:
        json.dump(data, f, ensure_ascii=False)


def cache_needs_update(cache):
    """判斷快取是否需要更新"""
    if not cache:
        return 'full'
    last_updated = cache.get('last_updated', 0)
    age_days = (datetime.now().timestamp() - last_updated) / 86400
    
    if age_days < 90:
        return 'skip'      # 直接用
    elif age_days < 180:
        return 'incremental'  # 只抓最新季
    else:
        return 'full'      # 整筆重跑


def safe_finmind(func_name, stock_id, **kwargs):
    """FinMind API 含 rate limit 控管 — 被拒直接跳過"""
    try:
        from FinMind.data import DataLoader
        api = DataLoader()
        api.login_by_token(api_token=FINMIND_TOKEN)
        
        from _data_fetcher import _fm_wait, _fm_register
        w = _fm_wait()
        if w > 0:
            time.sleep(w)
        _fm_register()
        
        func = getattr(api, func_name)
        df = func(stock_id=stock_id, **kwargs)
        return df
    except Exception as e:
        err = str(e)
        if 'illegal' not in err.lower() and 'upper limit' not in err.lower():
            time.sleep(5)
            try:
                from FinMind.data import DataLoader
                api = DataLoader()
                api.login_by_token(api_token=FINMIND_TOKEN)
                func = getattr(api, func_name)
                return func(stock_id=stock_id, **kwargs)
            except:
                pass
    return None


def calc_score_fresh(stock_id):
    """全新評分：yfinance 主力 → FinMind 備援"""
    finmind_api = None
    if not FINMIND_TOKEN_EXPIRED:
        try:
            from FinMind.data import DataLoader
            api_tmp = DataLoader()
            api_tmp.login_by_token(api_token=FINMIND_TOKEN)
            finmind_api = api_tmp
        except:
            pass
    
    result = {'g': [False]*5, 'l': [False]*6, 'd': [False]*5}
    
    # ── 擷取資料（yfinance 主力） ──
    fin = fetch_data(stock_id, 'financial_statement', finmind_api, start_date='2023-01-01')
    cf = fetch_data(stock_id, 'cash_flow', finmind_api, start_date='2019-01-01')
    bs = fetch_data(stock_id, 'balance_sheet', finmind_api, start_date='2019-01-01')
    div = fetch_data(stock_id, 'dividend', finmind_api, start_date='2015-01-01')
    
    # g1: 月營收YOY（FinMind 優先，yfinance 季度備援）
    rev = None
    if finmind_api:
        rev = fm_sg(finmind_api, 'taiwan_stock_month_revenue', stock_id, start_date='2024-01-01')
    if rev is None or len(rev) < 6:
        rev = yf_quarterly_revenue(stock_id)
        # 季度模式：取最後4季 vs 前4季 YoY
        if rev is not None and len(rev) >= 4:
            recent = rev.tail(2)  # 最近2季
            yoy_ok = 0
            for _, row in recent.iterrows():
                d = row['date']
                yr_ago = f"{int(d[:4])-1}-{d[5:]}"
                prev = rev[rev['date'] == yr_ago]
                if len(prev) > 0:
                    cur_r = float(row['revenue'])
                    prev_r = float(prev.iloc[0]['revenue'])
                    if prev_r > 0 and cur_r > prev_r:
                        yoy_ok += 1
            if yoy_ok >= 2:
                result['g'][0] = True
        elif rev is not None and len(rev) >= 6:
            # 月模式（從上面 FinMind 或 yfinance 月營收來）
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
    else:
        # FinMind 月營收模式
        if len(rev) >= 6:
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
    
    # g2-g5: 損益表
    if fin is not None and len(fin) > 0:
        fp = defaultdict(dict)
        for _, row in fin.iterrows():
            fp[row['date']][row['type']] = row['value']
        dates = sorted(fp.keys())
        fp_d = {d: dict(v) for d, v in fp.items()}
        growth_checks = {'g2': ('GrossProfit', 1), 'g3': ('OperatingIncome', 2),
                         'g4': ('PreTaxIncome', 3), 'g5': ('IncomeAfterTaxes', 4)}
        if len(dates) >= 5:
            latest = dates[-1]
            prev_year = dates[-5]
            if prev_year in fp:
                cur, prev = fp[latest], fp[prev_year]
                for key, (field, idx) in growth_checks.items():
                    if field in cur and field in prev:
                        try:
                            cur_v = float(cur[field])
                            prev_v = float(prev[field])
                            if cur_v > 0 and cur_v > prev_v:
                                result['g'][idx] = True
                        except: pass
    
    # l1-l4: 現金流
    if cf is not None and len(cf) > 0:
        cfp = defaultdict(dict)
        for _, row in cf.iterrows():
            cfp[row['date']][row['type']] = row['value']
        cf_dates = sorted(cfp.keys())
        
        # 有 FreeCashFlow 直接欄位就用，沒有就 CFO - CapEx 算
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
                try:
                    year = d[:4]
                    cfo = float(cfp[d].get('CashFlowsFromOperatingActivities', 0) or 0)
                    capex = float(cfp[d].get('PropertyPlantAndEquipment', 0) or 0)
                    fcf = cfo - abs(capex)
                    annual_fcf[year] = annual_fcf.get(year, 0) + fcf
                    quarter_counts[year] = quarter_counts.get(year, 0) + 1
                except: pass
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
    
    # l5-l6: AR & Inventory
    if bs is not None and len(bs) > 0 and fin is not None and len(fin) > 0:
        bsp = defaultdict(dict)
        for _, row in bs.iterrows():
            bsp[row['date']][row['type']] = row['value']
        bs_dates = sorted(bsp.keys())
        
        fp = defaultdict(dict)
        for _, row in fin.iterrows():
            fp[row['date']][row['type']] = row['value']
        fp_d = {d: dict(v) for d, v in fp.items()}
        
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
                    cur_rev_d = next((d for d in fp_d if d.startswith(l_ym) and rev_field in fp_d[d]), None)
                    prev_rev_d = next((d for d in fp_d if d.startswith(p_ym) and rev_field in fp_d[d]), None)
                    if cur_rev_d and prev_rev_d:
                        r_cur = float(fp_d[cur_rev_d][rev_field])
                        r_prev = float(fp_d[prev_rev_d][rev_field])
                        if r_cur > 0 and r_prev > 0:
                            d_cur = cur_v / r_cur * 365
                            d_prev = prev_v / r_prev * 365
                            if d_cur <= d_prev: result['l'][4+chk_idx] = True
            except: pass
    
    # d1-d5: 股息
    if div is not None and len(div) > 0:
        ds = div.sort_values('date').tail(5)
        if len(ds) >= 5:
            positive_divs = [x for x in ds['CashEarningsDistribution'] if x and float(x) > 0]
            if len(positive_divs) >= 3:
                result['d'][2] = True
        
        # Get current price from database
        cur_price = None
        for i in range(1, 26):
            p = f"{DATA_DIR}/batch_{i:03d}.json"
            if os.path.exists(p):
                with open(p) as f:
                    batch = json.load(f)
                for sym, data in batch.items():
                    if sym.split('.')[0] == stock_id and len(data['close']) > 0:
                        cur_price = data['close'][-1]
                        break
                if cur_price: break
        
        if cur_price and cur_price > 0:
            if len(ds) >= 1:
                try:
                    last_cash = float(ds.iloc[-1].get('CashEarningsDistribution', 0) or 0)
                    if last_cash / cur_price * 100 > 6: result['d'][0] = True
                except: pass
            if len(ds) >= 5:
                try:
                    cds = [float(x) for x in ds['CashEarningsDistribution'] if x and float(x) > 0]
                    if len(cds) >= 3 and (sum(cds)/len(cds))/cur_price*100 > 6:
                        result['d'][1] = True
                except: pass
        
        # d4-d5: payout ratio
        if fin is not None and len(fin) > 0 and len(ds) > 0:
            fp = defaultdict(dict)
            for _, row in fin.iterrows():
                fp[row['date']][row['type']] = row['value']
            fp_d = {d: dict(v) for d, v in fp.items()}
            ratios = []
            for _, drow in ds.iterrows():
                dy = str(drow['date'])[:4]
                for fd, fv in fp_d.items():
                    if fd[:4] == dy and 'EPS' in fv:
                        try:
                            eps = float(fv['EPS'] or 0)
                            cash = float(drow.get('CashEarningsDistribution', 0) or 0)
                            if eps > 0: ratios.append(cash / eps)
                        except: pass
                        break
            if len(ratios) >= 3:
                ok = sum(1 for r in ratios if r > 0.5)
                if ok >= 3: result['d'][3] = True
                if sum(ratios)/len(ratios) > 0.5: result['d'][4] = True
    
    # 計算獨立分數（比照財報狗）
    growth_pct = sum(result['g']) * 20        # 5項, 每項20%, 0-100%
    landmine_pct = sum(result['l']) * (100/6) # 6項, 每項16.67%, 0-100%
    div_score = sum(result['d']) * 4          # 5項, 每項4分, 0-20

    # 總分保留向後相容（以成長+地雷為主，股息為輔）
    total_score = growth_pct + landmine_pct + div_score
    
    # 金獎/銀獎/銅獎判斷（比照財報狗：地雷≥80% + 成長≥60%為金獎）
    if landmine_pct >= 80 and growth_pct >= 60:
        grade = '金獎'
    elif landmine_pct >= 60 or growth_pct >= 60:
        grade = '銀獎'
    elif landmine_pct >= 40 or growth_pct >= 40:
        grade = '銅獎'
    elif landmine_pct >= 20 or growth_pct >= 20:
        grade = '觀察'
    else:
        grade = '迴避'
    
    now = datetime.now().timestamp()
    return {
        'score': round(total_score, 1),
        'grade': grade,
        'pass_count': sum(result['g']) + sum(result['l']) + sum(result['d']),
        'growth_pct': round(growth_pct, 1),
        'landmine_pct': round(landmine_pct, 1),
        'div_score': round(div_score, 1),
        'g': [int(x) for x in result['g']],
        'l': [int(x) for x in result['l']],
        'd': [int(x) for x in result['d']],
        'last_updated': now,
    }


def calc_score_incremental(stock_id, cache):
    """增量更新：只抓最新季財報"""
    log(f"     增量更新 {stock_id}...")
    try:
        from FinMind.data import DataLoader
        api = DataLoader()
        api.login_by_token(api_token=FINMIND_TOKEN)
        
        # 抓最新一季
        latest_q = (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')
        fin = api.taiwan_stock_financial_statement(stock_id=stock_id, start_date=latest_q)
        
        if fin is None or len(fin) == 0:
            log(f"     無新季報，使用快取")
            cache['last_updated'] = datetime.now().timestamp()
            save_score_cache(stock_id, cache)
            return cache
        
        # 檢查是否確實有新季報
        fin_dates = sorted(fin['date'].unique())
        latest_fin_date = fin_dates[-1]
        
        cache_latest_q = cache.get('latest_quarter', '')
        if latest_fin_date <= cache_latest_q:
            log(f"     最新季 {latest_fin_date} 無變化")
            cache['last_updated'] = datetime.now().timestamp()
            save_score_cache(stock_id, cache)
            return cache
        
        log(f"     新季報 {latest_fin_date}，整筆重算")
        # 有新資料，整筆重跑
        new_score = calc_score_fresh(stock_id)
        new_score['latest_quarter'] = latest_fin_date
        save_score_cache(stock_id, new_score)
        return new_score
    except:
        log(f"     增量失敗，使用快取")
        return cache


def phase3_scoring(passed_hits):
    """為通過回歸線的股票評分（省API快取模式）"""
    if not passed_hits:
        return []
    log(f"📡 Phase 3: 基本面評分 ({len(passed_hits)} 檔)...")
    
    new_scores = 0
    cache_hits = 0
    
    for s in passed_hits:
        code = s['code']
        cache = load_score_cache(code)
        
        if cache:
            action = cache_needs_update(cache)
            if action == 'skip':
                s['score'] = cache['score']
                s['score_grade'] = cache['grade']
                cache_hits += 1
                continue
            elif action == 'incremental':
                updated = calc_score_incremental(code, cache)
                s['score'] = updated['score']
                s['score_grade'] = updated['grade']
                continue
            else:
                log(f"   快取過期，整筆重算 {code}")
        
        log(f"   新評分 {code}...")
        score = calc_score_fresh(code)
        
        # 抓最新季
        try:
            from FinMind.data import DataLoader
            api = DataLoader()
            api.login_by_token(api_token=FINMIND_TOKEN)
            fin = api.taiwan_stock_financial_statement(stock_id=code, start_date='2023-01-01')
            if fin is not None and len(fin) > 0:
                score['latest_quarter'] = sorted(fin['date'].unique())[-1]
        except:
            pass
        
        save_score_cache(code, score)
        s['score'] = score['score']
        s['score_grade'] = score['grade']
        new_scores += 1
        
        time.sleep(1.5)  # 避免 rate limit
    
    log(f"   ✅ 快取命中: {cache_hits} | 新評分: {new_scores}")
    return passed_hits


# ═══════════════════════════════════════════
# PHASE 4: 出榜檢查
# ═══════════════════════════════════════════

def phase4_expiry_check(all_dd40_hits, scored_list, failed_fetch_codes=None):
    """檢查之前有評分的股票是否已反彈出榜"""
    if failed_fetch_codes is None:
        failed_fetch_codes = set()
    scored_codes = {s['code'] for s in scored_list if s.get('score_grade') in ('金獎', '銀獎')}
    
    # 掃描分數目錄找出所有已評分股票
    expired = []
    for fname in os.listdir(SCORE_DIR):
        if not fname.endswith('.json'):
            continue
        code = fname[:-5]
        if code in scored_codes:
            continue
        
        with open(os.path.join(SCORE_DIR, fname)) as f:
            cache = json.load(f)
        
        # 檢查這支股今天的 dd%
        match = [s for s in all_dd40_hits if s['code'] == code]
        if match:
            # 仍在 dd40+，評分已套用
            continue
        else:
            # 不在今日 dd40 清單，需確認是否因下載失敗而漏掉（Bug 5）
            if code in failed_fetch_codes:
                continue
            
            # 再確認今日是否有成功抓到價格資料，避免 yfinance 404/timeout 誤判
            try:
                suffix = '.TWO' if code[0].isdigit() and (int(code[0]) >= 2 or int(code[0]) == 0) else '.TW'
                test = yf.download(f"{code}{suffix}", period="5d", progress=False, auto_adjust=False)
                if test is None or len(test) == 0:
                    continue  # 今日價格抓不到，不視為反彈
            except:
                continue  # 今日價格抓不到，不視為反彈
            
            expired.append({
                'code': code,
                'reason': '已反彈出榜（不在今日跌40%清單）',
                'last_known_grade': cache.get('grade', ''),
                'last_known_score': cache.get('score', ''),
            })
    
    return expired


# ═══════════════════════════════════════════
# PHASE 5: 輸出報告
# ═══════════════════════════════════════════

def phase5_output(scored_stocks, expired, new_listings_count, added_count):
    """產出 JSON 報告"""
    today = datetime.now().strftime('%Y%m%d')
    date_dir = f"{OUTPUT_DIR}/reports/{today}"
    os.makedirs(date_dir, exist_ok=True)
    
    buy_signals = [s for s in scored_stocks if s.get('score_grade') == '金獎']
    watch_signals = [s for s in scored_stocks if s.get('score_grade') == '銀獎']
    below_60 = [s for s in scored_stocks if s.get('score_grade') not in ('金獎', '銀獎')]
    
    report = {
        'date': today,
        'time': datetime.now().strftime('%H:%M:%S'),
        'new_listings_found': new_listings_count,
        'new_listings_added': added_count,
        'hits_dd40': len(scored_stocks),
        'buy_signals': len(buy_signals),
        'watch_signals': len(watch_signals),
        'expired': len(expired),
        'finmind_rate_limited': FINMIND_TOKEN_EXPIRED,
        'stocks': {
            '🚨 金獎（買入訊號）': [{
                'code': s['code'],
                'exchange': '市' if s.get('exchange')=='TSE' else '櫃',
                'dd_pct': s.get('dd_pct', 0),
                'price': s.get('price', 0),
                'score': s.get('score', 0),
                'url': f"https://statementdog.com/analysis/{s['code']}",
            } for s in buy_signals],
            '👀 銀獎（觀察清單）': [{
                'code': s['code'],
                'exchange': '市' if s.get('exchange')=='TSE' else '櫃',
                'dd_pct': s.get('dd_pct', 0),
                'price': s.get('price', 0),
                'score': s.get('score', 0),
                'url': f"https://statementdog.com/analysis/{s['code']}",
            } for s in watch_signals],
            '⬇ 已反彈出榜': [{
                'code': s['code'],
                'reason': s.get('reason', ''),
                'last_grade': s.get('last_known_grade', ''),
                'last_score': s.get('last_known_score', ''),
                'url': f"https://statementdog.com/analysis/{s['code']}",
            } for s in expired],
        }
    }
    
    path = f"{date_dir}/daily_dd40_{today}.json"
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    log(f"📁 報告存於: {path}")
    return report


# ═══════════════════════════════════════════
# PHASE 6: 資料庫增量更新（收盤價）
# ═══════════════════════════════════════════

def phase6_update_prices():
    """將今日最新收盤價 append 到資料庫（僅保留近3年）"""
    log("📡 Phase 6: 資料庫增量更新...")
    # This is optional - yfinance already fetches latest data in Phase 1.
    # For long-term storage, we could update our database with today's closing prices.
    pass


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════

def main():
    start = time.time()
    log("=" * 50)
    log("📡 每日監控啟動")
    log(f"   日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 初始化 FinMind token
    token = load_finmind_token()
    log(f"   FinMind token: {token[:10]}... ({len(token)} chars)")
    
    # 檢查 FinMind 是否可達
    check_finmind_token()
    
    # 載入黑名單
    skip_list = load_skip_list()
    if skip_list:
        log(f"   無法下載黑名單: {len(skip_list)} 檔")
    
    # Phase 0
    new_codes = phase0_check_new_listings()
    added = 0
    if new_codes:
        added = phase0_add_new_listings(new_codes, skip_list)
        log(f"   新增 {added} / {len(new_codes)} 檔到資料庫")
    new_listings_found = len(new_codes)
    
    # Load all stock codes from database
    all_codes = []
    for i in range(1, 26):
        p = f"{DATA_DIR}/batch_{i:03d}.json"
        if os.path.exists(p):
            with open(p) as f:
                all_codes.extend(json.load(f).keys())
    all_codes = sorted(set(all_codes))
    log(f"   資料庫共 {len(all_codes)} 檔")
    
    # Phase 1
    dd40_hits, failed_fetch = phase1_scan(all_codes)
    
    # 預載價格到記憶體（加速 Phase 2）
    log("📡 預載價格資料到記憶體...")
    all_prices = load_all_prices()
    log(f"   已載入 {len(all_prices)} 檔價格")
    
    # Phase 2
    reg_passed = phase2_regression_filter(dd40_hits, all_prices)
    
    # Phase 3
    scored_stocks = phase3_scoring(reg_passed)
    
    # Phase 4
    expired = phase4_expiry_check(dd40_hits, scored_stocks, failed_fetch)
    
    # Phase 5
    report = phase5_output(scored_stocks, expired, new_listings_found, added)
    
    # Phase 6
    phase6_update_prices()
    
    # Summary
    elapsed = time.time() - start
    log("=" * 50)
    log(f"✅ 監控完成 ({elapsed/60:.1f}分)")
    
    buy = report['stocks']['🚨 金獎（買入訊號）']
    watch = report['stocks']['👀 銀獎（觀察清單）']
    
    if buy:
        log(f"🚨 買入訊號 {len(buy)} 檔:")
        for s in buy:
            log(f"     {s['code']}({s['exchange']}) 跌{s['dd_pct']:.1f}% 評分{s['score']}")
    elif watch:
        log(f"👀 銀獎觀察 {len(watch)} 檔（無金獎）")
        for s in watch[:5]:
            log(f"     {s['code']}({s['exchange']}) 跌{s['dd_pct']:.1f}% 評分{s['score']}")
    else:
        log(f"📭 今日無買入訊號")
    
    return report


if __name__ == '__main__':
    report = main()
