#!/usr/bin/env python3
"""
Check and update listed stock roster (TWSE + TPEx).
Compares current listed stocks against stored list, reports changes.
Runs before daily_trust_monitor.py each trading day.
"""
import json, os, urllib.request
from datetime import datetime

BASE = os.path.expanduser("~/tw-stock-monitor")
ROSTER_FILE = f"{BASE}/data/listed_roster.json"

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def fetch_twse_codes():
    """Fetch TWSE listed 4-digit stock codes from open API."""
    url = 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode('utf-8-sig'))
    codes = set()
    for row in data:
        code = str(row.get('公司代號', '')).strip()
        if code.isdigit() and len(code) == 4:
            codes.add(code)
    return codes

def fetch_tpex_codes():
    """Fetch TPEx listed 4-digit stock codes."""
    url = 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode('utf-8-sig'))
    codes = set()
    for row in data:
        code = str(row.get('SecuritiesCompanyCode', '')).strip()
        if code.isdigit() and len(code) == 4:
            codes.add(code)
    return codes

def main():
    log("📋 檢查上市櫃家數...")
    
    # Fetch current listed stocks
    twse = fetch_twse_codes()
    tpex = fetch_tpex_codes()
    current = {'twse': sorted(twse), 'tpex': sorted(tpex)}
    log(f"  上市: {len(twse)}  上櫃: {len(tpex)}  合計: {len(twse | tpex)}")
    
    # Load stored roster
    stored = {}
    if os.path.exists(ROSTER_FILE):
        with open(ROSTER_FILE) as f:
            stored = json.load(f)
        stored_twse = set(stored.get('twse', []))
        stored_tpex = set(stored.get('tpex', []))
        
        # Check changes
        twse_new = twse - stored_twse
        twse_del = stored_twse - twse
        tpex_new = tpex - stored_tpex
        tpex_del = stored_tpex - tpex
        
        changes = []
        if twse_new:
            changes.append(f"上市新增 {len(twse_new)}: {sorted(twse_new)[:10]}{'...' if len(twse_new)>10 else ''}")
        if twse_del:
            changes.append(f"上市下市 {len(twse_del)}: {sorted(twse_del)[:10]}{'...' if len(twse_del)>10 else ''}")
        if tpex_new:
            changes.append(f"上櫃新增 {len(tpex_new)}: {sorted(tpex_new)[:10]}{'...' if len(tpex_new)>10 else ''}")
        if tpex_del:
            changes.append(f"上櫃下市 {len(tpex_del)}: {sorted(tpex_del)[:10]}{'...' if len(tpex_del)>10 else ''}")
        
        if changes:
            log("  ⚠️ 家數異動：")
            for c in changes:
                log(f"    {c}")
        else:
            log(f"  ✅ 無異動（上市 {len(stored_twse)}→{len(twse)}，上櫃 {len(stored_tpex)}→{len(tpex)}）")
    
    # Always save current roster
    os.makedirs(os.path.dirname(ROSTER_FILE), exist_ok=True)
    with open(ROSTER_FILE + '.tmp', 'w') as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    os.replace(ROSTER_FILE + '.tmp', ROSTER_FILE)
    
    return current

if __name__ == '__main__':
    main()
