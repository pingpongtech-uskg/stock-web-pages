#!/usr/bin/env python3
"""Validate archive pointer, content hashes, schema shape, and retention."""
from __future__ import annotations
import hashlib, json, re, sys
from datetime import date, timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from pipeline.history_archive import canonical_json_bytes

def verify_archive(archive: Path, retention_days: int=366) -> list[str]:
    errors=[]; index_path=archive/'index.json'
    if not index_path.exists(): return ['index missing']
    try: index=json.loads(index_path.read_bytes())
    except Exception as exc: return [f'index invalid: {exc}']
    if index.get('schemaVersion')!='screening-history-index-v1': errors.append('index schema')
    months=index.get('months',[]); seen=set()
    for meta in months:
        path=archive / 'months' / Path(str(meta.get('path',''))).name
        if not path.exists(): errors.append('month missing:'+str(meta.get('path'))); continue
        payload=path.read_bytes(); digest=hashlib.sha256(payload).hexdigest()
        if digest != meta.get('sha256'): errors.append('hash mismatch:'+path.name)
        if not re.fullmatch(r'\d{4}-\d{2}\.[0-9a-f]{12}\.json',path.name) or not path.name.split('.')[1]==digest[:12]: errors.append('filename suffix:'+path.name)
        try: month=json.loads(payload)
        except Exception: errors.append('month invalid:'+path.name); continue
        records=month.get('records',[]); dates=[r.get('marketDate') for r in records]
        if dates != sorted(dates) or len(dates)!=len(set(dates)): errors.append('dates:'+path.name)
        for r in records:
            if r.get('marketDate') in seen: errors.append('duplicate date:'+str(r.get('marketDate')))
            seen.add(r.get('marketDate'))
            if r.get('revision') != hashlib.sha256(canonical_json_bytes({k:v for k,v in r.items() if k!='revision'})).hexdigest()[:12]: errors.append('revision:'+str(r.get('marketDate')))
    latest=index.get('latestMarketDate')
    if latest and seen and latest != max(seen): errors.append('latest date')
    return errors

def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(); p.add_argument('--archive',type=Path,default=ROOT/'public/data/archive/v1'); p.add_argument('--retention-days',type=int,default=366); a=p.parse_args(argv)
    errors=verify_archive(a.archive,a.retention_days)
    if errors:
        for e in errors: print('archive_invalid='+e)
        return 1
    print('archive_valid'); return 0
if __name__=='__main__': raise SystemExit(main())
