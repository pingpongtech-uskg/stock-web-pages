"""Pure producer tests: authenticated expectations stay separate from bytes."""
import copy
import gzip
import hashlib
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    days = []
    current = date(2026, 10, 2)
    while len(days) < 11:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current -= timedelta(days=1)
    days.reverse()
    groups = []
    for kind, market, codes, dates, body, unit in [
        ('institutional', 'TWSE', ['1101'], days, {'rows': [{'marketDate': d, 'code': '1101', 'buy': 0, 'sell': 0, 'net': 0, 'unit': 'shares'} for d in days]}, 'shares'),
        ('institutional', 'TPEx', ['1102'], days, {'rows': [{'marketDate': d, 'code': '1102', 'buy': 2, 'sell': 1, 'net': 1, 'unit': 'shares'} for d in days]}, 'shares'),
        ('calendar', 'TWSE', [], ['2026-10-02'], {'schemaVersion': 'trading-calendar-v1', 'year': 2026, 'timezone': 'Asia/Taipei', 'closedDates': [], 'openExceptions': []}, 'calendar'),
        ('volume', 'TWSE', ['00631L'], days[-7:], {'rows': [{'marketDate': d, 'code': '00631L', 'volume': 0, 'unit': 'shares'} for d in days[-7:]]}, 'shares'),
    ]:
        raw = json.dumps(body, ensure_ascii=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        for form in ['raw', 'normalized']:
            role = f'{kind}_{form}'
            key = role + (f':{market}' if kind == 'institutional' else '')
            groups.append({'key': key, 'kind': role, 'market': market, 'codes': codes, 'dates': dates,
                           'unit': unit, 'sourceUrl': 'https://www.twse.com.tw/source?date=20261002',
                           'sourceSha256': digest, 'normalizedFromSha256': digest if form == 'normalized' else None,
                           'body': raw if form == 'raw' else body})
            if kind == 'institutional':
                groups[-1]['codesByDate'] = {day: list(codes) for day in dates}
    groups.append({'key': 'published_stock_inputs', 'kind': 'published_stock_inputs', 'market': 'ALL',
                   'codes': ['1101'], 'dates': ['2026-10-02'], 'unit': 'mixed',
                   'sourceUrl': 'https://example.org/public/data/stocks', 'sourceSha256': 'a' * 64,
                   'normalizedFromSha256': None,
                   'body': {'rows': [{'marketDate': '2026-10-02', 'code': '1101', 'metrics': {'eps': None, 'dividend': 0}}]}})
    header = {'marketDate': '2026-10-02', 'previousTradingDate': '2026-10-01', 'generatedAt': '2026-10-03T00:00:00Z',
              'source': {'requestId': 'fixture', 'actionsRunId': '123', 'sourceGitCommit': 'a' * 40}}
    expected = {**header, 'groups': [{k: copy.deepcopy(v) for k, v in g.items() if k != 'body'} for g in groups],
                'sessionDates': days, 'volumeDates': days[-7:], 'metricKeys': ['dividend', 'eps'], 'calendarYear': 2026}
    return {**header, 'groups': groups}, expected


def test_producer_matches_real_js_verifier_and_preserves_null_zero(tmp_path):
    from pipeline.market_cache import build_market_cache
    payload, expected = fixture()
    original = copy.deepcopy(payload)
    result = build_market_cache(payload, expected)
    assert payload == original
    assert result['proof']['cacheComplete'] is True
    assert result['proof']['metricsComplete'] is False
    assert result['proof']['metricCoverage']['dividend'] == {'known': 1, 'missing': 0, 'zero': 1}
    assert result['proof']['metricCoverage']['eps'] == {'known': 0, 'missing': 1, 'zero': 0}
    expected = {**expected, 'manifestHash': result['manifest']['manifestHash']}
    (tmp_path / 'manifest.json').write_text(json.dumps(result['manifest']))
    (tmp_path / 'expected.json').write_text(json.dumps(expected))
    for name, content in result['files'].items():
        (tmp_path / name).write_bytes(content)
    script = "const fs=require('fs'); const c=require(process.argv[1]); const p=process.argv[2]; const m=JSON.parse(fs.readFileSync(p+'/manifest.json')); const e=JSON.parse(fs.readFileSync(p+'/expected.json')); const files=Object.fromEntries(fs.readdirSync(p).filter(n=>n.endsWith('.gz')).map(n=>[n,fs.readFileSync(p+'/'+n)])); console.log(JSON.stringify(c.verifyMarketCache(m,files,e)));"
    proof = json.loads(subprocess.check_output(['node', '-e', script, str(ROOT / 'scripts/n8n/market-cache.cjs'), str(tmp_path)]))
    assert proof == {key: result['proof'][key] for key in proof}


def test_producer_proof_binds_semantics_to_exact_run_and_dates():
    from pipeline.market_cache import build_market_cache
    payload, expected = fixture()
    proof = build_market_cache(payload, expected)['proof']
    assert proof['schemaVersion'] == 'market-cache-producer-proof-v1'
    assert proof['semanticValidation'] == 'bounded-python-v1'
    assert proof['marketDate'] == payload['marketDate']
    assert proof['previousTradingDate'] == payload['previousTradingDate']
    assert proof['source'] == payload['source']


def test_shards_reassemble_opaque_receipts_deterministically():
    from pipeline.market_cache import build_market_cache
    payload, expected = fixture()
    a = build_market_cache(payload, expected, max_raw_bytes=40, max_compressed_bytes=128)
    b = build_market_cache(payload, expected, max_raw_bytes=40, max_compressed_bytes=128)
    assert a == b
    for group, source in zip(a['manifest']['groups'], payload['groups']):
        chunks = [gzip.decompress(a['files'][p['name']]) for p in group['shards']]
        assert all(len(chunk) <= 40 for chunk in chunks)
        if source['kind'].endswith('_raw'):
            assert b''.join(chunks) == source['body']


@pytest.mark.parametrize('change', ['trusted_codes', 'missing_row', 'duplicate_row', 'negative_buy', 'wrong_net', 'raw_hash', 'missing_role', 'short_window', 'missing_volume_date', 'future_date', 'secret', 'url_auth', 'url_token', 'bool_metric', 'nan_metric', 'wrong_metric_keys', 'holiday', 'unknown_header'])
def test_invalid_or_untrusted_cache_never_builds(change):
    from pipeline.market_cache import build_market_cache, MarketCacheError
    payload, expected = fixture()
    if change == 'trusted_codes': expected['groups'][0]['codes'] = ['9999']
    elif change == 'missing_row': payload['groups'][1]['body']['rows'].pop()
    elif change == 'duplicate_row': payload['groups'][1]['body']['rows'][-1] = payload['groups'][1]['body']['rows'][0]
    elif change == 'negative_buy': payload['groups'][1]['body']['rows'][0]['buy'] = -1
    elif change == 'wrong_net': payload['groups'][1]['body']['rows'][0]['net'] = 1
    elif change == 'raw_hash': payload['groups'][0]['body'] += b' '
    elif change == 'missing_role': payload['groups'].pop()
    elif change == 'short_window': expected['sessionDates'] = expected['sessionDates'][1:]
    elif change == 'missing_volume_date': expected['volumeDates'] = expected['volumeDates'][-6:]
    elif change == 'future_date': payload['marketDate'] = '2026-10-03'
    elif change == 'secret': payload['groups'][-1]['body']['token'] = 'fixture'
    elif change == 'url_auth': payload['groups'][0]['sourceUrl'] = 'https://user:password@example.org/source'
    elif change == 'url_token': payload['groups'][0]['sourceUrl'] = 'https://example.org/source?%74oken=fixture'
    elif change == 'bool_metric': payload['groups'][-1]['body']['rows'][0]['metrics']['eps'] = True
    elif change == 'nan_metric': payload['groups'][-1]['body']['rows'][0]['metrics']['eps'] = float('nan')
    elif change == 'wrong_metric_keys': payload['groups'][-1]['body']['rows'][0]['metrics']['other'] = None
    elif change == 'holiday': payload['groups'][5]['body']['closedDates'] = ['2026-10-02']
    elif change == 'unknown_header': payload['token'] = 'fixture'
    with pytest.raises(MarketCacheError): build_market_cache(payload, expected)


def test_compressed_limit_splits_incompressible_raw_receipt():
    import os
    from pipeline.market_cache import build_market_cache, MAX_GZIP
    payload, expected = fixture()
    raw = os.urandom(MAX_GZIP + 1)
    digest = hashlib.sha256(raw).hexdigest()
    payload['groups'][0]['body'] = raw
    for index in [0, 1]:
        for group in [payload['groups'][index], expected['groups'][index]]:
            group['sourceSha256'] = digest
            if index == 1: group['normalizedFromSha256'] = digest
    result = build_market_cache(payload, expected)
    parts = result['manifest']['groups'][0]['shards']
    assert len(parts) == 2 and all(part['gzipBytes'] <= MAX_GZIP for part in parts)
    assert b''.join(gzip.decompress(result['files'][part['name']]) for part in parts) == raw


@pytest.mark.parametrize('change', ['unit_list', 'expected_kind_list', 'expected_group_missing_field', 'calendar_bad_year', 'calendar_bool_year', 'bad_source_type', 'bad_timestamp', 'oversized_integer', 'bad_limits'])
def test_malformed_types_fail_as_sanitized_contract_error(change):
    from pipeline.market_cache import build_market_cache, MarketCacheError
    payload, expected = fixture()
    kwargs = {}
    if change == 'unit_list':
        payload['groups'][0]['unit'] = []; expected['groups'][0]['unit'] = []
    elif change == 'expected_kind_list': expected['groups'][0]['kind'] = []
    elif change == 'expected_group_missing_field': del expected['groups'][0]['kind']
    elif change == 'calendar_bad_year': expected['calendarYear'] = None; payload['groups'][5]['body']['year'] = None
    elif change == 'calendar_bool_year': expected['calendarYear'] = True; payload['groups'][5]['body']['year'] = True
    elif change == 'bad_source_type': payload['source'] = []
    elif change == 'bad_timestamp': payload['generatedAt'] = '2026-13-04T00:00:00Z'
    elif change == 'oversized_integer': payload['groups'][-1]['body']['rows'][0]['metrics']['eps'] = 10 ** 400
    elif change == 'bad_limits': kwargs['max_raw_bytes'] = True
    with pytest.raises(MarketCacheError): build_market_cache(payload, expected, **kwargs)


def changing_membership():
    payload, expected = fixture()
    dates = expected['sessionDates']
    by_date = {day: ['1101'] if day != dates[-1] else ['1103'] for day in dates}
    for group in [payload['groups'][0], payload['groups'][1], expected['groups'][0], expected['groups'][1]]:
        group['codes'] = ['1101', '1103']
        group['codesByDate'] = copy.deepcopy(by_date)
    payload['groups'][1]['body']['rows'][-1]['code'] = '1103'
    return payload, expected


def test_changing_institutional_membership_is_complete_without_fake_zeros():
    from pipeline.market_cache import build_market_cache
    payload, expected = changing_membership()
    assert build_market_cache(payload, expected)['proof']['cacheComplete']


@pytest.mark.parametrize('change', ['fake_zero', 'wrong_date', 'wrong_union', 'missing_roster'])
def test_per_date_institutional_membership_fails_closed(change):
    from pipeline.market_cache import build_market_cache, MarketCacheError
    payload, expected = changing_membership()
    if change == 'fake_zero': payload['groups'][1]['body']['rows'].append({'marketDate': '2026-10-02', 'code': '1101', 'buy': 0, 'sell': 0, 'net': 0, 'unit': 'shares'})
    elif change == 'wrong_date': payload['groups'][1]['body']['rows'][-1]['code'] = '1101'
    elif change == 'wrong_union':
        for group in [payload['groups'][0], expected['groups'][0]]: group['codes'] = ['1101']
    elif change == 'missing_roster':
        for group in [payload['groups'][0], expected['groups'][0]]: del group['codesByDate']['2026-10-02']
    with pytest.raises(MarketCacheError): build_market_cache(payload, expected)


def test_part_limit_rejects_before_materializing_unbounded_split(monkeypatch):
    from pipeline import market_cache as producer
    payload, expected = fixture()
    calls = []
    original = producer.gzip.compress
    def compress(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(producer.gzip, 'compress', compress)
    with pytest.raises(producer.MarketCacheError): producer.build_market_cache(payload, expected, max_raw_bytes=1)
    assert len(calls) <= producer.MAX_PARTS + 1


def test_aggregate_raw_limit_is_checked_before_second_compression(monkeypatch):
    from pipeline import market_cache as producer
    payload, expected = fixture()
    monkeypatch.setattr(producer, 'MAX_TOTAL_RAW', len(payload['groups'][0]['body']) + 1)
    with pytest.raises(producer.MarketCacheError): producer.build_market_cache(payload, expected)


@pytest.mark.parametrize('change', ['missing_kind', 'list_kind'])
def test_payload_kind_is_validated_before_dynamic_membership_schema(change):
    from pipeline.market_cache import build_market_cache, MarketCacheError
    payload, expected = fixture()
    if change == 'missing_kind': del payload['groups'][0]['kind']
    else: payload['groups'][0]['kind'] = []
    with pytest.raises(MarketCacheError): build_market_cache(payload, expected)
