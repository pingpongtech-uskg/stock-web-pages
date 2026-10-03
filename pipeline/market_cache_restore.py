"""Bounded semantic restoration of independently authenticated public cache data.

No HTTP, credentials, publication writes, or FinMind quota state. The caller
supplies descriptor identity from its authenticated operation checkpoint.
"""
from __future__ import annotations

import base64
import os
import re
import tempfile
import zlib
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from pipeline.market_cache import (MarketCacheError, canonical, sha, MAX_GZIP, MAX_RAW,
    MAX_TOTAL_GZIP, MAX_TOTAL_RAW, MAX_PARTS, _date, _hash, _header, _expectations,
    _group, _rows, _calendar, _utc)
from pipeline.source_receipts import safe_directory
from pipeline.trading_calendar import SOURCE_URL, build_calendar, is_open
from pipeline.market_indicators import TWSE_STOCK_DAY, SYMBOL, _date as volume_date, _volume
from pipeline.official_institutional import TWSE_ENDPOINT, TPEX_ENDPOINT, _cached_raw
from scripts.build_market_cache_index import _verify_institutional_groups, stock_metrics
from scripts.export_market_cache import _json

METADATA_LIMIT = 4 * 1024 * 1024
REPOSITORY = 'pingpongtech-uskg/stock-web-pages'


def _require(condition, category):
    if not condition:
        raise MarketCacheError('cache_restore_' + category)


def _flat(name):
    return isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,240}', name) is not None and '..' not in name


def _install_missing(path, raw):
    """Atomically publish without replacing a concurrently collected file."""
    parent = safe_directory(path.parent)
    destination = parent / path.name
    _require(not destination.is_symlink(), 'path')
    parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.restore-', dir=parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError:
            _require(not destination.is_symlink() and destination.is_file()
                     and destination.stat().st_size == len(raw), 'conflict')
            with destination.open('rb') as stream:
                _require(stream.read(len(raw) + 1) == raw, 'conflict')
    finally:
        os.unlink(temporary)


def _read(directory, name, limit):
    _require(_flat(name), 'path')
    path = directory / name
    _require(not path.is_symlink() and path.is_file(), 'path')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    _require(0 < len(raw) <= limit, 'size')
    return raw


def _descriptor(directory, trusted_hash, market_date, source, *, require_files=True):
    _require(_hash(trusted_hash) and _date(market_date), 'context')
    raw = _read(directory, 'restore.json', METADATA_LIMIT)
    _require(sha(raw) == trusted_hash, 'descriptor_hash')
    value = _json(raw)
    _require(type(value) is dict and set(value) == {'schemaVersion', 'repository', 'marketDate', 'source', 'manifestHash', 'files'}, 'descriptor')
    _require(value['schemaVersion'] == 'market-cache-restore-v1' and value['repository'] == REPOSITORY
             and value['marketDate'] == market_date and value['source'] == source and _hash(value['manifestHash']), 'context')
    files = value['files']
    _require(type(files) is list and 3 < len(files) <= MAX_PARTS + 3, 'files')
    names, total = [], 0
    for item in files:
        _require(type(item) is dict and set(item) == {'name', 'sha256', 'bytes'} and _flat(item['name']) and _hash(item['sha256'])
                 and type(item['bytes']) is int and item['bytes'] > 0, 'files')
        limit = MAX_GZIP if item['name'].endswith('.json.gz') else METADATA_LIMIT
        _require(item['bytes'] <= limit, 'size')
        total += item['bytes']
        _require(total <= MAX_TOTAL_GZIP + 3 * METADATA_LIMIT, 'size')
        names.append(item['name'])
    _require(names == sorted(set(names)) and set(names) >= {'manifest.json', 'proof.json', 'expected.json'}, 'files')
    if require_files:
        _require(set(path.name for path in directory.iterdir()) == set(names) | {'restore.json'}, 'files')
    return value


def _inflate(raw, part):
    _require(type(part['rawBytes']) is int and 0 < part['rawBytes'] <= MAX_RAW, 'size')
    try:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        inflated = decoder.decompress(raw, part['rawBytes'] + 1)
        _require(len(inflated) == part['rawBytes'] and decoder.eof and not decoder.unused_data
                 and not decoder.unconsumed_tail, 'gzip')
    except zlib.error as exc:
        raise MarketCacheError('cache_restore_gzip') from exc
    _require(sha(inflated) == part['rawSha256'], 'raw_hash')
    return inflated


def _load(directory, descriptor):
    items = {item['name']: item for item in descriptor['files']}
    metadata = {}
    for name in ['manifest.json', 'proof.json', 'expected.json']:
        raw = _read(directory, name, METADATA_LIMIT)
        _require(len(raw) == items[name]['bytes'] and sha(raw) == items[name]['sha256'], 'file_hash')
        metadata[name] = _json(raw)
    manifest, proof, expected = (metadata[name] for name in ['manifest.json', 'proof.json', 'expected.json'])
    _require(type(manifest) is dict and set(manifest) == {'schemaVersion', 'manifestHash', 'marketDate', 'previousTradingDate', 'generatedAt', 'source', 'groups'}, 'manifest')
    _require(manifest['schemaVersion'] == 'market-cache-v1' and manifest['manifestHash'] == descriptor['manifestHash']
             and sha(canonical({key: value for key, value in manifest.items() if key != 'manifestHash'})) == manifest['manifestHash'], 'manifest_hash')
    header = {key: manifest[key] for key in ['marketDate', 'previousTradingDate', 'generatedAt', 'source', 'groups']}
    _header(header)
    _require(header['marketDate'] == descriptor['marketDate'] and header['source'] == descriptor['source'], 'context')
    trusted = _expectations(header, expected)
    groups, names, total_raw, total_gzip = [], [], 0, 0
    extras = {'representation', 'codesHash', 'rawBytes', 'rawSha256', 'shards'}
    for group in manifest['groups']:
        _require(type(group) is dict and set(group) == set(trusted[group['key']]) | extras, 'group')
        fields = {key: value for key, value in group.items() if key not in extras}
        _group({**fields, 'body': b''}, header, trusted[group['key']])
        _require(group['codesHash'] == sha(canonical(group['codes'])) and _hash(group['rawSha256'])
                 and type(group['rawBytes']) is int and 0 < group['rawBytes'] <= MAX_TOTAL_RAW, 'group')
        total_raw += group['rawBytes']; _require(total_raw <= MAX_TOTAL_RAW, 'size')
        parts = group['shards']
        _require(type(parts) is list and 0 < len(parts) <= MAX_PARTS, 'parts')
        body = bytearray()
        for index, part in enumerate(parts):
            _require(type(part) is dict and set(part) == {'name', 'index', 'rawBytes', 'rawSha256', 'gzipBytes', 'gzipSha256'}, 'part')
            name = part['name']
            _require(_flat(name) and part['index'] == index and type(part['index']) is int and name not in names
                     and _hash(part['rawSha256']) and _hash(part['gzipSha256']), 'part')
            expected_name = f"{header['marketDate']}.{group['key'].replace(':', '-')}.{index}.{part['gzipSha256']}.json.gz"
            _require(name == expected_name and name in items and len(names) < MAX_PARTS, 'part')
            _require(type(part['gzipBytes']) is int and 0 < part['gzipBytes'] <= MAX_GZIP, 'size')
            total_gzip += part['gzipBytes']; _require(total_gzip <= MAX_TOTAL_GZIP, 'size')
            raw = _read(directory, name, MAX_GZIP)
            _require(len(raw) == part['gzipBytes'] == items[name]['bytes'] and sha(raw) == part['gzipSha256'] == items[name]['sha256'], 'file_hash')
            body.extend(_inflate(raw, part)); _require(len(body) <= group['rawBytes'], 'size')
            names.append(name)
        raw = bytes(body)
        _require(len(raw) == group['rawBytes'] and sha(raw) == group['rawSha256'], 'raw_hash')
        is_raw = fields['kind'].endswith('_raw')
        _require(group['representation'] == ('bytes' if is_raw else 'json'), 'representation')
        loaded = {**fields, 'body': raw if is_raw else _json(raw)}
        if is_raw: _require(sha(raw) == fields['sourceSha256'], 'source_hash')
        elif fields['kind'] == 'calendar_normalized': _calendar(loaded['body'], expected)
        else: _rows(loaded, expected)
        groups.append(loaded)
    _require(set(items) == set(names) | {'manifest.json', 'proof.json', 'expected.json'}, 'files')
    _verify_institutional_groups(groups)
    stock = next(group for group in groups if group['key'] == 'published_stock_inputs')['body']['rows']
    coverage = {key: {'known': sum(row['metrics'][key] is not None for row in stock),
                      'missing': sum(row['metrics'][key] is None for row in stock),
                      'zero': sum(row['metrics'][key] == 0 for row in stock)} for key in expected['metricKeys']}
    wanted = {'schemaVersion': 'market-cache-producer-proof-v1', 'semanticValidation': 'bounded-python-v1',
              'marketDate': header['marketDate'], 'previousTradingDate': header['previousTradingDate'], 'source': header['source'],
              'cacheComplete': True, 'manifestHash': manifest['manifestHash'], 'groupsVerified': 9, 'verifiedParts': names,
              'metricsComplete': all(item['missing'] == 0 for item in coverage.values()), 'metricCoverage': coverage}
    _require(proof == wanted, 'proof')
    return groups, expected, proof


def _receipts(group):
    bundle = _json(group['body'])
    _require(type(bundle) is dict and type(bundle.get('receipts')) is list and 0 < len(bundle['receipts']) <= 24, 'receipts')
    results = []
    for receipt in bundle['receipts']:
        _require(type(receipt) is dict and isinstance(receipt.get('rawBase64'), str)
                 and len(receipt['rawBase64']) <= (2 * 1024 * 1024 + 2) // 3 * 4 and _utc(receipt.get('retrievedAt')), 'receipt')
        try: raw = base64.b64decode(receipt['rawBase64'], validate=True)
        except (ValueError, TypeError) as exc: raise MarketCacheError('cache_restore_receipt') from exc
        _require(0 < len(raw) <= 2 * 1024 * 1024 and sha(raw) == receipt.get('rawSha256') and len(raw) == receipt.get('rawBytes'), 'receipt')
        results.append((receipt, raw))
    return results


def _official_semantics(groups, expected):
    by_key = {group['key']: group for group in groups}
    calendar = by_key['calendar_normalized']['body']
    receipts = _receipts(by_key['calendar_raw'])
    _require(len(receipts) == 1, 'calendar')
    receipt, raw = receipts[0]
    _require(receipt.get('sourceUrl') == SOURCE_URL and receipt.get('unit') == 'calendar'
             and receipt.get('requestYear') == expected['calendarYear'], 'calendar')
    parsed = build_calendar(_json(raw), year=expected['calendarYear'], fetched_at=receipt['retrievedAt'])
    _require(parsed == calendar, 'calendar')
    dates = []; target = date.fromisoformat(expected['marketDate'])
    for offset in range(60):
        day = (target - timedelta(days=offset)).isoformat()
        if is_open(calendar, day): dates.append(day)
        if len(dates) == 11: break
    _require(list(reversed(dates)) == expected['sessionDates'] and expected['previousTradingDate'] == dates[1]
             and expected['volumeDates'] == list(reversed(dates[:7])), 'window')
    volumes, months = {}, []
    for receipt, raw in _receipts(by_key['volume_raw']):
        month = receipt.get('requestMonth')
        _require(isinstance(month, str) and _date(month + '-01') and month not in months, 'volume')
        url = TWSE_STOCK_DAY + '?' + urlencode({'response': 'json', 'date': month.replace('-', '') + '01', 'stockNo': SYMBOL})
        _require(receipt.get('sourceUrl') == url and receipt.get('unit') == 'shares', 'volume')
        payload = _json(raw)
        reported = volume_date(payload.get('date')) if type(payload) is dict else None
        _require(type(payload) is dict and payload.get('stat') == 'OK' and reported is not None and reported.isoformat().startswith(month)
                 and type(payload.get('fields')) is list and payload['fields'][:2] == ['日期', '成交股數']
                 and type(payload.get('data')) is list, 'volume')
        seen = set()
        for row in payload['data']:
            _require(type(row) is list and len(row) >= 2, 'volume')
            day, value = volume_date(row[0]), _volume(row[1])
            _require(day is not None and day.isoformat().startswith(month) and day not in seen
                     and value is not None and value.is_integer() and value <= 2**53 - 1, 'volume')
            seen.add(day); volumes[day.isoformat()] = int(value)
        months.append(month)
    previous_month = (target.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    _require(sorted(months) == sorted([previous_month, target.strftime('%Y-%m')]), 'volume')
    rows = by_key['volume_normalized']['body']['rows']
    _require(all(row['marketDate'] in volumes and row['volume'] == volumes[row['marketDate']] for row in rows), 'volume')
    stock_rows = by_key['published_stock_inputs']['body']['rows']
    for row in stock_rows:
        evidence = row.get('evidence')
        _require(type(evidence) is dict and evidence.get('code') == row['code'] and evidence.get('asOf') == expected['marketDate']
                 and stock_metrics(evidence, expected['marketDate']) == row['metrics'], 'stock')
    return by_key


def _plan(by_key, source_dir, stock_dir, expected):
    files = {}
    for market in ['TWSE', 'TPEx']:
        for receipt, raw in _receipts(by_key['institutional_raw:' + market]):
            day = date.fromisoformat(receipt['reportedDate'])
            url = TWSE_ENDPOINT if market == 'TWSE' else TPEX_ENDPOINT + '?' + urlencode({'type': 'Daily', 'sect': 'AL', 'date': day.strftime('%Y/%m/%d'), 'response': 'csv'})
            encoding = 'utf-8' if market == 'TWSE' else 'MS950'
            existing = _cached_raw(source_dir, market=market, day=day, source_url=url, encoding='utf-8' if market == 'TWSE' else 'auto')
            if existing is not None:
                _require(existing[0] == raw, 'conflict')
                if '_recoveryReceipt' not in existing[1]:
                    _require(existing[1].get('codes') == receipt['codes'] and existing[1].get('status') == 'complete', 'conflict')
                    continue
                receipt = {**receipt, 'retrievedAt': existing[1]['_recoveryReceipt']['retrievedAt']}
            name = f"inst-{market.lower()}-{day.isoformat()}-{sha(raw)}.raw.json"
            metadata = {key: receipt[key] for key in ['requestDate', 'sourceUrl', 'unit', 'retrievedAt', 'rawSha256', 'rawBytes', 'market', 'reportedDate', 'validated', 'codes']}
            metadata = {**metadata, 'rawFile': name, 'encoding': encoding, 'status': 'complete'}
            files[source_dir / name] = raw
            original = {key: metadata[key] for key in ['requestDate', 'sourceUrl', 'unit', 'retrievedAt', 'rawFile', 'rawSha256', 'rawBytes']}
            files[source_dir / (name[:-9] + '.receipt.json')] = canonical({**original, 'rawBase64': base64.b64encode(raw).decode('ascii')})
            files[source_dir / f'institutional-{market}-{day.isoformat()}-validated.json'] = canonical(metadata)
    for family in ['calendar', 'volume']:
        family_files, groups = {}, []
        for form in ['raw', 'normalized']:
            group = by_key[family + '_' + form]
            name = family + ('.raw.bundle.json' if form == 'raw' else '.normalized.json')
            raw = group['body'] if form == 'raw' else canonical(group['body'])
            family_files[name] = raw
            groups.append({**{key: value for key, value in group.items() if key != 'body'}, 'bodyFile': name})
        family_files[family + '-receipt-index.json'] = canonical({'groups': groups})
        for name, raw in family_files.items():
            files[source_dir / 'restored' / expected['marketDate'] / name] = raw
        if not any((source_dir / name).exists() or (source_dir / name).is_symlink() for name in family_files):
            for name, raw in family_files.items(): files[source_dir / name] = raw
    for row in by_key['published_stock_inputs']['body']['rows']:
        files[stock_dir / expected['marketDate'] / (row['code'] + '.json')] = canonical(row['evidence'])
    files[stock_dir / expected['marketDate'] / 'restore-metadata.json'] = canonical({'marketDate': expected['marketDate'], 'source': expected['source'], 'codes': by_key['published_stock_inputs']['codes']})
    for path, raw in files.items():
        safe_directory(path.parent)
        _require(not path.is_symlink(), 'path')
        if path.exists():
            _require(path.is_file() and path.stat().st_size == len(raw), 'conflict')
            with path.open('rb') as stream:
                _require(stream.read(len(raw) + 1) == raw, 'conflict')
    return files


def restore_market_cache(directory: Path, *, descriptor_sha256: str, market_date: str, source: dict,
                         target_market_date: str, source_cache_dir: Path, stock_cache_dir: Path) -> dict:
    """Validate everything before installing missing immutable cache inputs."""
    try:
        directory, source_dir, stock_dir = (safe_directory(path) for path in [directory, source_cache_dir, stock_cache_dir])
        _require(_date(target_market_date) and _date(market_date) and market_date <= target_market_date, 'target_date')
        descriptor = _descriptor(directory, descriptor_sha256, market_date, source)
        groups, expected, proof = _load(directory, descriptor)
        by_key = _official_semantics(groups, expected)
        files = _plan(by_key, source_dir, stock_dir, expected)
        for path, raw in files.items(): _install_missing(path, raw)
        return {'schemaVersion': 'market-cache-restore-proof-v1', 'restoreUsable': True,
                'marketDate': market_date, 'targetMarketDate': target_market_date, 'manifestHash': descriptor['manifestHash'],
                'descriptorSha256': descriptor_sha256, 'sessionCount': len(expected['sessionDates']),
                'volumeSessionCount': len(expected['volumeDates']), 'stockCount': len(by_key['published_stock_inputs']['codes']),
                'metricsComplete': proof['metricsComplete'], 'metricCoverage': proof['metricCoverage'], 'installedFiles': len(files)}
    except MarketCacheError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        raise MarketCacheError('cache_restore_invalid') from exc
