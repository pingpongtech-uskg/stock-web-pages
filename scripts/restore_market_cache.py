#!/usr/bin/env python3
"""Fetch a pinned public data-only cache commit, then restore bounded inputs.

The workflow checks out trusted main code separately. This tool neither executes
restore tree content nor accepts a branch/ref URL or any Notion credential.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.market_cache import MarketCacheError, MAX_GZIP, MAX_TOTAL_GZIP, MAX_PARTS, _date
from pipeline.market_cache_restore import (restore_market_cache, _require, _flat, _descriptor, METADATA_LIMIT, REPOSITORY)
from pipeline.source_receipts import safe_directory
from scripts.build_market_cache_index import _store
from scripts.export_market_cache import _json

API = 'https://api.github.com/repos/' + REPOSITORY
SHA = re.compile('[a-f0-9]{40}')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MarketCacheError('cache_restore_redirect')


def github_get(path, limit):
    _require(isinstance(path, str) and re.fullmatch(r'/git/(commits|trees|blobs)/[a-f0-9]{40}', path) is not None, 'github_path')
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'stock-cache-restore/1.0'}
    token = os.environ.get('GITHUB_TOKEN')
    if token: headers = {**headers, 'Authorization': 'Bearer ' + token}
    with build_opener(NoRedirect()).open(Request(API + path, headers=headers), timeout=30) as response:
        raw = response.read(limit + 1)
    _require(isinstance(raw, bytes) and 0 < len(raw) <= limit, 'github_size')
    return _json(raw)


def _blob(item, get):
    limit = item['size'] * 2 + 8192
    value = get('/git/blobs/' + item['sha'], limit)
    _require(type(value) is dict and value.get('sha') == item['sha'] and value.get('size') == item['size']
             and value.get('encoding') == 'base64' and isinstance(value.get('content'), str)
             and len(value['content']) <= limit, 'blob')
    try: raw = base64.b64decode(value['content'].replace('\n', ''), validate=True)
    except (ValueError, TypeError) as exc: raise MarketCacheError('cache_restore_blob') from exc
    _require(len(raw) == item['size'] and hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == item['sha'], 'blob_hash')
    return raw


def fetch_restore_commit(commit, directory, *, trust, get=github_get):
    """Read exact root blobs only; reject unsafe trees before downloading data."""
    _require(isinstance(commit, str) and SHA.fullmatch(commit) is not None, 'commit')
    directory = safe_directory(directory)
    _require(not directory.exists(), 'staging')
    info = get('/git/commits/' + commit, METADATA_LIMIT)
    _require(type(info) is dict and info.get('sha') == commit and type(info.get('tree')) is dict
             and isinstance(info['tree'].get('sha'), str) and SHA.fullmatch(info['tree']['sha']) is not None, 'commit')
    tree_sha = info['tree']['sha']
    tree = get('/git/trees/' + tree_sha, METADATA_LIMIT)
    _require(type(tree) is dict and tree.get('sha') == tree_sha and tree.get('truncated') is False
             and type(tree.get('tree')) is list and 4 < len(tree['tree']) <= MAX_PARTS + 4, 'tree')
    items, total = {}, 0
    for item in tree['tree']:
        _require(type(item) is dict and _flat(item.get('path')) and item['path'] not in items
                 and item.get('mode') == '100644' and item.get('type') == 'blob'
                 and isinstance(item.get('sha'), str) and SHA.fullmatch(item['sha']) is not None
                 and type(item.get('size')) is int and item['size'] > 0, 'tree')
        name = item['path']
        _require(name in {'restore.json', 'manifest.json', 'proof.json', 'expected.json'} or name.endswith('.json.gz'), 'tree')
        _require(item['size'] <= (MAX_GZIP if name.endswith('.json.gz') else METADATA_LIMIT), 'tree_size')
        total += item['size']; _require(total <= MAX_TOTAL_GZIP + 4 * METADATA_LIMIT, 'tree_size')
        items[name] = item
    _require('restore.json' in items, 'tree')
    directory.mkdir(parents=True)
    _store(directory / 'restore.json', _blob(items['restore.json'], get))
    descriptor = _descriptor(directory, trust['descriptor_sha256'], trust['market_date'], trust['source'], require_files=False)
    _require(set(items) == {item['name'] for item in descriptor['files']} | {'restore.json'}, 'tree')
    for item in descriptor['files']:
        _require(items[item['name']]['size'] == item['bytes'], 'tree_size')
    for item in descriptor['files']:
        _store(directory / item['name'], _blob(items[item['name']], get))
    return directory


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument('--directory', type=Path)
    origin.add_argument('--restore-commit')
    for name in ['descriptor-sha256', 'cache-market-date', 'market-date', 'source-git-commit', 'actions-run-id', 'request-id']:
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--source-cache-dir', type=Path, default=ROOT / '.cache/market-source')
    parser.add_argument('--stock-cache-dir', type=Path, default=ROOT / '.cache/restored-stock-details')
    args = parser.parse_args(argv)
    trust = {'descriptor_sha256': args.descriptor_sha256, 'market_date': args.cache_market_date,
             'source': {'sourceGitCommit': args.source_git_commit, 'actionsRunId': args.actions_run_id, 'requestId': args.request_id}}
    try:
        _require(_date(args.market_date) and _date(args.cache_market_date) and args.cache_market_date <= args.market_date, 'target_date')
        with tempfile.TemporaryDirectory(prefix='market-cache-restore-') as temporary:
            directory = args.directory if args.directory is not None else fetch_restore_commit(args.restore_commit, Path(temporary) / 'data', trust=trust)
            proof = restore_market_cache(directory, target_market_date=args.market_date,
                                         source_cache_dir=args.source_cache_dir, stock_cache_dir=args.stock_cache_dir, **trust)
        print(json.dumps(proof, separators=(',', ':')))
        return 0
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        print('market_cache_restore_unavailable', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
