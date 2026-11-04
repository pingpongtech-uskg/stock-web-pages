#!/usr/bin/env python3
"""Write a PEG audit proof bound to the exact final screening export."""
import argparse
import json
import re
from pathlib import Path


def build_review(data_dir: Path, market_date: str, request_id: str, source_git_commit: str,
                 actions_run_id: str, *, manifest=None, prepare_run='', prepare_attempt='', candidate_sha256=''):
    latest = json.loads((data_dir / 'latest.json').read_text())
    export = json.loads((data_dir / 'screening-export.json').read_text())
    expected = {'marketDate': market_date, 'runId': latest.get('runId'), 'requestId': request_id,
                'sourceGitCommit': source_git_commit, 'actionsRunId': actions_run_id}
    if latest.get('marketDate') != market_date or any(export.get(k) != v for k, v in expected.items()):
        raise ValueError('PEG review export lineage mismatch')
    run_id = latest.get('runId')
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', run_id) or run_id in {'.', '..'}:
        raise ValueError('invalid PEG review release')
    rows = latest.get('stocks')
    if not isinstance(rows, list) or len(rows) != 100:
        raise ValueError('invalid PEG review stock count')
    codes = [row.get('code') if isinstance(row, dict) else None for row in rows]
    if any(not isinstance(code, str) or not re.fullmatch(r'[0-9]{4,6}[A-Z]?', code) for code in codes) or len(set(codes)) != 100:
        raise ValueError('invalid PEG review stocks')
    lineage = {}
    if manifest is not None:
        if not re.fullmatch(r'[1-9][0-9]{0,23}', prepare_run) or not re.fullmatch(r'[1-9][0-9]{0,5}', prepare_attempt) or not re.fullmatch(r'[a-f0-9]{64}', candidate_sha256):
            raise ValueError('invalid candidate lineage')
        lineage = {'prepareRunId': prepare_run, 'prepareRunAttempt': int(prepare_attempt), 'candidateSha256': candidate_sha256}
        if any(manifest.get(k) != v for k, v in {**lineage, 'marketDate': market_date, 'requestId': request_id}.items()):
            raise ValueError('candidate lineage mismatch')
    reviews, counts = [], {}
    for code in sorted(codes):
        detail = json.loads((data_dir / 'releases' / run_id / 'stocks' / f'{code}.json').read_text())
        if detail.get('code') != code:
            raise ValueError('PEG review detail identity mismatch')
        peg = detail.get('pegReview') or {'status': 'needs_review', 'reasonCodes': ['missing_evidence']}
        if not isinstance(peg, dict) or peg.get('status') not in {'available', 'needs_review', 'not_applicable'}:
            raise ValueError('invalid PEG review detail')
        status = peg['status']
        counts[status] = counts.get(status, 0) + 1
        reviews.append({'code': code, 'name': detail.get('name'), 'pegReview': peg})
    proof = {**expected, **lineage, 'counts': counts, 'stocks': reviews}
    (data_dir / 'peg-review.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
    return proof


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=Path('public/data'))
    for arg in ('market-date', 'request-id', 'source-git-commit', 'actions-run-id'):
        parser.add_argument('--' + arg, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--prepare-run-id', default='')
    parser.add_argument('--prepare-run-attempt', default='')
    parser.add_argument('--candidate-sha256', default='')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text()) if args.manifest else None
    result = build_review(args.data_dir, args.market_date, args.request_id, args.source_git_commit, args.actions_run_id,
                          manifest=manifest, prepare_run=args.prepare_run_id, prepare_attempt=args.prepare_run_attempt,
                          candidate_sha256=args.candidate_sha256)
    print(json.dumps({'runId': result['runId'], 'counts': result['counts']}))


if __name__ == '__main__':
    main()
