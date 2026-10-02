#!/usr/bin/env python3
"""Fetch an authoritative TWSE calendar; fail closed for missing/wrong year."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.trading_calendar import SOURCE_URL, build_calendar, is_open


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--market-date', required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'public/data/trading-calendar.json')
    args = parser.parse_args(argv)
    try:
        req = Request(SOURCE_URL, headers={'Accept':'application/json','User-Agent':'stock-calendar/1.0'})
        with urlopen(req, timeout=30) as response:
            rows = json.load(response)
        calendar = build_calendar(rows, year=int(args.market_date[:4]), fetched_at=datetime.now(timezone.utc).isoformat())
        if not is_open(calendar, args.market_date):
            raise ValueError('requested date is a market closure')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_suffix('.json.tmp')
        temp.write_text(json.dumps(calendar,ensure_ascii=False,sort_keys=True,separators=(',',':')),encoding='utf-8')
        os.replace(temp,args.output)
    except (OSError, ValueError, KeyError) as exc:
        print(f'trading_calendar_invalid={exc}',file=sys.stderr)
        return 1
    print('trading_calendar_valid')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
