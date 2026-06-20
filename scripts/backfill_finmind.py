#!/usr/bin/env python3
"""
Backfill 投信 data via FinMind (round-robin 4 keys).
Targets: all listed stocks missing from cache + TPEx stocks with < 5 data points.
Fetches last 15 trading days for each.
Merges into trust_all_cache.json.
"""
import json, os, sys, time
from datetime import datetime, timedelta

BASE = os.path.expanduser("~/tw-stock-monitor")
CACHE_FILE = f"{BASE}/output/trust_all_cache.json"

# Load FinMind keys
with open("/tmp/finmind_keys.json") as f:
    FM_KEYS = list(json.load(f).values())

# Load cache
with open(CACHE_FILE) as f:
    cache = json.load(f)
print(f"Cache before: {len(cache)} stocks")

# Load listed stocks
with open('/tmp/twse_codes.json') as f:
    twse = set(json.load(f))
with open('/tmp/tpex_codes.json') as f:
    tpex = set(json.load(f))
all_listed = twse | tpex

# Targets: missing + TPEx with short history
missing = all_listed - set(cache.keys())
short = [c for c in cache if len(cache[c].get('dates',[])) < 5 and c in tpex]
targets = sorted(set(missing) | set(short))
print(f"Targets: {len(targets)} (missing={len(missing)} + short-TPEx={len(short)})")

if not targets:
    print("Nothing to backfill!")
    sys.exit(0)

# Trading days
today = datetime.now()
trading_days = []
d = today
while len(trading_days) < 15:
    if d.weekday() < 5:
        trading_days.append(d.strftime('%Y-%m-%d'))
    d -= timedelta(days=1)
start_date = trading_days[-1]
print(f"Fetching from {start_date} to {trading_days[0]} ({len(trading_days)} trading days)")

# Round-robin
ki = [0]
def next_api():
    from FinMind.data import DataLoader
    k = FM_KEYS[ki[0] % len(FM_KEYS)]
    ki[0] += 1
    api = DataLoader()
    api.login_by_token(api_token=k)
    return api

api = next_api()
added_s = 0  # new stocks added
added_d = 0  # new data points
err = 0
nodata = 0
zero = 0

t_start = time.time()

for i, code in enumerate(targets):
    # Fetch
    df = None
    for attempt in range(3):
        try:
            df = api.taiwan_stock_institutional_investors(
                stock_id=code, start_date=start_date, timeout=30)
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
                api = next_api()
            else:
                err += 1
                df = None

    if df is None or len(df) == 0:
        nodata += 1
        if (i + 1) % 200 == 0:
            api = next_api()
        continue

    trust = df[df['name'] == 'Investment_Trust']
    if len(trust) == 0:
        nodata += 1
        continue

    # Extract net values
    got_data = False
    for _, row in trust.iterrows():
        d = str(row['date'])[:10]
        buy = int(row['buy'])
        sell = int(row['sell'])
        net = buy - sell
        if net == 0:
            continue

        got_data = True
        if code not in cache:
            cache[code] = {'dates': [], 'net': []}
            added_s += 1

        if d not in cache[code]['dates']:
            cache[code]['dates'].append(d)
            cache[code]['net'].append(net)
            added_d += 1

    if not got_data:
        zero += 1

    # Progress
    if (i + 1) % 100 == 0:
        elapsed = time.time() - t_start
        pct = (i + 1) / len(targets) * 100
        rate = (i + 1) / elapsed
        eta = (len(targets) - i - 1) / rate
        print(f"  [{i+1}/{len(targets)}] {pct:.0f}% | +{added_s}s +{added_d}d | "
              f"err={err} nodata={nodata} zero={zero} | {rate:.1f}/s ETA {eta:.0f}s")
        # Rotate key every 100 to spread load
        try:
            api = next_api()
        except:
            pass

elapsed = time.time() - t_start
print(f"\nDone in {elapsed:.0f}s: +{added_s} stocks, +{added_d} data points, "
      f"{err} errors, {nodata} no-data, {zero} zero-投信")

# Sort and deduplicate
for code in cache:
    zd = sorted(zip(cache[code]['dates'], cache[code]['net']))
    cache[code]['dates'] = [z[0] for z in zd]
    cache[code]['net'] = [z[1] for z in zd]

with open(CACHE_FILE + '.tmp', 'w') as f:
    json.dump(cache, f)
os.replace(CACHE_FILE + '.tmp', CACHE_FILE)
print(f"Cache after: {len(cache)} stocks")
print(f"Saved to {CACHE_FILE}")
