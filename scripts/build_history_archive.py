#!/usr/bin/env python3
"""Append a validated export to history without losing indexed legacy dates."""
from __future__ import annotations
import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.verify_history_archive import verify_archive
from pipeline.history_archive import (merge_month, project_export_to_history, project_release_to_history,
    prune_to_retention, revision_for_record, write_archive_atomic)

LEGACY_REASON = 'Recorded historical output; request and point-in-time lineage unavailable'


def _legacy(record: dict) -> dict:
    tagged = {**record, 'legacy': True, 'legacyReason': LEGACY_REASON}
    return {**tagged, 'revision': revision_for_record(tagged)}


def _existing_months(archive: Path, retention_days: int) -> dict:
    months = defaultdict(list)
    if not archive.exists():
        return months
    if not (archive/'index.json').exists():
        if any(archive.iterdir()):
            raise ValueError('existing history index missing')
        return months
    errors = verify_archive(archive, retention_days)
    if errors:
        raise ValueError('existing archive invalid: ' + ','.join(errors))
    index = json.loads((archive/'index.json').read_bytes())
    for meta in index['months']:
        path = archive/'months'/Path(meta['path']).name
        # Verification must finish before a missing/corrupt object can alter the pointer.
        for row in json.loads(path.read_bytes())['records']:
            month = meta['month']
            months[month] = merge_month(months[month], row)
            if 'legacy' not in row:
                months[month] = merge_month(months[month], _legacy(row))
    return months


def _new_record(data_dir: Path, latest: dict, require_export: bool) -> dict:
    path = data_dir/'screening-export.json'
    if path.exists():
        export = json.loads(path.read_bytes())
        if export.get('runId') != latest.get('runId') or export.get('marketDate') != latest.get('marketDate'):
            raise ValueError('export latest release mismatch')
        return project_export_to_history(export)
    if require_export:
        raise ValueError('screening export required')
    return _legacy(project_release_to_history(latest))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=ROOT/'public/data')
    parser.add_argument('--as-of')
    parser.add_argument('--require-export', action='store_true')
    parser.add_argument('--retention-days', type=int, default=366)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    try:
        latest = json.loads((args.data_dir/'latest.json').read_bytes())
        archive = args.data_dir/'archive/v1'
        months = _existing_months(archive, args.retention_days)
        record = _new_record(args.data_dir, latest, args.require_export)
        month = record['marketDate'][:7]
        months[month] = merge_month(months[month], record)
        end = date.fromisoformat(args.as_of) if args.as_of else date.today()
        months = prune_to_retention(months, end, args.retention_days)
        if not args.check_only:
            write_archive_atomic(args.data_dir/'.history-staging', archive, months, latest.get('generatedAt'))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('archive_blocked=' + str(exc), file=sys.stderr)
        return 1
    print('archive_check_ok' if args.check_only else 'archive_built')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
