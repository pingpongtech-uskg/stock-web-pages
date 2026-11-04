#!/usr/bin/env python3
"""Freeze and verify the candidate consumed by the PEG publication run."""
import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path

MAX_BYTES = 500_000_000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
PATHS = ('config/tracked_symbols.json', 'public/data', '.cache/market-source', '.cache/chip-state', '.cache/ownership_snapshot.json', '.artifacts/ownership/generation.txt')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_universe(root, market_date):
    data = root / 'public/data'
    latest = json.loads((data / 'latest.json').read_text())
    config = json.loads((root / 'config/tracked_symbols.json').read_text())
    official = json.loads((data / 'institutional_universe.json').read_text())
    symbols = config.get('symbols')
    metadata = config.get('metadata')
    universe = config.get('universe') or {}
    rows = latest.get('stocks')
    if (config != official or config.get('stale') is not False or
            not isinstance(symbols, list) or len(symbols) != 100 or
            any(not isinstance(code, str) or not re.fullmatch(r'[0-9]{4}', code) for code in symbols) or
            len(set(symbols)) != 100 or not isinstance(metadata, dict) or set(metadata) != set(symbols) or
            any(not isinstance(metadata[code], dict) for code in symbols) or
            not isinstance(universe, dict) or not universe.get('marketDates') or universe['marketDates'][0] != market_date or
            not isinstance(universe.get('rows'), list) or len(universe['rows']) != 100 or
            [row.get('code') for row in universe['rows'] if isinstance(row, dict)] != symbols or
            not isinstance(rows, list) or len(rows) != 100 or
            {row.get('code') for row in rows if isinstance(row, dict)} != set(symbols) or
            latest.get('marketDate') != market_date):
        raise ValueError('candidate universe or metadata mismatch')
    return latest


def create(root, artifact, request, market_date, run, attempt, source_commit):
    data = root / 'public/data'
    latest = validate_universe(root, market_date)
    rows = latest['stocks']
    stocks = []
    for row in rows:
        code = str(row['code'])
        if not re.fullmatch(r'[A-Za-z0-9]{1,12}', code):
            raise ValueError('invalid candidate code')
        detail = json.loads((data / 'releases' / latest['runId'] / 'stocks' / f'{code}.json').read_text())
        stocks.append({'code': code, 'name': detail.get('name') or row.get('name'),
                       'pegReview': detail.get('pegReview') or {'status': 'needs_review', 'reasonCodes': ['missing_evidence']},
                       'currentPeriod': (detail.get('pegReview') or {}).get('currentPeriod') or detail.get('currentPeriod')})
    artifact.mkdir(parents=True, exist_ok=True)
    archive = artifact / 'candidate.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for name in PATHS:
            path = root / name
            if path.exists():
                for file in sorted(path.rglob('*')):
                    if file.is_symlink():
                        raise ValueError('candidate contains symlink')
                tar.add(path, arcname=name, recursive=True)
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('candidate exceeds size limit')
    preview = {'requestId': request, 'marketDate': market_date, 'prepareRunId': str(run),
               'prepareRunAttempt': int(attempt), 'sourceGitCommit': source_commit,
               'candidateSha256': digest(archive), 'stocks': stocks}
    preview_bytes = json.dumps(preview, ensure_ascii=False, sort_keys=True).encode()
    if len(preview_bytes) > 256 * 1024:
        raise ValueError('candidate preview exceeds size limit')
    (artifact / 'preview.json').write_bytes(preview_bytes)
    return preview


def validate_prepare_run(preview, run, repository):
    expected = {
        'id': int(preview['prepareRunId']), 'run_attempt': preview['prepareRunAttempt'],
        'head_sha': preview['sourceGitCommit'], 'head_branch': 'main',
        'event': 'workflow_dispatch', 'status': 'completed', 'conclusion': 'success',
        'display_title': f"Daily PEG prepare | {preview['requestId']} | {preview['marketDate']}",
        'path': '.github/workflows/daily.yml',
    }
    if any(run.get(key) != value for key, value in expected.items()) or run.get('repository', {}).get('full_name') != repository:
        raise ValueError('prepare run provenance mismatch')


def restore(root, artifact, request, market_date, run, attempt, expected_digest):
    preview = json.loads((artifact / 'preview.json').read_text())
    identity = {'requestId': request, 'marketDate': market_date, 'prepareRunId': str(run), 'prepareRunAttempt': int(attempt)}
    if any(preview.get(k) != v for k, v in identity.items()):
        raise ValueError('candidate identity mismatch')
    archive = artifact / 'candidate.tar.gz'
    if not re.fullmatch(r'[a-f0-9]{64}', expected_digest) or archive.stat().st_size > MAX_ARCHIVE_BYTES or digest(archive) != expected_digest or preview.get('candidateSha256') != expected_digest:
        raise ValueError('candidate digest mismatch')
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        if sum(m.size for m in members) > MAX_BYTES or any(not (m.isfile() or m.isdir()) or not any(m.name == p or m.name.startswith(p + '/') for p in PATHS) or '..' in Path(m.name).parts for m in members):
            raise ValueError('candidate archive unsafe')
        if not any(m.name == 'config/tracked_symbols.json' and m.isfile() for m in members):
            raise ValueError('candidate universe config missing')
        tar.extractall(root, members=members, filter='data')
    validate_universe(root, market_date)
    return preview


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['create', 'restore'])
    p.add_argument('--root', type=Path, default=Path('.'))
    p.add_argument('--artifact', type=Path, required=True)
    p.add_argument('--request-id', required=True)
    p.add_argument('--market-date', required=True)
    p.add_argument('--prepare-run-id', required=True)
    p.add_argument('--prepare-run-attempt', required=True)
    p.add_argument('--source-git-commit', default='')
    p.add_argument('--candidate-sha256', default='')
    a = p.parse_args()
    args = (a.root, a.artifact, a.request_id, a.market_date, a.prepare_run_id, a.prepare_run_attempt)
    result = create(*args, a.source_git_commit) if a.action == 'create' else restore(*args, a.candidate_sha256)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
