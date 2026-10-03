#!/usr/bin/env python3
"""Checkpoint-only three-case source diagnostic for an explicitly dispatched job."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import sys
import zlib
from datetime import date, datetime, timedelta
from http.client import HTTPException, IncompleteRead, RemoteDisconnected
from pathlib import Path
from time import sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.finmind_incremental import atomic_json  # noqa: E402
from pipeline.institutional_probe import (  # noqa: E402
    OFFICIAL_URL, exact_date, run_institutional_probe, select_probe_cases, _budget_metadata,
)
from pipeline.trading_calendar import SOURCE_URL, is_open  # noqa: E402

MAX_OFFICIAL_BYTES = 2 * 1024 * 1024
EVIDENCE_KEYS = {'schemaVersion', 'sourceUrl', 'documentationUrl', 'requestMethod',
    'httpStatus', 'contentType', 'retrievedAt', 'rawDate', 'marketDate', 'unit',
    'rowCount', 'sha256', 'bytes'}


def read_captured_official(evidence_dir: Path, market_date: str) -> tuple[bytes, object]:
    """Validate original official capture without substituting a live response."""
    with (evidence_dir / f'{market_date}.metadata.json').open('rb') as stream:
        metadata_raw = stream.read(65537)
    if len(metadata_raw) > 65536:
        raise ValueError('Evidence metadata exceeds size limit')
    metadata = json.loads(metadata_raw)
    day = date.fromisoformat(market_date)
    expected = {'schemaVersion': 'official-institutional-evidence-v1', 'sourceUrl': OFFICIAL_URL,
        'documentationUrl': 'https://www.tpex.org.tw/openapi/swagger.json', 'requestMethod': 'GET',
        'httpStatus': 200, 'contentType': 'application/json', 'rawDate': f'{day.year - 1911:03d}{day:%m%d}',
        'marketDate': market_date, 'unit': 'shares'}
    if (not isinstance(metadata, dict) or set(metadata) != EVIDENCE_KEYS or
        any(metadata.get(key) != value for key, value in expected.items()) or
        type(metadata.get('rowCount')) is not int or metadata['rowCount'] < 3 or
        type(metadata.get('bytes')) is not int or not 0 < metadata['bytes'] <= MAX_OFFICIAL_BYTES or
        not isinstance(metadata.get('retrievedAt'), str) or
        datetime.fromisoformat(metadata['retrievedAt']).tzinfo is None):
        raise ValueError('Evidence metadata mismatch')
    with (evidence_dir / f'{market_date}.json.gz').open('rb') as stream:
        compressed = stream.read(MAX_OFFICIAL_BYTES + 1)
    if len(compressed) > MAX_OFFICIAL_BYTES:
        raise ValueError('Compressed evidence exceeds size limit')
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
            raw = archive.read(MAX_OFFICIAL_BYTES + 1)
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError('Invalid evidence archive') from exc
    if (len(raw) > MAX_OFFICIAL_BYTES or len(raw) != metadata['bytes'] or
        hashlib.sha256(raw).hexdigest() != metadata['sha256']):
        raise ValueError('Evidence size or hash mismatch')
    rows = json.loads(raw)
    select_probe_cases(rows, market_date)
    if len(rows) != metadata['rowCount']:
        raise ValueError('Evidence row count mismatch')
    return raw, rows


def fetch_official_json() -> tuple[bytes, object]:
    """Read a bounded complete JSON document; retry transport failure once."""
    for attempt in range(2):
        try:
            request = Request(OFFICIAL_URL,
                headers={'User-Agent': 'taiwan-stock-screener/institutional-probe'}, method='GET')
            with urlopen(request, timeout=20) as response:
                if response.getcode() != 200:
                    raise ValueError('Official source requires HTTP 200')
                raw = response.read(MAX_OFFICIAL_BYTES + 1)
            if len(raw) > MAX_OFFICIAL_BYTES:
                raise ValueError('Official source exceeds size limit')
            return raw, json.loads(raw)
        except HTTPError:
            raise
        except (OSError, IncompleteRead, RemoteDisconnected):
            if attempt:
                raise
            sleep(0.5)
    raise RuntimeError('Official read attempts exhausted')  # Defensive; loop always returns or raises.


def expected_sessions(calendar: dict, market_date: str) -> list[str]:
    exact_date(market_date)
    if not isinstance(calendar, dict) or calendar.get('sourceUrl') != SOURCE_URL:
        raise ValueError('Authoritative calendar source missing')
    for key in ('closedDates', 'openExceptions'):
        values = calendar.get(key)
        if not isinstance(values, list) or not values or any(exact_date(day) != day for day in values):
            raise ValueError('Invalid authoritative calendar dates')
        if len(values) != len(set(values)):
            raise ValueError('Duplicate calendar dates')
    if set(calendar['closedDates']) & set(calendar['openExceptions']):
        raise ValueError('Conflicting calendar dates')
    if not is_open(calendar, market_date):
        raise ValueError('Market date is not an official open session')
    day = date.fromisoformat(market_date); sessions = []
    while len(sessions) < 11:
        if is_open(calendar, day.isoformat()):
            sessions.append(day.isoformat())
        day -= timedelta(days=1)
    return sorted(sessions)


def _date_arg(value: str) -> str:
    try:
        return exact_date(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Expected exact ISO date YYYY-MM-DD') from exc


def _max_calls(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('Maximum data requests must be 1..3') from exc
    if str(parsed) != value or not 1 <= parsed <= 3:
        raise argparse.ArgumentTypeError('Maximum data requests must be 1..3')
    return parsed


def _check_outputs(cache: Path, summary: Path, calendar: Path) -> None:
    for path in (cache.resolve(), summary.resolve()):
        if path.is_relative_to(ROOT) and not any(path.is_relative_to(ROOT / folder)
                for folder in ('.cache', '.artifacts')):
            raise ValueError('Probe outputs must not modify product data or configuration')
    if summary.resolve() in {calendar.resolve(), cache.resolve() / 'state.json', cache.resolve() / 'rows.json'}:
        raise ValueError('Summary must not overwrite calendar or shared checkpoint')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--market-date', type=_date_arg, required=True)
    parser.add_argument('--calendar', type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path, required=True)
    parser.add_argument('--budget-date', type=_date_arg, required=True)
    parser.add_argument('--summary', type=Path, required=True)
    parser.add_argument('--max-data-requests', type=_max_calls, default=3)
    parser.add_argument('--official-evidence-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        _check_outputs(args.cache_dir, args.summary, args.calendar)
        dates = expected_sessions(json.loads(args.calendar.read_text()), args.market_date)
    except (OSError, ValueError, TypeError):
        print('institutional_probe_invalid_inputs', file=sys.stderr)
        return 1
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        print('institutional_probe_requires_actions', file=sys.stderr)
        return 1
    token = os.environ.get('FINMIND_TOKEN', '')
    summary = {'probeVersion': 'institutional-probe-v1', 'outcome': 'unavailable',
        'publicationEligible': False, 'globalCompleteness': False, 'marketDate': args.market_date,
        'expectedDates': dates, 'cases': [], 'actualAttempts': 0, 'dataRequests': 0, 'cacheHits': 0,
        'accountLimit': None, 'observedRemaining': None, 'tokenPresent': bool(token.strip()),
        **_budget_metadata(args.cache_dir / 'state.json', args.budget_date)}
    if summary.get('errorCategory') == 'checkpoint_unavailable':
        atomic_json(args.summary, summary)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    try:
        if args.official_evidence_dir is not None:
            print('official_evidence_mode=captured')
            raw, rows = read_captured_official(args.official_evidence_dir, args.market_date)
        else:
            raw, rows = fetch_official_json()
    except (OSError, ValueError, HTTPException) as exc:
        summary = {**summary, 'errorCategory': 'official_source_invalid' if args.official_evidence_dir is not None
                   and isinstance(exc, ValueError)
                   else 'official_source_unavailable'}
    else:
        try:
            summary = run_institutional_probe(rows, market_date=args.market_date, expected_dates=dates,
                cache_dir=args.cache_dir, budget_date=args.budget_date, token=token,
                max_data_requests=args.max_data_requests)
            summary = {**summary, 'officialSourceUrl': OFFICIAL_URL, 'officialRowCount': len(rows),
                       'officialSha256': hashlib.sha256(raw).hexdigest()}
        except ValueError:
            summary = {**summary, 'errorCategory': 'official_source_invalid'}
        except (OSError, RuntimeError):
            summary = {**summary, 'errorCategory': 'checkpoint_unavailable'}
    atomic_json(args.summary, summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
