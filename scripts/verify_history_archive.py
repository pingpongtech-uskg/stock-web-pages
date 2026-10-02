#!/usr/bin/env python3
"""Validate history metadata, immutable revisions, content hashes and retention."""
from __future__ import annotations
import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pipeline.history_archive import revision_for_record


def _revision_errors(archive: Path, record: dict) -> list[str]:
    errors = []
    refs = record.get('revisionRefs', [])
    if not isinstance(refs, list):
        return ['revision references shape']
    seen = set()
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get('revision'), str):
            errors.append('revision reference shape'); continue
        revision = ref['revision']
        if revision in seen:
            errors.append('duplicate revision reference')
        seen.add(revision)
        expected_name = f'{record["marketDate"]}.{revision}.json'
        if ref.get('path') != '/data/archive/v1/revisions/' + expected_name:
            errors.append('revision path:' + revision); continue
        path = archive / 'revisions' / expected_name
        if not path.exists():
            errors.append('revision missing:' + revision); continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref.get('sha256'):
            errors.append('revision hash:' + path.name)
        try:
            saved = json.loads(raw)
            if (saved.get('revision') != revision_for_record(saved) or saved.get('revision') != revision or
                saved.get('marketDate') != record['marketDate'] or saved.get('runId') != ref.get('runId')):
                errors.append('saved revision:' + path.name)
        except (ValueError, TypeError, AttributeError):
            errors.append('saved revision invalid:' + path.name)
    if refs and record.get('revision') not in seen:
        errors.append('active revision missing')
    return errors


def _month_errors(archive: Path, meta: dict, seen: set) -> list[str]:
    errors = []
    filename = Path(str(meta.get('path', ''))).name
    path = archive / 'months' / filename
    if not path.exists():
        return ['month missing:' + str(meta.get('path'))]
    payload = path.read_bytes(); digest = hashlib.sha256(payload).hexdigest()
    if digest != meta.get('sha256'):
        errors.append('hash mismatch:' + filename)
    if not re.fullmatch(r'\d{4}-\d{2}\.[0-9a-f]{12}\.json', filename) or filename.split('.')[1] != digest[:12]:
        errors.append('filename suffix:' + filename)
    if meta.get('path') != '/data/archive/v1/months/' + filename:
        errors.append('month path:' + filename)
    if meta.get('bytes') != len(payload):
        errors.append('month bytes:' + filename)
    try:
        month = json.loads(payload)
        if month.get('schemaVersion') != 'screening-history-month-v1' or month.get('month') != meta.get('month'):
            errors.append('month schema:' + filename)
        records = month['records']
        dates = [record['marketDate'] for record in records]
        if not dates or dates != sorted(dates) or len(dates) != len(set(dates)):
            errors.append('dates:' + filename)
        if meta.get('recordCount') != len(dates) or meta.get('marketDates') != dates:
            errors.append('month count:' + filename)
        if dates and (meta.get('marketDateStart') != min(dates) or meta.get('marketDateEnd') != max(dates)):
            errors.append('month bounds:' + filename)
        for record in records:
            day = date.fromisoformat(record['marketDate']).isoformat()
            if day[:7] != meta.get('month'):
                errors.append('month date:' + day)
            if day in seen:
                errors.append('duplicate date:' + day)
            seen.add(day)
            if record.get('revision') != revision_for_record(record):
                errors.append('revision:' + day)
            errors.extend(_revision_errors(archive, record))
    except (ValueError, KeyError, TypeError, AttributeError):
        errors.append('month invalid:' + filename)
    return errors


def verify_archive(archive: Path, retention_days: int = 366) -> list[str]:
    index_path = archive / 'index.json'
    if not index_path.exists():
        return ['index missing']
    try:
        index = json.loads(index_path.read_bytes())
        if not isinstance(index, dict) or not isinstance(index.get('months'), list):
            return ['index shape']
    except (OSError, ValueError) as exc:
        return [f'index invalid: {exc}']
    errors = []
    if index.get('schemaVersion') != 'screening-history-index-v1':
        errors.append('index schema')
    seen: set[str] = set()
    for meta in index['months']:
        if not isinstance(meta, dict):
            errors.append('month metadata shape'); continue
        errors.extend(_month_errors(archive, meta, seen))
    if seen:
        if index.get('latestMarketDate') != max(seen):
            errors.append('latest date')
        if index.get('earliestMarketDate') != min(seen):
            errors.append('earliest date')
        try:
            end = date.fromisoformat(str(index.get('generatedAt') or max(seen))[:10])
            start = end - timedelta(days=retention_days - 1)
            if any(not start <= date.fromisoformat(day) <= end for day in seen):
                errors.append('retention dates')
        except ValueError:
            errors.append('generated date')
    return errors


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, default=ROOT/'public/data/archive/v1')
    parser.add_argument('--retention-days', type=int, default=366)
    args = parser.parse_args(argv)
    errors = verify_archive(args.archive, args.retention_days)
    if errors:
        for error in errors:
            print('archive_invalid=' + error)
        return 1
    print('archive_valid')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
