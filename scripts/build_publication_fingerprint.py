#!/usr/bin/env python3
"""Publish a compact identity whose hash covers exact latest.json bytes."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def reject_nonfinite(value: str):
    raise ValueError('nonfinite snapshot value')


def build_fingerprint(payload: bytes) -> dict:
    if not isinstance(payload, bytes):
        raise ValueError('snapshot bytes required')
    release = json.loads(payload.decode('utf-8'), parse_constant=reject_nonfinite)
    if not isinstance(release, dict):
        raise ValueError('snapshot object required')
    market_date, run_id, generated_at = (release.get(key) for key in ('marketDate', 'runId', 'generatedAt'))
    if not isinstance(market_date, str) or date.fromisoformat(market_date).isoformat() != market_date:
        raise ValueError('invalid snapshot marketDate')
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', run_id):
        raise ValueError('invalid snapshot runId')
    if not isinstance(generated_at, str) or datetime.fromisoformat(generated_at).utcoffset() is None:
        raise ValueError('invalid snapshot generatedAt')
    return {'schemaVersion': 'publication-fingerprint-v1', 'marketDate': market_date,
            'runId': run_id, 'generatedAt': generated_at, 'contentHash': hashlib.sha256(payload).hexdigest()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'public/data')
    parser.add_argument('--market-date', required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    try:
        value = build_fingerprint((args.data_dir / 'latest.json').read_bytes())
        if value['marketDate'] != args.market_date:
            raise ValueError('requested market date mismatch')
        target = args.data_dir / 'publication.json'
        body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        if args.check:
            if target.read_bytes() != body:
                raise ValueError('publication fingerprint mismatch')
        else:
            temporary = target.with_suffix('.json.tmp')
            temporary.write_bytes(body)
            os.replace(temporary, target)
    except (OSError, ValueError) as exc:
        print(f'publication_fingerprint_invalid={exc}', file=sys.stderr)
        return 1
    print(f'publication_fingerprint_valid={value["contentHash"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
