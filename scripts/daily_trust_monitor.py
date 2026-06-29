#!/usr/bin/env python3
"""
📊 每日法人初建倉監控 (v3 — 無遞補版)
======================================
1. TWSE API → 上市投信每日買賣超
2. 快取 → 10日累積股數排名 (上市+上櫃)
3. TOP 30 候選 → yfinance 股價 (fallback FinMind) → 金額排名 → TOP 10
4. FinMind 基本面評分 (best-effort)
5. 輸出 JSON → cron agent 做新聞 + yfinance G/L

規則: 買賣超排行不能遞補。yfinance 失效時用 FinMind。
"""
import os, json, sys, re, time
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np
from bisect import bisect_left
import urllib.request, urllib.error
import warnings
warnings.filterwarnings('ignore')

BASE = os.path.expanduser("~/tw-stock-monitor")
DATA_DIR = f"{BASE}/data"
OUTPUT_DIR = f"{BASE}/output"
TRUST_CACHE_FILE = f"{OUTPUT_DIR}/trust_all_cache.json"
log = lambda m: print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

# 符號 lookup (一次性)
SYM_LOOKUP = {}
for i in range(1, 26):
    p = f"{DATA_DIR}/batch_{i:03d}.json"
    if os.path.exists(p):
        with open(p) as f:
            for sym in json.load(f):
                SYM_LOOKUP[sym.split('.')[0]] = sym

def find_sym(code):
    return SYM_LOOKUP.get(code)

def normalize_date(d):
    if '-' not in d and len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d

# ═══ 1. TWSE API ═════════════════════════════════════════════════
def fetch_twse_daily(date_str=None):
    if date_str is None:
        date_str = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
    url = f'https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALL'
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15
        ) as r:
            data = json.loads(r.read().decode('utf-8'))
    except:
        return None, None
    if data.get('stat') != 'OK' or not data.get('data'):
        return None, None
    result = {}
    for row in data['data']:
        code = row[0].strip()
        if not code.isdigit() or len(code) != 4 or code.startswith('0'):
            continue
        try:
            net = int(row[10].replace(',', ''))
            if net != 0:
                result[code] = net
        except:
            continue
    return result, date_str


def fetch_tpex_daily(date_str=None):
    """抓 TPEx 上櫃投信每日買賣超"""
    if date_str is None:
        date_str = (datetime.now() - timedelta(days=1)).strftime('%Y/%m/%d')
    else:
        date_str = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:8]}"
    url = f'https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&se=AL&t=D&d={date_str}'
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15
        ) as r:
            data = json.loads(r.read().decode('utf-8'))
    except:
        return None, None
    if data.get('stat') not in ('OK', 'ok') or not data.get('tables'):
        return None, None
    result = {}
    for row in data['tables'][0]['data']:
        code = row[0].strip()
        if not code.isdigit() or len(code) != 4:
            continue
        try:
            net = int(row[10].replace(',', ''))
            if net != 0:
                result[code] = net
        except:
            continue
    return result, data.get('date', date_str)

# ═══ 2. 快取管理 ══════════════════════════════════════════════════
def load_cache():
    if os.path.exists(TRUST_CACHE_FILE):
        with open(TRUST_CACHE_FILE) as f:
            cache = json.load(f)
        # Normalize & deduplicate
        for sid in list(cache.keys()):
            dates = [normalize_date(d) for d in cache[sid].get('dates', [])]
            net = cache[sid].get('net', [])
            seen = {}
            for i, d in enumerate(dates):
                seen[d] = i
            if len(seen) < len(dates):
                unique_dates = sorted(seen.keys())
                new_net = [net[seen[d]] for d in unique_dates]
                cache[sid] = {'dates': unique_dates, 'net': new_net}
            else:
                cache[sid]['dates'] = sorted(dates)
        return cache
    return {}

def save_cache(cache):
    with open(TRUST_CACHE_FILE + '.tmp', 'w') as f:
        json.dump(cache, f)
    os.replace(TRUST_CACHE_FILE + '.tmp', TRUST_CACHE_FILE)

def merge_twse(cache, daily, ds):
    ds = normalize_date(ds)
    for code, net in daily.items():
        if code not in cache:
            cache[code] = {'dates': [ds], 'net': [net]}
        elif ds not in cache[code].get('dates', []):
            cache[code].setdefault('dates', []).append(ds)
            cache[code].setdefault('net', []).append(net)
        else:
            idx = cache[code]['dates'].index(ds)
            cache[code]['net'][idx] = net
    return cache

# ═══ 3. 10日累積股數排名 (no API) ════════════════════════════════
def get_share_ranking(cache, as_of):
    """回傳 [(sid, total_shares, last_date), ...] 由大到小。無遞補。"""
    as_of = normalize_date(as_of)
    rankings = []
    for sid, data in cache.items():
        dates = data.get('dates', [])
        net = data.get('net', [])
        if not dates or len(dates) < 5:
            continue
        zd = sorted(zip(dates, net))
        dt = [z[0] for z in zd]
        nv = [z[1] for z in zd]
        i = bisect_left(dt, as_of)
        if i >= len(dt):
            i = len(dt) - 1
        if dt[i] > as_of and i > 0:
            i -= 1
        start = max(0, i - 9)
        ts = sum(nv[j] for j in range(start, i + 1))
        if ts > 0:
            rankings.append((sid, ts, dt[i]))
    rankings.sort(key=lambda x: -x[1])
    return rankings

# ═══ 4. 股價: yfinance → FinMind ════════════════════════════════
_FM_API_FOR_PRICE = None
def _get_fm_price(code):
    """FinMind 股價備援 (當 yfinance 失效時)"""
    global _FM_API_FOR_PRICE
    try:
        from FinMind.data import DataLoader
        if _FM_API_FOR_PRICE is None:
            src = f"{BASE}/scripts/download_otc_prices.py"
            with open(src) as f:
                content = f.read()
            for m in re.finditer(r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+', content):
                tok = m.group()
                break
            _FM_API_FOR_PRICE = DataLoader()
            _FM_API_FOR_PRICE.login_by_token(api_token=tok)
        df = _FM_API_FOR_PRICE.taiwan_stock_daily(stock_id=code, start_date=(datetime.now()-timedelta(days=10)).strftime('%Y-%m-%d'))
        if df is not None and len(df) > 0:
            return float(df.sort_values('date').iloc[-1]['close'])
    except:
        pass
    return None

def guess_exchange(code):
    """Guess exchange suffix: try TW first (most 投信 active on TSE)"""
    for ext in ['.TW', '.TWO']:
        yield ext


def get_price(code):
    """股價: yfinance 優先 → FinMind 備援"""
    import yfinance as yf
    for ext in guess_exchange(code):
        try:
            tk = yf.Ticker(f"{code}{ext}")
            info = tk.info
            name = info.get('longName') or info.get('shortName') or code
            hist = tk.history(period='5d')
            if hist is not None and len(hist) > 0:
                return name, float(hist['Close'].iloc[-1])
            price = (info.get('currentPrice') or info.get('regularMarketPrice')
                     or info.get('previousClose'))
            if price and price > 0:
                return name, price
        except:
            pass
    
    # Fallback: FinMind
    name = code
    price = _get_fm_price(code)
    if price and price > 0:
        return code, price
    return code, None

# ═══ 5. FinMind 基本面 (best-effort) ═════════════════════════════
FM_TOKEN = None
def _init_fm():
    global FM_TOKEN
    if FM_TOKEN:
        return FM_TOKEN
    src = f"{BASE}/scripts/download_otc_prices.py"
    if not os.path.exists(src):
        return None
    with open(src) as f:
        content = f.read()
    for m in re.finditer(r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+', content):
        tok = m.group(); return tok
    return FM_TOKEN if FM_TOKEN else None

def get_fm_api():
    tok = _init_fm()
    if not tok:
        return None
    try:
        from FinMind.data import DataLoader
        api = DataLoader()
        api.login_by_token(api_token=tok)
        return api
    except:
        return None

def score_stock(code, api):
    result = {'g': [False]*5, 'l': [False]*6}
    gd, ld = [], []
    
    def ff(name, **kw):
        try:
            return getattr(api, name)(**kw)
        except:
            return None
    
    # G1: 營收YoY
    rev = ff('taiwan_stock_month_revenue', stock_id=code, start_date='2024-01-01')
    if rev is not None and len(rev) >= 6:
        rs = rev.sort_values('date')
        yoy = 0
        for _, r in rs.tail(3).iterrows():
            yr = f"{int(r['date'][:4])-1}-{r['date'][5:]}"
            p = rs[rs['date'] == yr]
            if len(p) > 0 and float(r['revenue']) > float(p.iloc[0]['revenue']):
                yoy += 1
        if yoy >= 3:
            result['g'][0] = True
            gd.append('✅ 營收YoY連3月正')
    
    # G2-G5: 損益
    fin = ff('taiwan_stock_financial_statement', stock_id=code, start_date='2023-01-01')
    if fin is not None and len(fin) > 0:
        fp = defaultdict(dict)
        for _, r in fin.iterrows():
            fp[r['date']][r['type']] = r['value']
        ds = sorted(fp)
        if len(ds) >= 5 and ds[-5] in fp:
            for field, idx, label in [('GrossProfit',1,'毛利'),('OperatingIncome',2,'營業利益'),
                                       ('PreTaxIncome',3,'稅前淨利'),('IncomeAfterTaxes',4,'稅後淨利')]:
                if field in fp[ds[-1]] and field in fp[ds[-5]]:
                    cv, pv = float(fp[ds[-1]][field]), float(fp[ds[-5]][field])
                    if cv > 0 and cv > pv:
                        result['g'][idx] = True
                        gd.append(f'✅ {label}YoY成長')
    
    # L1-L4: 現金流
    cf = ff('taiwan_stock_cash_flows_statement', stock_id=code, start_date='2019-01-01')
    if cf is not None and len(cf) > 0:
        cfp = defaultdict(dict)
        for _, r in cf.iterrows():
            cfp[r['date']][r['type']] = r['value']
        cfd = sorted(cfp)
        afcf, qc = {}, {}
        for d in cfd:
            y = d[:4]
            cfo = float(cfp[d].get('CashFlowsFromOperatingActivities',0) or 0)
            cx = float(cfp[d].get('PropertyPlantAndEquipment',0) or 0)
            afcf[y] = afcf.get(y,0) + cfo - abs(cx)
            qc[y] = qc.get(y,0) + 1
        # 取最近 5 年
        years = sorted(afcf.keys(), reverse=True)[:5]
        fcfv = [afcf[y] for y in years if qc.get(y, 0) >= 3]
        if len(fcfv) >= 3:
            if sum(1 for v in fcfv if v > 0) >= 3:
                result['l'][0] = True; ld.append('✅ 近5年3年FCF>0')
            if sum(fcfv) / len(fcfv) > 0:
                result['l'][1] = True; ld.append('✅ 近5年平均FCF>0')
        if fin is not None:
            fp = defaultdict(dict)
            for _, r in fin.iterrows():
                fp[r['date']][r['type']] = r['value']
            # 合併到年：每年 CFO/NI 取加權平均（用 NI 加權）
            cy_pairs = defaultdict(list)
            for d in cfd:
                if d in fp:
                    try:
                        cfo = float(cfp[d].get('CashFlowsFromOperatingActivities', 0) or 0)
                        ni = float(fp[d].get('IncomeAfterTaxes', 0) or 0)
                        if ni > 0:
                            cy_pairs[d[:4]].append(cfo / ni * 100)
                    except:
                        pass
            # 每年取平均，最近 5 年
            yr_ratios = [(y, sum(vals) / len(vals)) for y, vals in sorted(cy_pairs.items(), reverse=True)[:5] if vals]
            if len(yr_ratios) >= 3:
                ok_years = sum(1 for _, r in yr_ratios if r > 100)
                if ok_years >= 3:
                    result['l'][2] = True
                    ld.append('✅ 近5年3年CFO/NI>100%')
                if sum(r for _, r in yr_ratios) / len(yr_ratios) > 100:
                    result['l'][3] = True
                    ld.append('✅ 近5年平均CFO/NI>100%')
    
    # L5-L6: AR & Inventory turnover (需 balance sheet)
    bs = ff('taiwan_stock_balance_sheet', stock_id=code, start_date='2019-01-01')
    if bs is not None and len(bs) > 0 and fin is not None and len(fin) > 0:
        bsp = defaultdict(dict)
        for _, r in bs.iterrows():
            bsp[r['date']][r['type']] = r['value']
        bsd = sorted(bsp)
        
        fp = defaultdict(dict)
        for _, r in fin.iterrows():
            fp[r['date']][r['type']] = r['value']
        
        for chk_idx, (bs_field, rev_field, label) in enumerate([
            ('AccountsReceivableNet', 'Revenue', 'AR週轉'),
            ('Inventories', 'Revenue', '存貨週轉')]):
            try:
                l_d = bsd[-1]
                l_ym = l_d[:7]
                p_ym = f"{int(l_d[:4])-1}{l_d[4:7]}"
                prev = None
                for d in bsd:
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
                            if d_cur <= d_prev:
                                result['l'][4+chk_idx] = True
                                ld.append(f'✅ {label}天數改善')
            except: pass
    
    return round(sum(result['g'])/5*100,1), round(sum(result['l'])/6*100,1), gd, ld

# ═══ 6. 回歸線 Z（yfinance 即時價格）══════════════════════════════
def calc_z(code):
    """樂活五線譜 3.5年標準差倍數（yfinance 原始價格）
    
    參數與籌碼K線 APP 一致：
    1. yfinance 抓 5 年每日 close（auto_adjust=False，原始價格）
    2. 取近 3.5 年 (882 交易日)
    3. OLS 回歸 → 趨勢線 + 殘差標準差 σ
    4. Z = (現價 - 趨勢線) / σ
    
    Z = 0   → 價格在趨勢線上（合理價）
    Z = -1  → 價格在趨勢線下方 1σ（便宜）
    Z = -2  → 價格在趨勢線下方 2σ（很便宜）
    """
    try:
        import yfinance as yf
        for ext in guess_exchange(code):
            tk = yf.Ticker(f"{code}{ext}")
            hist = tk.history(period="5y", auto_adjust=False)
            if hist is not None and len(hist) >= 200:
                break
        if hist is None or len(hist) < 200:
            return None
        
        p = hist['Close'].values
        if hasattr(p[0], 'item'):
            p = np.array([float(x) for x in p])
        
        # 3.5 年窗口
        p = p[-882:] if len(p) >= 882 else p
        if len(p) < 100:
            return None
        x = np.arange(len(p))
        slope, intercept = np.polyfit(x, p, 1)
        trend = slope * x + intercept
        residuals = p - trend
        sigma = np.std(residuals, ddof=0)
        if sigma <= 0:
            return None
        
        z = (p[-1] - trend[-1]) / sigma
        return round(z, 2)
    except:
        return None

# ═══ 6.5 中文名稱對照（FinMind）════════════════════════════════════
def load_chinese_names():
    """從 FinMind taiwan_stock_info 建立 code → 繁體中文名稱 對照表"""
    try:
        tok = _init_fm()
        if not tok:
            return {}
        from FinMind.data import DataLoader
        api = DataLoader()
        api.login_by_token(api_token=tok)
        df = api.taiwan_stock_info(timeout=30)
        if df is not None and len(df) > 0:
            name_map = {}
            for _, row in df.iterrows():
                sid = str(row['stock_id']).strip()
                name = str(row['stock_name']).strip()
                if sid and name:
                    name_map[sid] = name
            return name_map
    except Exception as e:
        log(f"⚠️ 中文名稱載入失敗: {e}")
    return {}

# ═══ MAIN ═════════════════════════════════════════════════════════
def main():
    t0 = datetime.now()
    
    # ── 週末／假日防護 ──
    if t0.weekday() >= 5:
        log(f"⏭️ 跳過：今天 {t0.strftime('%Y-%m-%d')} 是週{'六' if t0.weekday()==5 else '日'}，台股不交易")
        return
    
    log("=" * 75)
    log("📊 法人初建倉每日監控 v3 (無遞補)")
    log(f"📆 {t0.strftime('%Y-%m-%d %H:%M')}")
    log("=" * 75)

    cache = load_cache()
    log(f"📦 投信: {len(cache)} stocks")

    # ── Check listed stock roster for changes ──
    try:
        from scripts.check_listed import main as check_listed
        check_listed()
    except Exception as e:
        log(f"⚠️ 上市櫃清單檢查失敗: {e}")

    # Load Chinese name map from FinMind (once)
    cn_names = load_chinese_names()
    log(f"📛 中文名稱: {len(cn_names)} stocks")

    # TWSE
    log("📡 抓 TWSE 最新投信資料...")
    twse, twse_date = None, None
    for d in range(0, 7):
        dt = (t0 - timedelta(days=d)).strftime('%Y%m%d')
        d2, u2 = fetch_twse_daily(dt)
        if d2: twse, twse_date = d2, u2; break
    if twse:
        cache = merge_twse(cache, twse, twse_date)
        log(f"   TWSE: {len(twse)} stocks")

    # TPEx (上櫃)
    log("📡 抓 TPEx 上櫃投信資料...")
    tpex, tpex_date = None, None
    for d in range(0, 7):
        dt = (t0 - timedelta(days=d)).strftime('%Y%m%d')
        tpex, tpex_date = fetch_tpex_daily(dt)
        if tpex: break
    if tpex:
        cache = merge_twse(cache, tpex, tpex_date or dt)
        log(f"   TPEx: {len(tpex)} stocks")

    save_cache(cache)

    # 10日排名 (無遞補: 有幾檔算幾檔)
    today_s = t0.strftime('%Y-%m-%d')
    sr = get_share_ranking(cache, today_s)
    log(f"🏆 {len(sr)} stocks with 10d 投信 buy (無遞補)")

    # TOP 100 候選 → 股價 → 金額排名 → Z篩選 → G/L評分
    candidates = sr[:100]
    log(f"🔄 股價: yfinance → FinMind, {len(candidates)} 檔候選...")
    enriched = []
    for sid, shares, last_dt in candidates:
        name, price = get_price(sid)
        if price and price > 0:
            enriched.append((sid, shares * price, shares, last_dt, name, price))
        else:
            log(f"   ⚠️ {sid}: 無法取得股價")

    enriched.sort(key=lambda x: -x[1])
    top100 = enriched[:100]
    log(f"🔝 金額排名 TOP {len(top100)}")

    # Step 1: 計算所有 Z（yfinance，快）
    log(f"📉 計算 Z（yfinance 5年回歸）...")
    scored_z = []
    for rank, (sid, amount, shares, last_dt, name, price) in enumerate(top100, 1):
        z = calc_z(sid)
        scored_z.append((rank, sid, amount, shares, last_dt, name, price, z))
        if rank % 20 == 0:
            log(f"   [{rank}/{len(top100)}]")

    # Step 2: Z <= 0 篩選
    z_pass = [(r, s, a, sh, ld, n, p, z) for r, s, a, sh, ld, n, p, z in scored_z if z is not None and z <= 0]
    log(f"🎯 Z <= 0: {len(z_pass)} / {len(top100)} 檔")

    # Step 3: G/L 評分（只對 Z 通過的，省 FinMind API）
    fm_api = get_fm_api()
    report = []
    for rank, sid, amount, shares, last_dt, name, price, z in z_pass:
        gs, ls, gd, ld = 0, 0, [], []
        if fm_api:
            try:
                time.sleep(5)
                gs, ls, gd, ld = score_stock(sid, fm_api)
            except:
                try:
                    time.sleep(10)
                    fm_api = get_fm_api()
                    if fm_api:
                        gs, ls, gd, ld = score_stock(sid, fm_api)
                except:
                    pass

        log(f"   #{rank} {sid} {name[:20]:<20s} ${price:<6.0f} Z={z} G={gs:.0f} L={ls:.0f}")
        name_zh = cn_names.get(sid, name)
        report.append({
            'rank': rank, 'code': sid, 'name': name,
            'name_zh': name_zh,
            'net_amount_10d': round(amount),
            'net_amount_10d_k': round(amount / 1000),
            'net_shares_10d': round(shares),
            'net_shares_10d_zhang': round(shares / 1000),
            'last_date': last_dt, 'cur_price': round(price, 2),
            'price_source': 'yfinance+fm_fallback', 'g_score': gs, 'l_score': ls,
            'g_detail': gd, 'l_detail': ld, 'regression_z': z,
            'statementdog_url': f"https://statementdog.com/analysis/{sid}",
        })

    # Step 4: G>=80, L>=80 篩選
    final = [r for r in report if r['g_score'] >= 80 and r['l_score'] >= 80]
    log(f"🎯 G>=80 & L>=80: {len(final)} / {len(report)} 檔")
    if not final:
        log("📭 無符合條件的股票")
        # Still output empty report
        final = []

    # 輸出
    rp = f"{OUTPUT_DIR}/reports/daily_trust10_{t0.strftime('%Y%m%d')}.json"
    os.makedirs(f"{OUTPUT_DIR}/reports", exist_ok=True)
    with open(rp, 'w') as f:
        json.dump({
            'date': t0.strftime('%Y-%m-%d'), 'time': t0.strftime('%H:%M'),
            'twse_date': twse_date, 'stocks_in_cache': len(cache),
            'stocks_with_buy': len(sr), 'price_source': 'yfinance+fm_fallback',
            'note': '篩選: TOP100金額 → Z<=0 → G>=80 & L>=80',
            'top10': final,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 75}")
    print(f"🏆 篩選結果 — G>=80, L>=80, Z<=0 ({len(final)} 檔)")
    print(f"{'=' * 75}")
    if final:
        for r in final:
            print(f"  #{r['rank']} {r['code']} {r.get('name_zh', r['name'])[:22]:<22s} "
                  f"${r['cur_price']:<6,.0f} {r['net_amount_10d_k']:>13,}千元 "
                  f"Z={r['regression_z']} G={r['g_score']:.0f} L={r['l_score']:.0f}")
    else:
        print(f"  📭 無符合條件的股票（Z<=0 有 {len(z_pass)} 檔，皆未通過 G>=80/L>=80）")

if __name__ == '__main__':
    main()
