#!/usr/bin/env python3
"""⚡ 建置完整投信買賣超快取 (1954 stocks, async, one-time)"""
import os, sys, json, time, re, warnings
from datetime import datetime
warnings.filterwarnings('ignore')

BASE = os.path.expanduser("~/tw-stock-monitor")
DATA_DIR = f"{BASE}/data"
TRUST_CACHE_FILE = f"{BASE}/output/trust_all_cache.json"

log = lambda m: print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

# Load token
with open(f"{BASE}/scripts/download_otc_prices.py") as f:
    content = f.read()
for m in re.finditer(r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+', content):
    token = m.group(); break

from FinMind.data import DataLoader
api = DataLoader()
api.login_by_token(api_token=token)

# Get all stock IDs
all_ids = []
for i in range(1, 26):
    p = f"{DATA_DIR}/batch_{i:03d}.json"
    if os.path.exists(p):
        with open(p) as f:
            for sym in json.load(f):
                code = sym.split('.')[0]
                if code not in all_ids:
                    all_ids.append(code)
all_ids.sort()

log(f"📡 Building 投信 cache for {len(all_ids)} stocks...")
log(f"   Range: {all_ids[0]} ~ {all_ids[-1]}")

# Continue from existing cache
cache = {}
if os.path.exists(TRUST_CACHE_FILE):
    with open(TRUST_CACHE_FILE) as f:
        cache = json.load(f)
    log(f"   Existing cache: {len(cache)} stocks")

to_query = [sid for sid in all_ids if sid not in cache]
log(f"   To query: {len(to_query)} stocks")

if not to_query:
    log("✅ Cache already complete!")
    sys.exit(0)

# Rate limit: 3s between batches of 100
BATCH = 100
total = (len(to_query) + BATCH - 1) // BATCH

for b in range(total):
    batch = to_query[b * BATCH : (b + 1) * BATCH]
    log(f"   [{b+1}/{total}] Querying batch of {len(batch)}...")
    
    time.sleep(3)  # rate limit between batches
    
    try:
        df = api.taiwan_stock_institutional_investors(
            stock_id_list=batch,
            start_date='2014-01-01',
            end_date=datetime.now().strftime('%Y-%m-%d'),
            use_async=True
        )
    except Exception as e:
        log(f"   ⚠️ Failed: {e}, retrying in 30s...")
        time.sleep(30)
        try:
            api.login_by_token(api_token=token)
            df = api.taiwan_stock_institutional_investors(
                stock_id_list=batch, start_date='2014-01-01',
                end_date=datetime.now().strftime('%Y-%m-%d'), use_async=True
            )
        except Exception as e2:
            log(f"   ❌ Retry failed: {e2}, skipping batch")
            continue
    
    if df is not None and len(df) > 0:
        trust = df[df['name'] == 'Investment_Trust'].copy()
        if len(trust) > 0:
            trust['net'] = (trust['buy'] - trust['sell']).astype(float)
            for sid in trust['stock_id'].unique():
                sdf = trust[trust['stock_id'] == sid].sort_values('date')
                # Only store what we need
                cache[sid] = {
                    'dates': sdf['date'].tolist(),
                    'net': [float(x) for x in sdf['net']],
                }
    
    # Save progress every 5 batches
    if (b+1) % 5 == 0 or b == total - 1:
        with open(TRUST_CACHE_FILE + '.tmp', 'w') as f:
            json.dump(cache, f)
        os.replace(TRUST_CACHE_FILE + '.tmp', TRUST_CACHE_FILE)
        log(f"   💾 Saved: {len(cache)} stocks so far")

log(f"\n✅ Done! {len(cache)} stocks cached")
log(f"   Saved to {TRUST_CACHE_FILE}")

# Summary: how many have data?
with_data = sum(1 for v in cache.values() if len(v['net']) > 20)
log(f"   Stocks with 20+ days of 投信 data: {with_data}")
