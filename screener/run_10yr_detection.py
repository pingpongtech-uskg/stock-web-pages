#!/usr/bin/env python3
"""10-year volume anomaly signal detection - run this directly"""
import os, sys, time, warnings, math, json
import numpy as np
warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_loader import load_stocks
from indicators import compute_indicators
from pattern_type1 import detect_type1
from pattern_type2 import detect_type2
import pattern_type3 as pt3
pt3._fetch_ohlc_finmind = lambda sym: None

# Import blocking
import builtins
_real_import = builtins.__import__
def _no_finmind(name, *args, **kwargs):
    if 'FinMind' in name or 'finmind' in name:
        raise ImportError()
    return _real_import(name, *args, **kwargs)
builtins.__import__ = _no_finmind

OUT = 'output/backtest_10yr'
os.makedirs(OUT, exist_ok=True)

t0 = time.time()
print(f'Loading stocks...', flush=True)
stocks = load_stocks('data', '2016-06-01', '2026-05-22')
print(f'Loaded {len(stocks)} stocks in {time.time()-t0:.0f}s', flush=True)

def get_ret(sig, stock, d):
    t = stock.date_index(sig.signal_date)
    if t < 0: return None
    ct = stock.closes[t]
    if math.isnan(ct) or ct <= 0: return None
    idx = min(t + d, len(stock.closes) - 1)
    cn = stock.closes[idx]
    if math.isnan(cn): return None
    r = (cn / ct - 1.0) * 100.0
    return None if (math.isnan(r) or math.isinf(r)) else r

all_items = list(stocks.items())
all_signals = []

for i, (symbol, stock) in enumerate(all_items):
    if (i+1) % 400 == 0:
        elapsed = time.time() - t0
        print(f'  [{i+1}/{len(all_items)}] {elapsed:.0f}s | signals: {len(all_signals)}', flush=True)
    try:
        ind = compute_indicators(stock)
    except:
        continue
    try:
        for sig in detect_type1(stock, ind):
            all_signals.append((sig, stock))
        for sig in detect_type2(stock, ind):
            all_signals.append((sig, stock))
        for sig in pt3.detect_type3(stock, ind, ohlc_cache_dir=None):
            all_signals.append((sig, stock))
    except:
        continue

print(f'Detection done: {len(all_signals)} signals, {time.time()-t0:.0f}s', flush=True)

# Compute forward returns
for sig, stock in all_signals:
    sig._r = {d: get_ret(sig, stock, d) for d in [5, 10, 20, 60]}
    sig._year = sig.signal_date[:4]

# Build output
signals_out = []
for sig, stock in all_signals:
    signals_out.append({
        'symbol': sig.symbol,
        'name': sig.name,
        'date': sig.signal_date,
        'year': sig._year,
        'type': sig.pattern_type,
        'price': sig.entry_price,
        'vol_ratio': sig.volume_ratio,
        'ret5': sig._r[5],
        'ret10': sig._r[10],
        'ret20': sig._r[20],
        'ret60': sig._r[60],
    })

# Save chunks
chunk_size = 5000
for i in range(0, len(signals_out), chunk_size):
    chunk = signals_out[i:i+chunk_size]
    with open(f'{OUT}/signals_{i//chunk_size:03d}.json', 'w') as f:
        json.dump(chunk, f)
    print(f'  Saved chunk {i//chunk_size}: {len(chunk)} signals', flush=True)

# Summary
summary = {
    'total_signals': len(signals_out),
    'total_stocks': len(stocks),
    'types': {},
    'years': {},
}
for s in signals_out:
    summary['types'][s['type']] = summary['types'].get(s['type'], 0) + 1
    summary['years'][s['year']] = summary['years'].get(s['year'], 0) + 1
with open(f'{OUT}/summary.json', 'w') as f:
    json.dump(summary, f, indent=2)

print(f'\nSummary:', flush=True)
print(f'  Total signals: {len(signals_out)}', flush=True)
print(f'  Types: {summary["types"]}', flush=True)
print(f'  Years: {dict(sorted(summary["years"].items()))}', flush=True)
print(f'Total time: {time.time()-t0:.0f}s', flush=True)
