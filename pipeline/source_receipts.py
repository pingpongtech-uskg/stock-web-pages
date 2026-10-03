"""Bounded exact-byte receipts for public official sources; no HTTP or secrets."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

MAX_SOURCE_BYTES = 2 * 1024 * 1024


def read_raw(response, *, max_bytes: int = MAX_SOURCE_BYTES) -> bytes:
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_SOURCE_BYTES:
        raise ValueError('invalid source byte limit')
    raw = response.read(max_bytes + 1)
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise ValueError('source response exceeds bounded binary contract')
    return raw


def _public_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('source URL must be public HTTPS')
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        key = key.replace('_', '').replace('-', '').lower()
        if re.search('token|secret|password|apikey|authorization|signature|credential', key) or key in {'sig', 'key', 'auth'}:
            raise ValueError('source URL contains private parameters')


def _prefix(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch('[a-z0-9][a-z0-9._-]{0,100}', value) or '..' in value:
        raise ValueError('invalid receipt filename')


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def safe_directory(directory: Path) -> Path:
    """Bind a directory without user symlink components; allow macOS OS aliases."""
    directory = Path(os.path.abspath(directory))
    system_aliases = {Path('/tmp'): Path('/private/tmp'), Path('/var'): Path('/private/var')}
    for component in (*reversed(directory.parents), directory):
        if component.is_symlink() and system_aliases.get(component) != component.resolve():
            raise ValueError('source directory must not contain symlinks')
    return directory.resolve()


def _write(directory: Path, name: str, raw: bytes) -> None:
    directory = safe_directory(directory)
    _prefix(name)
    destination = directory / name
    if destination.is_symlink():
        raise ValueError('receipt file must not be a symlink')
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.receipt-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(raw)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def capture_raw(directory: Path, *, prefix: str, raw: bytes, source_url: str, unit: str,
                request_period: dict, retrieved_at: str) -> dict:
    """Save raw bytes before decoding; caller adds only validated reported dates."""
    _prefix(prefix)
    _public_url(source_url)
    timestamp = datetime.fromisoformat(retrieved_at.replace('Z', '+00:00'))
    if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
        raise ValueError('receipt time must be UTC')
    if not isinstance(raw, bytes) or len(raw) > MAX_SOURCE_BYTES or unit not in {'calendar', 'shares', 'lots'}:
        raise ValueError('invalid raw receipt')
    if not request_period or not set(request_period) <= {'requestYear', 'requestMonth', 'requestDate'}:
        raise ValueError('invalid receipt request period')
    for key, value in request_period.items():
        if key == 'requestYear':
            valid = type(value) is int and 1900 <= value <= 2200
        else:
            try:
                parsed = date.fromisoformat(value + '-01' if key == 'requestMonth' else value)
                valid = parsed.isoformat()[:7 if key == 'requestMonth' else 10] == value
            except (TypeError, ValueError):
                valid = False
        if not valid:
            raise ValueError('invalid receipt request period')
    digest = hashlib.sha256(raw).hexdigest()
    stem = f'{prefix}-{digest}'
    receipt = {**request_period, 'sourceUrl': source_url, 'unit': unit, 'retrievedAt': retrieved_at,
               'rawFile': stem + '.raw.json', 'rawSha256': digest, 'rawBytes': len(raw),
               'rawBase64': base64.b64encode(raw).decode('ascii')}
    _write(directory, receipt['rawFile'], raw)
    _write(directory, stem + '.receipt.json', _json(receipt))
    return receipt


def write_bundle(directory: Path, *, prefix: str, receipts: list[dict], normalized, group: dict) -> dict:
    """Bind two group fragments to one container retaining every original body."""
    directory = safe_directory(directory)
    _prefix(prefix)
    _public_url(group['sourceUrl'])
    if not receipts:
        raise ValueError('receipt bundle must not be empty')
    for receipt in receipts:
        _prefix(receipt['rawFile'])
        _public_url(receipt['sourceUrl'])
        path = Path(directory) / receipt['rawFile']
        if path.is_symlink():
            raise ValueError('receipt file must not be a symlink')
        with path.open('rb') as source:
            raw = read_raw(source)
        if (len(raw) != receipt['rawBytes'] or hashlib.sha256(raw).hexdigest() != receipt['rawSha256'] or
                base64.b64decode(receipt['rawBase64'], validate=True) != raw or receipt['unit'] != group['unit']):
            raise ValueError('receipt source hash mismatch')
    bundle = _json({'schemaVersion': 'source-receipt-bundle-v1', 'receipts': receipts})
    digest = hashlib.sha256(bundle).hexdigest()
    raw_file, normalized_file = prefix + '.raw.bundle.json', prefix + '.normalized.json'
    _write(directory, raw_file, bundle)
    _write(directory, normalized_file, _json(normalized))
    groups = []
    for form, body_file in [('raw', raw_file), ('normalized', normalized_file)]:
        kind = group['kind'] + '_' + form
        key = kind + (':' + group['market'] if group['kind'] == 'institutional' else '')
        groups.append({**group, 'key': key, 'kind': kind, 'sourceSha256': digest,
                       'normalizedFromSha256': digest if form == 'normalized' else None, 'bodyFile': body_file})
    result = {'groups': groups}
    _write(directory, prefix + '-receipt-index.json', _json(result))
    return result
