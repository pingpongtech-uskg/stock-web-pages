"""補齊缺漏上櫃股價格資料（yfinance優先，FinMind備援）"""
import json, os, time, warnings, urllib.request
warnings.filterwarnings('ignore')
import yfinance as yf
from FinMind.data import DataLoader

TOKEN = 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiQS5TIiwiZW1haWwiOiJ4ZC45NDQwNTAyQGdtYWlsLmNvbSIsInRva2VuX3ZlcnNpb24iOjF9.ZomkgalNDRc2bfdz6_Ax8F_HNqC0JiFRUiGqVFRr1tk'
DATA_DIR = "/tmp/tw_stock_data"
OUTPUT_DIR = "/tmp/hermes-output/20260523"
log = lambda m: print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

# ===== 1. 取得完整上櫃清單 =====
log("📡 抓TPEx上櫃清單...")
otc=json.loads(urllib.request.urlopen(urllib.request.Request(
    "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d=2026/05/22&s=0,asc,0",
    headers={'User-Agent':'Mozilla/5.0'}),timeout=15).read())

all_otc=set()
for r in otc['tables'][0]['data']:
    if r[0].isdigit() and len(r[0])==4 and not r[0].startswith('0'):
        all_otc.add(r[0])

log(f"   上櫃總數: {len(all_otc)} 檔")

# ===== 2. 檢查已有哪些 =====
existing=set()
for i in range(1,26):
    p=f"{DATA_DIR}/batch_{i:03d}.json"
    if not os.path.exists(p): continue
    with open(p) as f:
        for sym in json.load(f):
            c=sym.split('.')[0]
            existing.add(c)

have_otc=existing & all_otc
missing_otc=all_otc - existing
log(f"   已有上櫃: {len(have_otc)} 檔")
log(f"   缺少上櫃: {len(missing_otc)} 檔")

# ===== 3. yfinance下載 =====
new_data={}
total=len(missing_otc)
for i,code in enumerate(sorted(missing_otc)):
    if (i+1)%50==0: log(f"   [{i+1}/{total}] 已下載 {len(new_data)} 檔")

    # yfinance
    got=False
    for suffix in ['.TWO','.TW']:
        try:
            raw=yf.download(f"{code}{suffix}", period="max", progress=False, auto_adjust=False)
            if raw is not None and len(raw)>200:
                c=raw['Close'].iloc[:,0].values if hasattr(raw['Close'],'iloc') else raw['Close'].values
                v=raw['Volume'].iloc[:,0].values if hasattr(raw['Volume'],'iloc') else raw['Volume'].values
                dates=raw.index.strftime('%Y-%m-%d').tolist()
                new_data[f"{code}.TWO"]={
                    'dates':dates,'close':[round(float(x),2) for x in c],
                    'volume':[int(x) for x in v],'start':dates[0],'end':dates[-1],'days':len(dates),'name':''
                }
                got=True; break
        except: pass
    if got: continue
    time.sleep(1.5)

log(f"\n✅ yfinance: {len(new_data)} 檔成功")

# ===== 4. FinMind備援（對yfinance沒抓到的） =====
yf_codes={s.split('.')[0] for s in new_data}
still_missing=missing_otc - yf_codes
if still_missing:
    log(f"📡 FinMind備援 {len(still_missing)} 檔...")
    fm_count=0
    for code in sorted(still_missing)[:200]:  # 最多200檔以免rate limit
        try:
            api=DataLoader(); api.login_by_token(api_token=TOKEN)
            df=api.taiwan_stock_price(stock_id=code,start_date='2010-01-01')
            if df is not None and len(df)>200:
                df=df.sort_values('date')
                dates=df['date'].tolist()
                close=[float(x) for x in df['close']]
                volume=[int(x) for x in df['volume']]
                new_data[f"{code}.TWO"]={
                    'dates':dates,'close':[round(x,2) for x in close],
                    'volume':volume,'start':dates[0],'end':dates[-1],'days':len(dates),'name':''
                }
                fm_count+=1
                if fm_count%20==0: log(f"   FinMind: {fm_count} 檔")
        except: pass
        time.sleep(2)
    log(f"   FinMind: {fm_count} 檔")

# ===== 5. 合併 =====
log("\n📦 合併到批次檔...")
all_stocks={}
for i in range(1,26):
    p=f"{DATA_DIR}/batch_{i:03d}.json"
    if not os.path.exists(p): continue
    with open(p) as f:
        all_stocks.update(json.load(f))

all_stocks.update(new_data)

# 重新存檔
tickers=sorted(all_stocks.keys())
chunks=[tickers[i:i+100] for i in range(0,len(tickers),100)]
for ci,chunk in enumerate(chunks):
    cd={t:all_stocks[t] for t in chunk}
    p=f"{DATA_DIR}/batch_{ci+1:03d}.json"
    with open(p,'w') as f:
        json.dump(cd,f,ensure_ascii=False)
    sz=os.path.getsize(p)/1024/1024
    log(f"   batch_{ci+1:03d}.json: {len(cd)} stocks, {sz:.1f}MB")

tw_count=sum(1 for s in all_stocks if s.endswith('.TW'))
two_count=sum(1 for s in all_stocks if s.endswith('.TWO'))
log(f"\n📊 最終: 上市{tw_count} + 上櫃{two_count} = {len(all_stocks)} 檔")
log(f"✅ 補齊完成!")
