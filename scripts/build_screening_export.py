#!/usr/bin/env python3
"""Build one compact, validated export; never query data providers."""
import argparse
import json
import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.screening_export import build_export, export_bytes, validate_export


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'public/data')
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--market-date', required=True)
    parser.add_argument('--source-git-commit', required=True)
    parser.add_argument('--actions-run-id', required=True)
    args = parser.parse_args(argv)
    try:
        release = json.loads((args.data_dir / 'latest.json').read_bytes())
        if release.get('marketDate') != args.market_date:
            raise ValueError('requested market date mismatch')
        codes = {row['code'] for rows in release.get('rankings', {}).values() for row in rows}
        details = {}
        for code in codes:
            path = args.data_dir / 'releases' / release['runId'] / 'stocks' / f'{code}.json'
            if not path.exists():
                raise ValueError('selected stock detail missing: ' + code)
            details[code] = json.loads(path.read_bytes())
        value = build_export(release, request_id=args.request_id, source_git_commit=args.source_git_commit,
                             actions_run_id=args.actions_run_id, details=details)
        errors = validate_export(value)
        if errors:
            raise ValueError(','.join(errors))
        target = args.data_dir / 'screening-export.json'
        temp = target.with_suffix('.json.tmp')
        temp.write_bytes(export_bytes(value))
        os.replace(temp, target)
    except (ValueError, OSError, KeyError) as exc:
        print(f'screening_export_invalid={exc}', file=sys.stderr)
        return 1
    print(f'screening_export_valid={value["payloadHash"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
