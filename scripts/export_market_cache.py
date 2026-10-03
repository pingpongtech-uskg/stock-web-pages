#!/usr/bin/env python3
"""Export a trusted receipt index to immutable market-cache-v1 artifacts.

No HTTP, credentials, quota ledger, publication data, or source acquisition.
Raw bodyFile paths are relative to the input index; normalized files are JSON.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.market_cache import MAX_TOTAL_RAW, MarketCacheError, build_market_cache, canonical

MAX_INPUT_BYTES = 4 * 1024 * 1024


def _read(path: Path, limit: int) -> bytes:
    with path.open('rb') as source:
        value = source.read(limit + 1)
    if len(value) > limit:
        raise MarketCacheError('cache_input_size')
    return value


def _pairs(values):
    if len(values) > 10000:
        raise MarketCacheError('cache_object_size')
    if len({key for key, _ in values}) != len(values):
        raise MarketCacheError('cache_duplicate_key')
    return dict(values)


def _json(raw: bytes):
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(MarketCacheError('cache_numbers')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise MarketCacheError('cache_json') from exc


def load_inputs(path: Path) -> dict:
    payload = _json(_read(path, MAX_INPUT_BYTES))
    if not isinstance(payload, dict) or not isinstance(payload.get('groups'), list):
        raise MarketCacheError('cache_input')
    groups = []
    total_raw = 0
    for group in payload['groups']:
        if not isinstance(group, dict):
            raise MarketCacheError('cache_group')
        if 'bodyFile' not in group:
            total_raw += len(canonical(group.get('body')))
            if total_raw > MAX_TOTAL_RAW:
                raise MarketCacheError('cache_input_size')
            groups.append(group)
            continue
        relative = group['bodyFile']
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts or 'body' in group:
            raise MarketCacheError('cache_body_path')
        receipt = (path.parent / relative).resolve()
        if not receipt.is_relative_to(path.parent.resolve()):
            raise MarketCacheError('cache_body_path')
        raw = _read(receipt, max(0, MAX_TOTAL_RAW - total_raw))
        total_raw += len(raw)
        body = raw if str(group.get('kind', '')).endswith('_raw') else _json(raw)
        groups.append({**{key: value for key, value in group.items() if key != 'bodyFile'}, 'body': body})
    return {**payload, 'groups': groups}


def write_artifact(result: dict, output: Path) -> None:
    if output.exists():
        raise MarketCacheError('cache_output_exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f'.{output.name}.', dir=output.parent))
    try:
        for name, content in result['files'].items():
            (temporary / name).write_bytes(content)
        (temporary / 'manifest.json').write_bytes(canonical(result['manifest']))
        (temporary / 'proof.json').write_bytes(canonical(result['proof']))
        if output.exists():
            raise MarketCacheError('cache_output_exists')
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_market_cache(load_inputs(args.input), _json(_read(args.expected, MAX_INPUT_BYTES)))
        write_artifact(result, args.output)
    except (MarketCacheError, OSError, RecursionError, OverflowError) as exc:
        category = str(exc) if isinstance(exc, MarketCacheError) else 'cache_io'
        print(f'market_cache_failed={category}', file=sys.stderr)
        return 1
    print('market_cache_exported=' + json.dumps({'manifestHash': result['manifest']['manifestHash'],
          'cacheComplete': True, 'metricsComplete': result['proof']['metricsComplete'],
          'parts': len(result['files'])}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
