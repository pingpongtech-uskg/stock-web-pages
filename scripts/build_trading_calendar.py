#!/usr/bin/env python3
"""Fetch an authoritative TWSE calendar; fail closed for missing/wrong year."""
import argparse
import base64
import hashlib
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.request import Request, urlopen
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.trading_calendar import (SOURCE_URL, build_calendar, compose_calendar_set, is_open,
                                       recent_sessions)
from pipeline.source_receipts import read_raw, capture_raw, write_bundle, safe_directory


def _read_file(directory: Path, name: str, limit: int) -> bytes:
    if not isinstance(name, str) or Path(name).name != name or name in {'.', '..'}:
        raise ValueError('invalid restored calendar path')
    path = directory / name
    if path.is_symlink():
        raise ValueError('restored calendar file must not be a symlink')
    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('restored calendar file exceeds size limit')
    return raw


def _verified_restored_calendar(directory: Path) -> tuple[dict, dict[int, tuple[dict, bytes]]]:
    """Rebuild one or two restored calendar years from their authenticated receipts."""
    directory = safe_directory(directory)
    index = json.loads(_read_file(directory, 'calendar-receipt-index.json', 256 * 1024))
    if not isinstance(index, dict) or not isinstance(index.get('groups'), list):
        raise ValueError('restored calendar receipt index is invalid')
    by_kind = {group.get('kind'): group for group in index['groups'] if isinstance(group, dict)}
    raw_group, normalized_group = by_kind.get('calendar_raw'), by_kind.get('calendar_normalized')
    if (len(index['groups']) != 2 or not isinstance(raw_group, dict) or not isinstance(normalized_group, dict) or
        raw_group.get('key') != 'calendar_raw' or normalized_group.get('key') != 'calendar_normalized' or
        raw_group.get('unit') != 'calendar' or normalized_group.get('unit') != 'calendar' or
        raw_group.get('sourceUrl') != SOURCE_URL or normalized_group.get('sourceUrl') != SOURCE_URL or
        raw_group.get('market') != 'TWSE' or normalized_group.get('market') != 'TWSE' or
        not isinstance(raw_group.get('dates'), list) or raw_group.get('dates') != normalized_group.get('dates') or len(raw_group['dates']) != 1 or
        raw_group.get('sourceSha256') != normalized_group.get('sourceSha256') or
        normalized_group.get('normalizedFromSha256') != raw_group.get('sourceSha256')):
        raise ValueError('restored calendar fragment is incomplete')
    raw_bundle = _read_file(directory, raw_group.get('bodyFile'), 4 * 1024 * 1024)
    if hashlib.sha256(raw_bundle).hexdigest() != raw_group.get('sourceSha256'):
        raise ValueError('restored calendar raw hash mismatch')
    bundle = json.loads(raw_bundle)
    normalized = json.loads(_read_file(directory, normalized_group.get('bodyFile'), 256 * 1024))
    receipts = bundle.get('receipts') if isinstance(bundle, dict) else None
    if (not isinstance(bundle, dict) or bundle.get('schemaVersion') != 'source-receipt-bundle-v1' or
        not isinstance(receipts, list) or len(receipts) not in {1, 2}):
        raise ValueError('restored calendar receipt bundle is invalid')
    parsed_by_year, receipt_by_year = {}, {}
    for receipt in receipts:
        if (not isinstance(receipt, dict) or receipt.get('sourceUrl') != SOURCE_URL or
            receipt.get('unit') != 'calendar' or type(receipt.get('requestYear')) is not int or
            receipt.get('requestYear') in parsed_by_year or not isinstance(receipt.get('retrievedAt'), str) or
            type(receipt.get('rawBytes')) is not int or not 0 < receipt['rawBytes'] <= 2 * 1024 * 1024 or
            not isinstance(receipt.get('rawSha256'), str) or len(receipt['rawSha256']) != 64 or
            not isinstance(receipt.get('rawBase64'), str)):
            raise ValueError('restored calendar receipt metadata is invalid')
        raw = base64.b64decode(receipt['rawBase64'], validate=True)
        if len(raw) != receipt['rawBytes'] or hashlib.sha256(raw).hexdigest() != receipt['rawSha256']:
            raise ValueError('restored calendar receipt hash mismatch')
        rows = json.loads(raw)
        year = receipt['requestYear']
        parsed = build_calendar(rows, year=year, fetched_at=receipt['retrievedAt'])
        reported_dates = sorted(date(int(row['Date'][:3]) + 1911, int(row['Date'][3:5]), int(row['Date'][5:])).isoformat()
                                for row in rows)
        if receipt.get('reportedDates') != reported_dates:
            raise ValueError('restored calendar receipt date mismatch')
        parsed_by_year[year] = parsed
        receipt_by_year[year] = (receipt, raw)
    parsed_calendar = (next(iter(parsed_by_year.values())) if len(parsed_by_year) == 1 else
                       compose_calendar_set(list(parsed_by_year.values())))
    if parsed_calendar != normalized or raw_group.get('unit') != 'calendar' or normalized_group.get('unit') != 'calendar':
        raise ValueError('restored calendar projection mismatch')
    if not raw_group['dates'] or not all(
            date.fromisoformat(value).isoformat() == value for value in raw_group['dates']):
        raise ValueError('restored calendar target date is invalid')
    return parsed_calendar, receipt_by_year


def _needs_prior_year(calendar: dict, target: date, *, sessions: int = 11) -> bool:
    count = 0
    for offset in range(60):
        day = target - timedelta(days=offset)
        if day.year != target.year:
            return count < sessions
        if is_open(calendar, day.isoformat()):
            count += 1
            if count == sessions:
                return False
    raise ValueError('current calendar has too few sessions')


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
    parser.add_argument('--prior-calendar-cache-dir', type=Path,
                        help='verified restored calendar fragment for the immediately prior year')
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
        prior_calendar = prior_receipts = None
        if args.prior_calendar_cache_dir is not None:
            prior_calendar, prior_receipts = _verified_restored_calendar(args.prior_calendar_cache_dir)
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
        needs_prior = _needs_prior_year(calendar, target)
        output_calendar = calendar
        receipts = [{**receipt, 'reportedDates': sorted(
            date(int(row['Date'][:3]) + 1911, int(row['Date'][3:5]), int(row['Date'][5:])).isoformat()
            for row in rows)}] if receipt is not None else []
        if needs_prior:
            prior_year = target.year - 1
            prior_members = ([] if prior_calendar is None else
                             [prior_calendar] if prior_calendar.get('year') == prior_year else
                             [item for item in prior_calendar.get('calendars', []) if item.get('year') == prior_year])
            if not prior_members or prior_receipts is None or prior_year not in prior_receipts:
                raise ValueError('verified prior-year calendar is required for the 11-session window')
            prior_year_calendar = prior_members[0]
            prior_receipt, prior_raw = prior_receipts[prior_year]
            output_calendar = compose_calendar_set([prior_year_calendar, calendar])
            recent_sessions(output_calendar, args.market_date, count=11)
            if cache_directory is not None:
                prior_copy = capture_raw(cache_directory, prefix=f'calendar-{prior_year}',
                    raw=prior_raw, source_url=prior_receipt['sourceUrl'], unit='calendar',
                    request_period={'requestYear': prior_receipt['requestYear']},
                    retrieved_at=prior_receipt['retrievedAt'])
                receipts.insert(0, {**prior_copy, 'reportedDates': prior_receipt.get('reportedDates', [])})
        if receipt is not None:
            write_bundle(cache_directory, prefix='calendar', receipts=receipts,
                         normalized=output_calendar, group={'kind': 'calendar', 'market': 'TWSE', 'codes': [],
                         'dates': [args.market_date], 'unit': 'calendar', 'sourceUrl': SOURCE_URL})
        _write_calendar(output, output_calendar)
    except (OSError, ValueError, KeyError, HTTPException) as exc:
        print(f'trading_calendar_invalid={exc}',file=sys.stderr)
        return 1
    print('trading_calendar_valid')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
