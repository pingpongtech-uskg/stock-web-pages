"""Verified, temporary TWSE full-day closure notices for calendar gaps."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

FEED_URL = 'https://www.twse.com.tw/rwd/zh/news/feed?type=rss'
DETAIL_PREFIX = 'https://www.twse.com.tw/rwd/zh/news/newsDetail/'
FEED_LIMIT = 256 * 1024
DETAIL_LIMIT = 256 * 1024
MAX_CLOSURE_EVIDENCE_BYTES = 1024 * 1024
MAX_NOTICES = 8
CONTENT_TAG = '{http://purl.org/rss/1.0/modules/content/}encoded'
TITLE_RE = re.compile(r'^臺灣證券交易所集中交易市場(?P<year>\d{3})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日休市一天$')
DETAIL_PATH_RE = re.compile(r'^/rwd/zh/news/newsDetail/[0-9a-fA-F]{32}$')
PDF_PATH_RE = re.compile(r'^/news/news/tsecnews/[0-9a-fA-F]{32}\.pdf$')


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _raw_record(raw: bytes, url: str, retrieved_at: str, limit: int) -> dict:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
        raise ValueError('closure source size invalid')
    timestamp = datetime.fromisoformat(retrieved_at.replace('Z', '+00:00'))
    if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
        raise ValueError('closure retrieval timestamp invalid')
    return {'sourceUrl': url, 'retrievedAt': timestamp.isoformat(), 'rawBytes': len(raw),
            'rawSha256': _digest(raw), 'rawBase64': base64.b64encode(raw).decode('ascii')}


def _decode_record(record: object, *, url: str, limit: int) -> bytes:
    if (type(record) is not dict or record.get('sourceUrl') != url or
        type(record.get('rawBytes')) is not int or not 0 < record['rawBytes'] <= limit or
        not isinstance(record.get('rawSha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', record['rawSha256']) or
        not isinstance(record.get('rawBase64'), str) or not isinstance(record.get('retrievedAt'), str)):
        raise ValueError('closure receipt metadata invalid')
    try:
        timestamp = datetime.fromisoformat(record['retrievedAt'].replace('Z', '+00:00'))
        raw = base64.b64decode(record['rawBase64'], validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('closure receipt encoding invalid') from exc
    if (timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0) or len(raw) != record['rawBytes'] or
        _digest(raw) != record['rawSha256']):
        raise ValueError('closure receipt hash or time mismatch')
    return raw


def _canonical_detail_url(link: str) -> str:
    if not isinstance(link, str):
        raise ValueError('closure detail link invalid')
    if link.startswith('/'):
        path = link
    else:
        parts = urlsplit(link)
        if (parts.scheme != 'https' or parts.netloc != 'www.twse.com.tw' or parts.query or parts.fragment or
            parts.username or parts.password or parts.port not in (None, 443)):
            raise ValueError('closure detail origin invalid')
        path = parts.path
    if not DETAIL_PATH_RE.fullmatch(path):
        raise ValueError('closure detail path invalid')
    return DETAIL_PREFIX + path.rsplit('/', 1)[1]


def _candidates(feed_raw: bytes, target: date | None) -> list[dict]:
    if not isinstance(feed_raw, bytes) or not 0 < len(feed_raw) <= FEED_LIMIT:
        raise ValueError('closure feed size invalid')
    if b'<!DOCTYPE' in feed_raw.upper() or b'<!ENTITY' in feed_raw.upper():
        raise ValueError('closure feed XML declarations are not allowed')
    try:
        root = ET.fromstring(feed_raw)
    except ET.ParseError as exc:
        raise ValueError('closure feed XML invalid') from exc
    if root.tag.rsplit('}', 1)[-1] != 'rss' or not any(child.tag.rsplit('}', 1)[-1] == 'channel' for child in root):
        raise ValueError('closure feed is not an RSS channel')
    minimum = target - timedelta(days=60) if target is not None else None
    candidates = []
    for item in root.iter('item'):
        values = {child.tag: (child.text or '').strip() for child in item}
        title = values.get('title', '')
        match = TITLE_RE.fullmatch(title)
        if not match:
            continue
        year = int(match['year']) + 1911
        day = date(year, int(match['month']), int(match['day']))
        if target is not None and not minimum <= day <= target:
            continue
        body = values.get(CONTENT_TAG, '')
        if '集中交易市場全日休市' not in body or '全體公教機關停止上班' not in body:
            raise ValueError('closure notice is not explicit full-day evidence')
        link = _canonical_detail_url(values.get('link', ''))
        if values.get('guid', '') != urlsplit(link).path:
            raise ValueError('closure feed link and guid mismatch')
        try:
            published = parsedate_to_datetime(values['pubDate'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('closure feed publication time invalid') from exc
        if published.tzinfo is None:
            raise ValueError('closure feed publication timezone missing')
        candidates.append({'date': day.isoformat(), 'title': title, 'detailUrl': link,
                           'rssPublishedAt': published.astimezone(timezone.utc).isoformat()})
    return candidates


def _validate_detail(raw: bytes, candidate: dict) -> None:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= DETAIL_LIMIT:
        raise ValueError('closure detail size invalid')
    try:
        detail = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('closure detail JSON invalid') from exc
    if (type(detail) is not dict or detail.get('stat') != 'ok' or
        not re.fullmatch(r'\d{12}', str(detail.get('date', '')))):
        raise ValueError('closure detail metadata invalid')
    published = datetime.strptime(detail['date'], '%Y%m%d%H%M').replace(tzinfo=timezone(timedelta(hours=8)))
    rss_published = datetime.fromisoformat(candidate['rssPublishedAt'].replace('Z', '+00:00'))
    if published.date() != rss_published.astimezone(timezone(timedelta(hours=8))).date():
        raise ValueError('closure detail publication date mismatch')
    tables = detail.get('tables')
    matches = [table for table in tables if type(table) is dict and table.get('title') == candidate['title']] if type(tables) is list else []
    if len(matches) != 1:
        raise ValueError('closure detail title mismatch')
    table = matches[0]
    fields, data = table.get('fields'), table.get('data')
    if fields != ['text', 'html', 'pdf', 'lang'] or type(data) is not list:
        raise ValueError('closure detail lacks official notice document')
    row = data[0] if len(data) == 1 and type(data[0]) is list else data
    if len(row) < 3 or not PDF_PATH_RE.fullmatch(row[2] if isinstance(row[2], str) else ''):
        raise ValueError('closure detail lacks official notice document')


def build_closure_evidence(feed_raw: bytes, fetch_detail, *, target: date, retrieved_at: str) -> dict:
    """Capture RSS and matching same-origin detail JSON for recent full-day notices."""
    feed_record = _raw_record(feed_raw, FEED_URL, retrieved_at, FEED_LIMIT)
    candidates = _candidates(feed_raw, target)
    if len(candidates) > MAX_NOTICES:
        raise ValueError('closure notice count exceeds bounded contract')
    notices = []
    for candidate in candidates:
        raw = fetch_detail(candidate['detailUrl'])
        _validate_detail(raw, candidate)
        notices.append({**candidate, 'detail': _raw_record(raw, candidate['detailUrl'], retrieved_at, DETAIL_LIMIT)})
    evidence = {'schemaVersion': 'twse-full-day-closure-v1', 'feed': feed_record, 'notices': notices}
    verify_closure_evidence(evidence)
    return evidence


def verify_closure_evidence(evidence: object) -> list[dict]:
    if type(evidence) is not dict or evidence.get('schemaVersion') != 'twse-full-day-closure-v1' or type(evidence.get('notices')) is not list:
        raise ValueError('closure evidence schema invalid')
    feed_raw = _decode_record(evidence.get('feed'), url=FEED_URL, limit=FEED_LIMIT)
    feed_candidates = _candidates(feed_raw, None)
    candidates_by_url = {item['detailUrl']: item for item in feed_candidates}
    verified = []
    seen = set()
    for notice in evidence['notices']:
        if type(notice) is not dict or notice.get('detailUrl') not in candidates_by_url:
            raise ValueError('closure notice is absent from feed proof')
        candidate = candidates_by_url[notice['detailUrl']]
        if (notice.get('date') != candidate['date'] or notice.get('title') != candidate['title'] or
            notice.get('rssPublishedAt') != candidate['rssPublishedAt'] or candidate['date'] in seen):
            raise ValueError('closure notice does not match feed proof')
        detail_raw = _decode_record(notice.get('detail'), url=candidate['detailUrl'], limit=DETAIL_LIMIT)
        _validate_detail(detail_raw, candidate)
        seen.add(candidate['date'])
        verified.append({'date': candidate['date'], 'market': 'TWSE', 'scope': 'centralized_full_day',
                         'title': candidate['title'], 'detailUrl': candidate['detailUrl'],
                         'detailSha256': _digest(detail_raw)})
    return verified


def merge_closure_evidence(*evidence_groups: list[dict]) -> list[dict]:
    """Keep verified notices across feed rotation, preferring the newest proof."""
    chosen = {}
    for group in evidence_groups:
        for evidence in group:
            dates = {item['date'] for item in verify_closure_evidence(evidence)}
            for day in dates:
                chosen[day] = evidence
    result = []
    owners, seen = [], set()
    for owner in chosen.values():
        if id(owner) not in seen:
            seen.add(id(owner))
            owners.append(owner)
    for source in owners:
        selected = {day for day, owner in chosen.items() if owner is source}
        copied = {**source, 'notices': [notice for notice in source['notices'] if notice['date'] in selected]}
        verify_closure_evidence(copied)
        result.append(copied)
    return result


def validate_closure_evidence_size(receipts: list[dict]) -> None:
    """Bound nested evidence so existing four-megabyte calendar receipts fit."""
    total = 0
    for receipt in receipts:
        if type(receipt) is not dict:
            raise ValueError('closure evidence receipt metadata invalid')
        evidence = receipt.get('closureEvidence', [])
        if type(evidence) is not list:
            raise ValueError('closure evidence receipt metadata invalid')
        for item in evidence:
            try:
                total += len(json.dumps(item, ensure_ascii=False, sort_keys=True,
                                        separators=(',', ':'), allow_nan=False).encode('utf-8'))
            except (TypeError, ValueError) as exc:
                raise ValueError('closure evidence receipt metadata invalid') from exc
            if total > MAX_CLOSURE_EVIDENCE_BYTES:
                raise ValueError('closure evidence bundle exceeds size limit')


def closure_evidence_for_year(evidence: dict, year: int) -> dict | None:
    """Return a verified receipt view containing notices for one calendar year."""
    verify_closure_evidence(evidence)
    notices = [item for item in evidence['notices'] if date.fromisoformat(item['date']).year == year]
    if not notices:
        return None
    result = {**evidence, 'notices': notices}
    verify_closure_evidence(result)
    return result


def apply_verified_closures(calendar: dict, evidence: object) -> dict:
    """Return a new calendar with only source-verified full-day closures merged."""
    closures = verify_closure_evidence(evidence)
    if not closures:
        return dict(calendar)
    result = dict(calendar)
    closed = set(calendar.get('closedDates', []))
    opened = set(calendar.get('openExceptions', []))
    for item in closures:
        day = item['date']
        if date.fromisoformat(day).year != calendar.get('year') or day in opened:
            raise ValueError('closure evidence conflicts with annual calendar')
        closed.add(day)
    result['closedDates'] = sorted(closed)
    return result
