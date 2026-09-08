#!/usr/bin/env python3
"""Validate a static release without contacting any financial API."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    data = root / 'public' / 'data'
    latest_path = data / 'latest.json'
    if not latest_path.exists():
        print('snapshot_invalid=latest.json missing')
        return 1
    latest = json.loads(latest_path.read_text(encoding='utf-8'))
    required = {'schemaVersion', 'strategyVersion', 'formulaVersion', 'runId', 'marketDate', 'generatedAt', 'sourceRefs', 'stocks', 'rankings', 'coverage'}
    missing = sorted(required - set(latest))
    if missing:
        print('snapshot_invalid=missing:' + ','.join(missing))
        return 1
    run_id = latest['runId']
    release_dir = data / 'releases' / run_id
    if not (release_dir / 'manifest.json').exists():
        print('snapshot_invalid=manifest_missing')
        return 1
    manifest = json.loads((release_dir / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('runId') != run_id:
        print('snapshot_invalid=manifest_run_mismatch')
        return 1
    codes = [str(stock.get('code', '')) for stock in latest['stocks']]
    if any(not re.fullmatch(r'[0-9A-Z-]+', code) for code in codes):
        print('snapshot_invalid=bad_code')
        return 1
    detail_count = 0
    for code in codes:
        detail_path = release_dir / 'stocks' / f'{code}.json'
        if not detail_path.exists():
            print('snapshot_invalid=detail_missing:' + code)
            return 1
        detail = json.loads(detail_path.read_text(encoding='utf-8'))
        if detail.get('code') != code or detail.get('runId') not in (None, run_id):
            print('snapshot_invalid=detail_mismatch:' + code)
            return 1
        detail_count += 1
    print(json.dumps({'valid': True, 'run_id': run_id, 'stocks': len(codes), 'details': detail_count, 'market_date': latest['marketDate']}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
