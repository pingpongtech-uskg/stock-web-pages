#!/usr/bin/env python3
"""
Quick patch: fill missing listed stocks into trust_all_cache.json using FinMind.
Only fetches last 30 days for 440 missing stocks (fast, ~2 min).
"""
import json, os, sys, time, re
from datetime import datetime, timedelta

BASE = os.path.expanduser("~/tw-stock-monitor")
CACHE_FILE = f"{BASE}/output/trust_all_cache.json"

# Load FinMind token
src = f"{BASE}/scripts/download_otc_prices.py"
with open(src) as f:
    content = f.read()
tok = None
for m in re.finditer(r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+', content):
    tok = m.group(); break
if not tok:
    print("No FinMind token found!"); sys.exit(1)

# Load cache + listed stocks
with open(CACHE_FILE) as f:
    cache = json.load(f)
with open('/tmp/twse_codes.json') as f:
    twse = set(json.load(f))
with open('/tmp/tpex_codes.json') as f:
    tpex = set(json.load(f))

missing = sorted((twse | tpex) - set(cache.keys()))
print(f"Cache: {len(cache)}, Listed: {len(twse|tpex)}, Missing: {len(missing)}")

if not missing:
    print("Nothing missing!"); sys.exit(0)

# Last 30 trading days
today = datetime.now()
start = today - timedelta(days=45)  # ~30 trading days
start_date = start.strftime('%Y-%m-%d')
print(f"Fetching from {start_date}...")

from FinMind.data import DataLoader
api = DataLoader()
api.login_by_token(api_token=tok)

added_s = 0
added_d = 0
no_data = 0
errors = 0
t_start = time.time()

for i, code in enumerate(missing):
    try:
        df = api.taiwan_stock_institutional_investors(
            stock_id=code, start_date=start_date, timeout=30)
    except Exception as e:
        errors += 1
        if errors <= 5:
            print(f"  {code}: API error")
        continue

    if df is None or len(df) == 0:
        no_data += 1
        continue

    trust = df[df['name'] == 'Investment_Trust']
    if len(trust) == 0:
        no_data += 1
        continue

    got = False
    for _, row in trust.iterrows():
        d = str(row['date'])[:10]
        buy = int(row['buy']); sell = int(row['sell'])
        net = buy - sell
        if net == 0:
            continue
        got = True
        if code not in cache:
            cache[code] = {'dates': [], 'net': []}
            added_s += 1
        if d not in cache[code]['dates']:
            cache[code]['dates'].append(d)
            cache[code]['net'].append(net)
            added_d += 1

    if not got:
        no_data += 1

    if (i + 1) % 50 == 0:
        elapsed = time.time() - t_start
        pct = (i + 1) / len(missing) * 100
        print(f"  [{i+1}/{len(missing)}] {pct:.0f}% +{added_s}s +{added_d}d err={errors} no_data={no_data} {elapsed:.0f}s")

# Sort + save
for code in cache:
    zd = sorted(zip(cache[code]['dates'], cache[code]['net']))
    cache[code]['dates'] = [z[0] for z in zd]
    cache[code]['net'] = [z[1] for z in zd]

with open(CACHE_FILE + '.tmp', 'w') as f:
    json.dump(cache, f)
os.replace(CACHE_FILE + '.tmp', CACHE_FILE)

elapsed = time.time() - t_start
print(f"\nDone in {elapsed:.0f}s:")
print(f"  +{added_s} new stocks")
print(f"  +{added_d} data points")
print(f"  {errors} errors, {no_data} no-data/zero-net")
print(f"  Cache: {len(cache)} stocks total")
print(f"Saved to {CACHE_FILE}")
