"""Pure, bounded full-market source cache producer; no fetching or quota state."""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlsplit

MAX_GZIP = 4 * 1024 * 1024
MAX_RAW = 32 * 1024 * 1024
MAX_TOTAL_RAW = 256 * 1024 * 1024
MAX_TOTAL_GZIP = 64 * 1024 * 1024
MAX_PARTS = 256
ROLES = ('institutional_raw:TWSE', 'institutional_raw:TPEx',
         'institutional_normalized:TWSE', 'institutional_normalized:TPEx',
         'calendar_raw', 'calendar_normalized', 'volume_raw', 'volume_normalized', 'published_stock_inputs')
FIELDS = {'key', 'kind', 'market', 'codes', 'dates', 'unit', 'sourceUrl', 'sourceSha256', 'normalizedFromSha256'}
SECRET = re.compile(r'^(token|api_?key|password|authorization|accountIdentity|accountEmail|rawLogs|signedUrl)$', re.I)


class MarketCacheError(ValueError):
    """Sanitized contract failure; never includes source bytes or URLs."""


def _check(condition: bool, category: str) -> None:
    if not condition:
        raise MarketCacheError(f'cache_{category}')


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _number(value: int | float) -> str:
    if isinstance(value, int):
        _check(abs(value) <= 2**53 - 1, 'numbers')
    _check(math.isfinite(value), 'numbers')
    if value == 0:
        return '0'
    if isinstance(value, int):
        _check(abs(value) <= 2**53 - 1, 'numbers')
        return str(value)
    # Match ECMAScript's fixed/scientific notation boundaries used by the peer.
    shortest = repr(value)
    if 1e-6 <= abs(value) < 1e21:
        return format(Decimal(shortest), 'f').rstrip('0').rstrip('.') if '.' in format(Decimal(shortest), 'f') else format(Decimal(shortest), 'f')
    mantissa, exponent = shortest.lower().split('e') if 'e' in shortest.lower() else (shortest, '0')
    return f'{mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa}e{int(exponent):+d}' if int(exponent) >= 0 else f'{mantissa}e{int(exponent)}'


def canonical(value: Any, depth: int = 0) -> bytes:
    """Canonical UTF-8 JSON compatible with the deterministic JS validator."""
    _check(depth <= 24, 'json_depth')
    if value is None or isinstance(value, (bool, str)):
        try:
            return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        except UnicodeError as exc:
            raise MarketCacheError('cache_json') from exc
    if type(value) in (int, float):
        return _number(value).encode()
    if isinstance(value, list):
        return b'[' + b','.join(canonical(item, depth + 1) for item in value) + b']'
    _check(type(value) is dict and all(isinstance(key, str) for key in value), 'json')
    _check(not any(SECRET.fullmatch(key) for key in value), 'secret')
    try:
        keys = sorted(value, key=lambda key: key.encode('utf-16-be'))
    except UnicodeError as exc:
        raise MarketCacheError('cache_json') from exc
    return b'{' + b','.join(canonical(key, depth + 1) + b':' + canonical(value[key], depth + 1) for key in keys) + b'}'


def _date(value: Any) -> bool:
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _utc(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)', value):
        return False
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return True
    except ValueError:
        return False


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def _sorted(values: Any, predicate) -> bool:
    return isinstance(values, list) and all(predicate(value) for value in values) and values == sorted(set(values))


def _source_url(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r'https://[a-zA-Z0-9.-]+/[^\s#]*', value):
        return False
    try:
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.port or parsed.fragment:
            return False
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True, errors='strict'):
            normalized = key.replace('-', '').replace('_', '').lower()
            if re.search('token|secret|password|apikey|authorization|signature|credential', normalized) or normalized in {'sig', 'key', 'auth'} or normalized.startswith('xamz'):
                return False
        return True
    except (ValueError, UnicodeError):
        return False


def _header(value: dict[str, Any]) -> None:
    _check(type(value) is dict and set(value) == {'marketDate', 'previousTradingDate', 'generatedAt', 'source', 'groups'}, 'header')
    _check(_date(value['marketDate']) and _date(value['previousTradingDate']) and value['previousTradingDate'] < value['marketDate'], 'dates')
    _check(_utc(value['generatedAt']), 'generated_at')
    source = value['source']
    _check(type(source) is dict and set(source) == {'requestId', 'actionsRunId', 'sourceGitCommit'}, 'lineage')
    for key, pattern in [('sourceGitCommit', '[a-f0-9]{40}'), ('actionsRunId', r'\d{1,20}'), ('requestId', '[a-zA-Z0-9:_-]{1,160}')]:
        _check(isinstance(source[key], str) and re.fullmatch(pattern, source[key]) is not None, 'lineage')
    groups = value['groups']
    _check(isinstance(groups, list) and all(type(g) is dict and isinstance(g.get('key'), str) for g in groups) and sorted(g['key'] for g in groups) == sorted(ROLES), 'roles')


def _group(group: dict[str, Any], header: dict[str, Any], trusted: dict[str, Any]) -> None:
    _check(isinstance(group.get('kind'), str), 'group')
    fields = FIELDS | ({'codesByDate'} if group['kind'].startswith('institutional') else set())
    _check(set(group) == fields | {'body'} and type(trusted) is dict and set(trusted) == fields, 'group')
    _check(all(group[key] == trusted[key] for key in fields), 'expected_group')
    kind, _, market = group['key'].partition(':')
    _check(group['kind'] == kind and group['market'] == (market or ('ALL' if kind == 'published_stock_inputs' else 'TWSE')), 'roles')
    dates, codes = group['dates'], group['codes']
    _check(_sorted(dates, _date) and 1 <= len(dates) <= 60 and dates[-1] == header['marketDate'], 'dates')
    _check(_sorted(codes, lambda code: isinstance(code, str) and re.fullmatch(r'\d{4,6}[A-Z]?', code) is not None) and len(codes) <= 10000, 'codes')
    _check(len(codes) == 0 if kind.startswith('calendar') else len(codes) > 0, 'codes')
    if kind.startswith('institutional'):
        roster = group['codesByDate']
        _check(type(roster) is dict and sorted(roster) == dates, 'codes_by_date')
        _check(all(_sorted(daily, lambda code: isinstance(code, str) and code in codes) and daily for daily in roster.values()), 'codes_by_date')
        _check(sorted({code for daily in roster.values() for code in daily}) == codes, 'codes_by_date')
    _check(isinstance(group['unit'], str) and group['unit'] in {'shares', 'lots', 'mixed', 'calendar'}, 'units')
    if kind.startswith('volume'):
        _check(codes == ['00631L'] and header['previousTradingDate'] in dates, 'dates')
    if kind in {'institutional_normalized', 'volume_normalized'}:
        _check(group['unit'] == 'shares', 'units')
    if kind.startswith('calendar'):
        _check(group['unit'] == 'calendar', 'units')
    if kind == 'published_stock_inputs':
        _check(group['unit'] == 'mixed', 'units')
    _check(_source_url(group['sourceUrl']), 'source_url')
    _check(_hash(group['sourceSha256']), 'source_hash')
    _check(group['normalizedFromSha256'] == group['sourceSha256'] if kind.endswith('_normalized') else group['normalizedFromSha256'] is None, 'source_hash')


def _calendar(body: Any, expected: dict[str, Any]) -> None:
    from pipeline.trading_calendar import calendar_years, recent_sessions
    _check(type(expected.get('calendarYear')) is int and expected['calendarYear'] == int(expected['marketDate'][:4]), 'calendar')
    try:
        years = calendar_years(body)
        sessions = list(reversed(recent_sessions(body, expected['marketDate'], count=11)))
    except (ValueError, TypeError, KeyError) as exc:
        raise MarketCacheError('cache_calendar') from exc
    _check(expected['calendarYear'] in years, 'calendar')
    _check(sessions == expected['sessionDates'] and expected['volumeDates'] == sessions[-7:], 'calendar')


def validate_ownership_bundle(bundle: Any, market_date: str) -> dict:
    """Validate exact producer bytes independently of display evidence."""
    _check(type(bundle) is dict and set(bundle) == {'schemaVersion', 'generationCommit', 'manifestSha256', 'filesBase64'}, 'ownership_bundle')
    _check(bundle['schemaVersion'] == 'ownership-bundle-v1' and isinstance(bundle['generationCommit'], str)
           and re.fullmatch('[a-f0-9]{40}', bundle['generationCommit']) is not None and _hash(bundle['manifestSha256']), 'ownership_bundle')
    encoded = bundle['filesBase64']
    _check(type(encoded) is dict and 3 <= len(encoded) <= 10000, 'ownership_files')
    files, total = {}, 0
    for name, value in encoded.items():
        _check(isinstance(name, str) and re.fullmatch(r'(?:manifest|snapshot|ownership_snapshot|queue)\.json|receipts/[a-f0-9]{64}\.(?:raw|json)', name) is not None, 'ownership_path')
        _check(isinstance(value, str) and len(value) <= MAX_RAW * 2, 'ownership_size')
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise MarketCacheError('cache_ownership_encoding') from exc
        total += len(raw)
        _check(0 < len(raw) <= MAX_RAW and total <= MAX_TOTAL_RAW, 'ownership_size')
        _check(base64.b64encode(raw).decode('ascii') == value, 'ownership_encoding')
        files[name] = raw
    _check('manifest.json' in files and sha(files['manifest.json']) == bundle['manifestSha256'], 'ownership_manifest')
    try:
        manifest = json.loads(files['manifest.json'])
        snapshot = json.loads(files.get('snapshot.json', files.get('ownership_snapshot.json', b'')))
        queue = json.loads(files['queue.json'])
    except (ValueError, KeyError, UnicodeError) as exc:
        raise MarketCacheError('cache_ownership_json') from exc
    canonical(manifest); canonical(snapshot); canonical(queue)
    _check(manifest.get('schemaVersion') == 'ownership-generation-v1' and _date(manifest.get('verifiedMarketDate'))
           and manifest['verifiedMarketDate'] <= market_date and re.fullmatch('[a-f0-9]{40}', str(manifest.get('sourceGitCommit'))) is not None, 'ownership_manifest')
    listed = manifest.get('files')
    _check(isinstance(listed, list) and len(listed) == len(files) - 1, 'ownership_files')
    seen = set()
    for item in listed:
        _check(type(item) is dict and set(item) == {'path', 'sha256', 'size'} and item['path'] in files
               and item['path'] != 'manifest.json' and item['path'] not in seen, 'ownership_files')
        seen.add(item['path'])
        _check(type(item['size']) is int and item['size'] == len(files[item['path']]) and item['sha256'] == sha(files[item['path']]), 'ownership_hash')
    _check(snapshot.get('schemaVersion') == 'ownership-snapshot-v1' and queue.get('schemaVersion') == 'ownership-queue-v1'
           and snapshot.get('generationId') == manifest.get('generationId')
           and snapshot.get('verifiedMarketDate') == queue.get('verifiedMarketDate') == manifest['verifiedMarketDate']
           and isinstance(snapshot.get('rows'), list) and isinstance(queue.get('jobs'), list), 'ownership_semantics')
    binding_keys = ('verifiedMarketDate', 'sourceGitCommit', 'requestId', 'actionsRunId', 'actionsRunAttempt', 'previousGeneration', 'rosterHash', 'targetMonths', 'formulaVersion', 'priorityRosterMarketDate', 'priorityRosterPublicationHash')
    _check(all(key in manifest for key in binding_keys), 'ownership_binding')
    binding = {key: manifest[key] for key in binding_keys}
    from pipeline.ownership_checks import FORMULA_VERSION
    _check(binding['formulaVersion'] == FORMULA_VERSION, 'ownership_formula')
    _check(manifest['generationId'] == sha(canonical({'binding': binding, 'queueHash': sha(files['queue.json'])})), 'ownership_generation_hash')
    _check(isinstance(queue.get('roster'), list) and binding['rosterHash'] == sha(canonical(queue['roster']))
           and binding['targetMonths'] == queue.get('targetMonths'), 'ownership_roster')
    _check(binding['priorityRosterMarketDate'] == queue.get('priorityRosterMarketDate') and binding['priorityRosterPublicationHash'] == queue.get('priorityRosterPublicationHash'), 'ownership_priority_roster')
    _check(binding['priorityRosterMarketDate'] is None or _date(binding['priorityRosterMarketDate']) and binding['priorityRosterMarketDate'] <= manifest['verifiedMarketDate'], 'ownership_priority_date')
    _check(binding['priorityRosterPublicationHash'] is None or _hash(binding['priorityRosterPublicationHash']), 'ownership_priority_hash')
    from scripts.fetch_ownership import completed_months
    _check(binding['targetMonths'] == completed_months(manifest['verifiedMarketDate']), 'ownership_months')
    for receipt in queue.get('receipts', []):
        _check(type(receipt) is dict, 'ownership_receipt')
        name = 'receipts/' + str(receipt.get('rawFile'))
        _check(name in files and receipt.get('rawSha256') == sha(files[name]) and receipt.get('rawBytes') == len(files[name]), 'ownership_receipt_hash')
        url = urlsplit(str(receipt.get('sourceURL')))
        _check(_source_url(receipt.get('sourceURL')) and url.hostname in {'mops.twse.com.tw', 'www.tdcc.com.tw', 'opendata.tdcc.com.tw', 'openapi.twse.com.tw', 'www.tpex.org.tw'}, 'ownership_origin')
        parameters = receipt.get('parameters')
        _check(type(parameters) is dict and not any(re.search('token|cookie|secret|csrf|password|authorization|credential|apikey', key, re.I) for key in parameters), 'ownership_private_parameter')
        _check(receipt.get('rawSanitization') in {'none', 'transient-session-controls-removed', 'roster-filtered-csv-v1'} and _hash(receipt.get('originalResponseSha256')), 'ownership_sanitization')
        if receipt.get('rawSanitization') == 'roster-filtered-csv-v1':
            selected = receipt.get('selectedCodes')
            _check(receipt.get('source') == 'TDCC_LATEST' and receipt.get('sourceURL') == 'https://opendata.tdcc.com.tw/getOD.ashx?id=1-5'
                   and isinstance(selected, list) and 1 <= len(selected) <= 100 and len(set(selected)) == len(selected)
                   and all(isinstance(code, str) and re.fullmatch(r'\d{4,6}[A-Z]?', code) for code in selected)
                   and all(row.get('code') in selected for row in receipt.get('rows', [])), 'ownership_filtered_roster')
        _check(not re.search(rb'SYNCHRONIZER_TOKEN|SYNCHRONIZER_URI', files[name], re.I), 'ownership_transient_control')
        source_date = receipt.get('sourceDate')
        _check(source_date is None or isinstance(source_date, str) and source_date <= manifest['verifiedMarketDate'], 'ownership_period')
        metadata = 'receipts/' + str(receipt.get('receiptFile'))
        _check(metadata in files and json.loads(files[metadata]) == receipt, 'ownership_receipt_metadata')
    queue_rows = queue.get('rows')
    _check(isinstance(queue_rows, list), 'ownership_rows')
    receipt_map = {'receipts/' + str(item.get('receiptFile')): item for item in queue.get('receipts', [])}
    queue_identities = {canonical(row) for row in queue_rows}
    _check(all(canonical(row) in queue_identities for row in snapshot['rows']), 'ownership_snapshot_binding')
    _check(all(type(row) is dict and row.get('code') in queue.get('roster', []) for row in snapshot['rows']), 'ownership_snapshot_roster')
    fields = ('code', 'period', 'asOf', 'sourceDate', 'largeHolderPct', 'shareholderCount', 'directorSupervisorPct', 'directorSupervisorShares', 'officialDirectorSupervisorShares', 'directorDenominator', 'directorIdentityConsistent')
    metrics = fields[4:]
    for row in queue_rows:
        _check(type(row) is dict and isinstance(row.get('code'), str) and re.fullmatch(r'\d{4,6}[A-Z]?', row['code']), 'ownership_row')
        for key in ('period', 'asOf', 'sourceDate', 'publishedAt', 'availableAt'):
            value = row.get(key)
            _check(value is None or isinstance(value, str) and value[:10] <= manifest['verifiedMarketDate'], 'ownership_row_period')
        top_receipt = receipt_map.get(row.get('rawReceiptPath'))
        _check(top_receipt is not None and row.get('rawSha256') == top_receipt['rawSha256']
               and row.get('sourceURL') == top_receipt['sourceURL'], 'ownership_row_receipt')
        observations = row.get('sourceObservations') or [row]
        _check(isinstance(observations, list) and observations, 'ownership_observations')
        for observation in observations:
            _check(type(observation) is dict and observation.get('code') == row['code'] and observation.get('period') == row.get('period'), 'ownership_observation')
            for key in ('period', 'asOf', 'sourceDate', 'publishedAt', 'availableAt'):
                value = observation.get(key)
                _check(value is None or isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}(?:-\d{2})?(?:T[^ ]+)?', value)
                       and value[:10] <= manifest['verifiedMarketDate'], 'ownership_row_period')
            receipt = receipt_map.get(observation.get('rawReceiptPath'))
            _check(receipt is not None and observation.get('rawSha256') == receipt['rawSha256']
                   and observation.get('sourceURL') == receipt['sourceURL'], 'ownership_row_receipt')
            _check(any(all(observation.get(field) == original.get(field) for field in fields) for original in receipt.get('rows', [])), 'ownership_row_values')
        for field in metrics:
            observed = next((item[field] for item in observations if item.get(field) is not None), None)
            _check(row.get(field) == observed, 'ownership_merged_values')
    return {**bundle, 'decodedFiles': files, 'manifest': manifest}


def _rows(group: dict[str, Any], expected: dict[str, Any]) -> None:
    body = group['body']
    _check(type(body) is dict and isinstance(body.get('rows'), list), 'coverage')
    rows = body['rows']
    if group['kind'] == 'published_stock_inputs' and 'ownershipBundle' in body:
        validate_ownership_bundle(body['ownershipBundle'], expected['marketDate'])
    institutional = group['kind'] == 'institutional_normalized'
    _check(len(rows) == (sum(len(codes) for codes in group['codesByDate'].values()) if institutional else len(group['dates']) * len(group['codes'])), 'coverage')
    keys = []
    for row in rows:
        _check(type(row) is dict and row.get('code') in group['codes'] and row.get('marketDate') in group['dates'], 'coverage')
        keys.append((row['marketDate'], row['code']))
        if institutional:
            _check(row['code'] in group['codesByDate'][row['marketDate']], 'coverage')
        if group['kind'] == 'institutional_normalized':
            _check(row.get('unit') == 'shares', 'units')
            _check(all(type(row.get(k)) is int and 0 <= row[k] <= 2**53 - 1 for k in ['buy', 'sell']) and type(row.get('net')) is int and abs(row['net']) <= 2**53 - 1 and row['net'] == row['buy'] - row['sell'], 'numbers')
        elif group['kind'] == 'volume_normalized':
            _check(row.get('unit') == 'shares' and type(row.get('volume')) is int and 0 <= row['volume'] <= 2**53 - 1, 'numbers')
        else:
            metrics = row.get('metrics')
            _check(type(metrics) is dict and set(metrics) == set(expected['metricKeys']), 'metrics')
            _check(all(v is None or type(v) in (int, float) and math.isfinite(v) for v in metrics.values()), 'metrics')
    _check(len(set(keys)) == len(keys), 'coverage')


def _expectations(header: dict[str, Any], expected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _check(type(expected) is dict and all(header[key] == expected.get(key) for key in ['marketDate', 'previousTradingDate', 'source']), 'expected_lineage')
    sessions, volume = expected.get('sessionDates'), expected.get('volumeDates')
    _check(_sorted(sessions, _date) and len(sessions) == 11 and sessions[-2:] == [header['previousTradingDate'], header['marketDate']], 'window')
    _check(volume == sessions[-7:], 'volume_window')
    metrics = expected.get('metricKeys')
    _check(isinstance(metrics, list) and len(metrics) > 0 and all(isinstance(k, str) and k and not SECRET.fullmatch(k) for k in metrics) and len(set(metrics)) == len(metrics), 'metrics')
    groups = expected.get('groups')
    _check(isinstance(groups, list) and all(type(g) is dict and isinstance(g.get('key'), str) for g in groups) and sorted(g['key'] for g in groups) == sorted(ROLES), 'roles')
    trusted = {g['key']: g for g in groups}
    for group in groups:
        _check(isinstance(group.get('kind'), str), 'group')
        fields = FIELDS | ({'codesByDate'} if group['kind'].startswith('institutional') else set())
        _check(set(group) == fields, 'group')
        if group.get('kind', '').startswith('institutional'):
            _check(group.get('dates') == sessions, 'window')
        if group.get('kind', '').startswith('volume'):
            _check(group.get('dates') == volume, 'volume_window')
    return trusted


def _shards(raw: bytes, max_raw: int, max_compressed: int):
    if len(raw) > max_raw:
        midpoint = len(raw) // 2
        yield from _shards(raw[:midpoint], max_raw, max_compressed)
        yield from _shards(raw[midpoint:], max_raw, max_compressed)
        return
    compressed = bytearray(gzip.compress(raw, compresslevel=9, mtime=0))
    compressed[9] = 255  # Stable OS marker across Python/platform versions.
    if len(compressed) > max_compressed:
        _check(len(raw) > 1, 'limit')
        midpoint = len(raw) // 2
        yield from _shards(raw[:midpoint], max_raw, max_compressed)
        yield from _shards(raw[midpoint:], max_raw, max_compressed)
        return
    yield raw, bytes(compressed)


def build_market_cache(payload: dict[str, Any], expected: dict[str, Any], *, max_raw_bytes: int = MAX_RAW, max_compressed_bytes: int = MAX_GZIP) -> dict[str, Any]:
    """Build only after independent expectations prove full source coverage.

    `expected` must come from authenticated run lineage and full source rosters;
    deriving it from this output manifest would remove the trust boundary.
    """
    _header(payload)
    trusted = _expectations(payload, expected)
    _check(type(max_raw_bytes) is int and 1 <= max_raw_bytes <= MAX_RAW and type(max_compressed_bytes) is int and 32 <= max_compressed_bytes <= MAX_GZIP, 'limit')
    descriptors, files = [], {}
    total_raw, total_gzip = 0, 0
    for group in payload['groups']:
        _group(group, payload, trusted[group['key']])
        body = group['body']
        raw = body if type(body) is bytes else canonical(body)
        total_raw += len(raw)
        _check(0 < len(raw) and total_raw <= MAX_TOTAL_RAW, 'raw_size')
        if group['kind'].endswith('_raw'):
            _check(type(body) is bytes and sha(raw) == group['sourceSha256'], 'source_hash')
        else:
            _check(type(body) is dict, 'representation')
            if group['kind'] == 'calendar_normalized':
                _calendar(body, expected)
            else:
                _rows(group, expected)
        parts = []
        for index, (chunk, compressed) in enumerate(_shards(raw, max_raw_bytes, max_compressed_bytes)):
            total_gzip += len(compressed)
            _check(len(files) < MAX_PARTS and total_gzip <= MAX_TOTAL_GZIP, 'total_limit')
            digest = sha(compressed)
            name = f"{payload['marketDate']}.{group['key'].replace(':', '-')}.{index}.{digest}.json.gz"
            parts.append({'name': name, 'index': index, 'rawBytes': len(chunk), 'rawSha256': sha(chunk), 'gzipBytes': len(compressed), 'gzipSha256': digest})
            files = {**files, name: compressed}
        metadata = {key: value for key, value in group.items() if key != 'body'}
        descriptors.append({**metadata, 'representation': 'bytes' if type(body) is bytes else 'json',
                            'codesHash': sha(canonical(group['codes'])), 'rawBytes': len(raw), 'rawSha256': sha(raw), 'shards': parts})
    for group in descriptors:
        if group['kind'].endswith('_normalized'):
            receipt = next(g for g in descriptors if g['key'] == group['key'].replace('_normalized', '_raw'))
            _check(receipt['rawSha256'] == group['normalizedFromSha256'], 'source_hash')
    _check(len(files) <= MAX_PARTS and sum(len(content) for content in files.values()) <= MAX_TOTAL_GZIP and sum(g['rawBytes'] for g in descriptors) <= MAX_TOTAL_RAW, 'total_limit')
    manifest = {**{key: value for key, value in payload.items() if key != 'groups'}, 'schemaVersion': 'market-cache-v1', 'groups': descriptors}
    manifest = {**manifest, 'manifestHash': sha(canonical(manifest))}
    stock_rows = next(g for g in payload['groups'] if g['kind'] == 'published_stock_inputs')['body']['rows']
    coverage = {key: {'known': sum(row['metrics'][key] is not None for row in stock_rows),
                      'missing': sum(row['metrics'][key] is None for row in stock_rows),
                      'zero': sum(row['metrics'][key] == 0 for row in stock_rows)} for key in expected['metricKeys']}
    proof = {'schemaVersion': 'market-cache-producer-proof-v1', 'semanticValidation': 'bounded-python-v1',
             'marketDate': payload['marketDate'], 'previousTradingDate': payload['previousTradingDate'],
             'source': {**payload['source']}, 'cacheComplete': True, 'manifestHash': manifest['manifestHash'], 'groupsVerified': len(descriptors),
             'verifiedParts': [part['name'] for group in descriptors for part in group['shards']],
             'metricsComplete': all(value['missing'] == 0 for value in coverage.values()), 'metricCoverage': coverage}
    return {'manifest': manifest, 'files': files, 'proof': proof}
