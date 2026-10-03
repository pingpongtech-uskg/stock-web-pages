#!/usr/bin/env python3
"""Fetch an authoritative TWSE calendar; fail closed for missing/wrong year."""
import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.request import Request, urlopen
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.trading_calendar import SOURCE_URL, build_calendar, is_open
from pipeline.source_receipts import read_raw, capture_raw, write_bundle, safe_directory


def _write_calendar(output, calendar):
    parent = safe_directory(output.parent)
    output = parent / output.name
    if output.is_symlink():
        raise ValueError('calendar output must not be a symlink')
    parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.calendar-', dir=parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(calendar, stream, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--market-date', required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'public/data/trading-calendar.json')
    parser.add_argument('--source-cache-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        target = date.fromisoformat(args.market_date)
        if target.isoformat() != args.market_date:
            raise ValueError('market date must be exact ISO date')
        output_parent = safe_directory(args.output.parent)
        output = output_parent / args.output.name
        if output.is_symlink():
            raise ValueError('calendar output must not be a symlink')
        cache_directory = safe_directory(args.source_cache_dir) if args.source_cache_dir is not None else None
        req = Request(SOURCE_URL, headers={'Accept':'application/json','User-Agent':'stock-calendar/1.0'})
        with urlopen(req, timeout=30) as response:
            raw = read_raw(response)
        retrieved_at = datetime.now(timezone.utc).isoformat()
        receipt = capture_raw(cache_directory, prefix=f'calendar-{target.year}', raw=raw,
                              source_url=SOURCE_URL, unit='calendar', request_period={'requestYear': target.year},
                              retrieved_at=retrieved_at) if args.source_cache_dir is not None else None
        rows = json.loads(raw)
        calendar = build_calendar(rows, year=target.year, fetched_at=retrieved_at)
        if not is_open(calendar, args.market_date):
            raise ValueError('requested date is a market closure')
        if receipt is not None:
            reported = sorted(date(int(row['Date'][:3]) + 1911, int(row['Date'][3:5]), int(row['Date'][5:])).isoformat() for row in rows)
            write_bundle(cache_directory, prefix='calendar', receipts=[{**receipt, 'reportedDates': reported}],
                         normalized=calendar, group={'kind': 'calendar', 'market': 'TWSE', 'codes': [],
                         'dates': [args.market_date], 'unit': 'calendar', 'sourceUrl': SOURCE_URL})
        _write_calendar(output, calendar)
    except (OSError, ValueError, KeyError, HTTPException) as exc:
        print(f'trading_calendar_invalid={exc}',file=sys.stderr)
        return 1
    print('trading_calendar_valid')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
