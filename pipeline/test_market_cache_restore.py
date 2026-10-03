"""Restore exact public cache bytes with independently supplied trust context."""
import base64
import copy
import gzip
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.market_cache import canonical, sha, build_market_cache, MarketCacheError
from pipeline.source_receipts import capture_raw, write_bundle
from pipeline.trading_calendar import SOURCE_URL, build_calendar
from pipeline.market_indicators import TWSE_STOCK_DAY
from scripts.test_build_market_cache_index import setup_inputs
from scripts.build_market_cache_index import write_institutional_cache, assemble_index


def restore_fixture(tmp_path):
    snapshots, kwargs = setup_inputs(tmp_path)
    directory = kwargs['source_cache_dir']
    for path in directory.glob('institutional-*-validated.json'):
        value = json.loads(path.read_bytes())
        value.update(retrievedAt='2026-10-03T00:00:00Z', status='complete',
                     encoding='MS950' if value['market'] == 'TPEx' else 'utf-8')
        path.write_bytes(canonical(value))
    calendar_rows = [{'Name': '中華民國開國紀念日', 'Date': '1150101', 'Weekday': '四', 'Description': ''},
                     {'Name': '國曆新年開始交易日', 'Date': '1150102', 'Weekday': '五', 'Description': ''}]
    retrieved = '2026-10-03T00:00:00Z'
    raw = canonical(calendar_rows)
    receipt = capture_raw(directory, prefix='calendar-2026', raw=raw, source_url=SOURCE_URL,
                          unit='calendar', request_period={'requestYear': 2026}, retrieved_at=retrieved)
    calendar = build_calendar(calendar_rows, year=2026, fetched_at=retrieved)
    write_bundle(directory, prefix='calendar', receipts=[receipt], normalized=calendar,
                 group={'kind': 'calendar', 'market': 'TWSE', 'codes': [], 'dates': ['2026-10-02'],
                        'unit': 'calendar', 'sourceUrl': SOURCE_URL})
    days = sorted(snapshot['date'] for snapshot in snapshots)[-7:]
    receipts = []
    for month in ['2026-09', '2026-10']:
        dates = [day for day in days if day.startswith(month)]
        raw = canonical({'stat': 'OK', 'date': month.replace('-', '') + '01', 'fields': ['日期', '成交股數'],
                         'data': [[f'{int(day[:4])-1911}/{day[5:7]}/{day[8:]}', '10'] for day in dates]})
        url = TWSE_STOCK_DAY + '?response=json&date=' + month.replace('-', '') + '01&stockNo=00631L'
        receipt = capture_raw(directory, prefix='stock-day-' + month, raw=raw, source_url=url,
                              unit='shares', request_period={'requestMonth': month}, retrieved_at=retrieved)
        receipts.append(receipt)
    write_bundle(directory, prefix='volume', receipts=receipts,
                 normalized={'rows': [{'marketDate': day, 'code': '00631L', 'volume': 10, 'unit': 'shares'} for day in days]},
                 group={'kind': 'volume', 'market': 'TWSE', 'codes': ['00631L'], 'dates': days,
                        'unit': 'shares', 'sourceUrl': TWSE_STOCK_DAY})
    write_institutional_cache(snapshots, directory)
    payload, expected = assemble_index(**kwargs)
    built = build_market_cache(payload, expected)
    backup = tmp_path / 'backup'; backup.mkdir()
    files = {**built['files'], 'manifest.json': canonical(built['manifest']),
             'proof.json': canonical(built['proof']), 'expected.json': canonical(expected)}
    for name, raw in files.items(): (backup / name).write_bytes(raw)
    descriptor = {'schemaVersion': 'market-cache-restore-v1', 'repository': 'pingpongtech-uskg/stock-web-pages',
                  'marketDate': payload['marketDate'], 'source': payload['source'],
                  'manifestHash': built['manifest']['manifestHash'],
                  'files': [{'name': name, 'sha256': sha(raw), 'bytes': len(raw)} for name, raw in sorted(files.items())]}
    raw = canonical(descriptor); (backup / 'restore.json').write_bytes(raw)
    trust = {'descriptor_sha256': sha(raw), 'market_date': payload['marketDate'], 'source': payload['source']}
    return backup, trust, built, expected


def test_restore_replays_all_eleven_sessions_without_http_and_retains_financial_evidence(tmp_path):
    from pipeline.market_cache_restore import restore_market_cache
    from pipeline.official_institutional import fetch_complete_day
    from pipeline.market_indicators import compute_volume_multiple
    backup, trust, built, expected = restore_fixture(tmp_path)
    cache = tmp_path / 'cache'
    proof = restore_market_cache(backup, source_cache_dir=cache, stock_cache_dir=tmp_path / 'stocks',
                                 target_market_date='2026-10-03', **trust)
    assert proof['restoreUsable'] is True and proof['sessionCount'] == 11
    with patch('pipeline.official_institutional.urllib.request.urlopen', side_effect=AssertionError('HTTP forbidden')):
        for day in expected['sessionDates']:
            assert len(fetch_complete_day(date.fromisoformat(day), source_cache_dir=cache, refresh=False)) == 2
    volumes = json.loads((cache / 'volume.normalized.json').read_bytes())['rows']
    indicator = compute_volume_multiple([{'date': row['marketDate'], 'volume': row['volume']} for row in volumes], as_of=date(2026, 10, 2))
    assert indicator['status'] == 'available' and indicator['multiple'] == 1
    details = sorted((tmp_path / 'stocks' / '2026-10-02').glob('[0-9][0-9][0-9][0-9].json'))
    assert len(details) == 100
    assert json.loads(details[0].read_bytes())['reason'] == 'preserve full evidence'


def test_bad_descriptor_and_future_cache_fail_before_any_write(tmp_path):
    from pipeline.market_cache_restore import restore_market_cache
    backup, trust, *_ = restore_fixture(tmp_path)
    for overrides in [{'descriptor_sha256': '0' * 64}, {'target_market_date': '2026-10-01'}]:
        values = {**trust, 'target_market_date': '2026-10-02', **overrides}
        with pytest.raises(MarketCacheError):
            restore_market_cache(backup, source_cache_dir=tmp_path / 'out', stock_cache_dir=tmp_path / 'stocks', **values)
        assert not (tmp_path / 'out').exists()


def test_shard_hash_failure_is_atomic(tmp_path):
    from pipeline.market_cache_restore import restore_market_cache
    backup, trust, *_ = restore_fixture(tmp_path)
    shard = next(backup.glob('*.gz')); shard.write_bytes(b'corrupt')
    with pytest.raises(MarketCacheError):
        restore_market_cache(backup, source_cache_dir=tmp_path / 'out', stock_cache_dir=tmp_path / 'stocks', target_market_date='2026-10-02', **trust)
    assert not (tmp_path / 'out').exists()


def resign(backup, trust):
    descriptor = json.loads((backup / 'restore.json').read_bytes())
    descriptor['files'] = [{'name': item['name'], 'sha256': sha((backup / item['name']).read_bytes()),
                            'bytes': (backup / item['name']).stat().st_size} for item in descriptor['files']]
    manifest = json.loads((backup / 'manifest.json').read_bytes())
    descriptor['manifestHash'] = manifest['manifestHash']
    raw = canonical(descriptor); (backup / 'restore.json').write_bytes(raw)
    return {**trust, 'descriptor_sha256': sha(raw)}


@pytest.mark.parametrize('mutation', ['duplicate', 'extra', 'traversal', 'source', 'size', 'unknown'])
def test_descriptor_boundary_rejects_malformed_authenticated_metadata(tmp_path, mutation):
    from pipeline.market_cache_restore import restore_market_cache
    backup, trust, *_ = restore_fixture(tmp_path)
    descriptor = json.loads((backup / 'restore.json').read_bytes())
    if mutation == 'duplicate': descriptor['files'].append(descriptor['files'][0])
    elif mutation == 'extra': (backup / 'surprise.json').write_bytes(b'{}')
    elif mutation == 'traversal': descriptor['files'][0]['name'] = '../secret'
    elif mutation == 'source': descriptor['source'] = {**descriptor['source'], 'actionsRunId': '456'}
    elif mutation == 'size': descriptor['files'][0]['bytes'] = 2**40
    else: descriptor['surprise'] = True
    raw = canonical(descriptor); (backup / 'restore.json').write_bytes(raw)
    trust = {**trust, 'descriptor_sha256': sha(raw)}
    with pytest.raises(MarketCacheError):
        restore_market_cache(backup, source_cache_dir=tmp_path / 'out', stock_cache_dir=tmp_path / 'stocks', target_market_date='2026-10-02', **trust)
    assert not (tmp_path / 'out').exists()


@pytest.mark.parametrize('mutation', ['proof', 'expected', 'manifest', 'symlink', 'concatenated', 'bomb'])
def test_authenticated_bytes_still_require_valid_proof_and_bounded_semantics(tmp_path, mutation):
    from pipeline.market_cache_restore import restore_market_cache
    backup, trust, *_ = restore_fixture(tmp_path)
    if mutation == 'proof':
        proof = json.loads((backup / 'proof.json').read_bytes()); proof['cacheComplete'] = False
        (backup / 'proof.json').write_bytes(canonical(proof))
    elif mutation == 'expected':
        expected = json.loads((backup / 'expected.json').read_bytes()); expected['sessionDates'].pop(0)
        (backup / 'expected.json').write_bytes(canonical(expected))
    elif mutation == 'manifest':
        manifest = json.loads((backup / 'manifest.json').read_bytes()); manifest['previousTradingDate'] = '2026-09-30'
        (backup / 'manifest.json').write_bytes(canonical(manifest))
    elif mutation == 'symlink':
        shard = next(backup.glob('*.gz')); sentinel = tmp_path / 'sentinel'; sentinel.write_bytes(shard.read_bytes())
        shard.unlink(); shard.symlink_to(sentinel)
    else:
        manifest = json.loads((backup / 'manifest.json').read_bytes()); part = manifest['groups'][0]['shards'][0]
        old_name = part['name']; raw = (backup / old_name).read_bytes()
        altered = raw + raw if mutation == 'concatenated' else gzip.compress(b'x' * (part['rawBytes'] + 1), mtime=0)
        part['gzipSha256'] = sha(altered); part['gzipBytes'] = len(altered)
        part['name'] = old_name.replace(old_name.split('.')[-4], part['gzipSha256']) if False else f"{manifest['marketDate']}.{manifest['groups'][0]['key'].replace(':','-')}.0.{sha(altered)}.json.gz"
        (backup / old_name).unlink(); (backup / part['name']).write_bytes(altered)
        descriptor = json.loads((backup / 'restore.json').read_bytes())
        descriptor['files'] = sorted([{**item, 'name': part['name']} if item['name'] == old_name else item for item in descriptor['files']], key=lambda item: item['name'])
        (backup / 'restore.json').write_bytes(canonical(descriptor))
        manifest['manifestHash'] = sha(canonical({key:value for key,value in manifest.items() if key != 'manifestHash'}))
        (backup / 'manifest.json').write_bytes(canonical(manifest))
    trust = resign(backup, trust)
    with pytest.raises(MarketCacheError):
        restore_market_cache(backup, source_cache_dir=tmp_path / 'out', stock_cache_dir=tmp_path / 'stocks', target_market_date='2026-10-02', **trust)
    assert not (tmp_path / 'out').exists()


def test_existing_receipts_idempotent_and_fresh_fragments_preserved(tmp_path):
    from pipeline.market_cache_restore import restore_market_cache
    backup, trust, *_ = restore_fixture(tmp_path)
    cache, stocks = tmp_path / 'cache', tmp_path / 'stocks'
    kwargs = dict(source_cache_dir=cache, stock_cache_dir=stocks, target_market_date='2026-10-03', **trust)
    restore_market_cache(backup, **kwargs)
    before = {path: path.read_bytes() for path in cache.glob('institutional-*.json')}
    fresh = b'{"fresh":true}'
    (cache / 'calendar-receipt-index.json').write_bytes(fresh)
    proof = restore_market_cache(backup, **kwargs)
    assert proof['restoreUsable'] and (cache / 'calendar-receipt-index.json').read_bytes() == fresh
    assert all(path.read_bytes() == raw for path, raw in before.items())


def test_conflicting_stock_or_output_symlink_rejected_before_source_install(tmp_path):
    from pipeline.market_cache_restore import restore_market_cache
    backup, trust, *_ = restore_fixture(tmp_path)
    stocks = tmp_path / 'stocks' / '2026-10-02'; stocks.mkdir(parents=True)
    (stocks / '1000.json').write_bytes(b'conflict')
    with pytest.raises(MarketCacheError):
        restore_market_cache(backup, source_cache_dir=tmp_path / 'out', stock_cache_dir=stocks.parent, target_market_date='2026-10-02', **trust)
    assert not (tmp_path / 'out').exists()
    outside = tmp_path / 'outside'; outside.mkdir()
    alias = tmp_path / 'alias'; alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MarketCacheError):
        restore_market_cache(backup, source_cache_dir=alias, stock_cache_dir=tmp_path / 'other', target_market_date='2026-10-02', **trust)
    assert list(outside.iterdir()) == []


def replace_semantics(backup, trust, mutation):
    from pipeline.market_cache import FIELDS
    manifest = json.loads((backup / 'manifest.json').read_bytes())
    expected = json.loads((backup / 'expected.json').read_bytes())
    groups = []
    for group in manifest['groups']:
        raw = b''.join(gzip.decompress((backup / part['name']).read_bytes()) for part in group['shards'])
        fields = FIELDS | ({'codesByDate'} if group['kind'].startswith('institutional') else set())
        groups.append({**{key:group[key] for key in fields}, 'body':raw if group['kind'].endswith('_raw') else json.loads(raw)})
    by_key = {group['key']:group for group in groups}
    if mutation == 'institutional_values':
        row = by_key['institutional_normalized:TWSE']['body']['rows'][0]
        row.update(buy=99, sell=0, net=99)
    elif mutation == 'institutional_raw_date':
        group=by_key['institutional_raw:TWSE']; bundle=json.loads(group['body']); receipt=bundle['receipts'][0]
        raw=json.loads(base64.b64decode(receipt['rawBase64'])); raw['date']='20261002'
        raw=canonical(raw); receipt.update(rawBase64=base64.b64encode(raw).decode(),rawSha256=sha(raw),rawBytes=len(raw))
        group['body']=canonical(bundle); group['sourceSha256']=sha(group['body'])
        normalized=by_key['institutional_normalized:TWSE']
        normalized.update(sourceSha256=group['sourceSha256'],normalizedFromSha256=group['sourceSha256'])
    elif mutation == 'calendar':
        by_key['calendar_normalized']['body']['closedDates'].append('2026-01-03')
    elif mutation == 'volume':
        by_key['volume_normalized']['body']['rows'][0]['volume']=0
    elif mutation == 'stock':
        by_key['published_stock_inputs']['body']['rows'][0]['metrics']['currentPrice']=999
    else:
        group=by_key['volume_raw'];bundle=json.loads(group['body']);bundle['receipts'][0]['sourceUrl']='https://example.org/incorrect'
        group['body']=canonical(bundle);group['sourceSha256']=sha(group['body'])
        by_key['volume_normalized'].update(sourceSha256=group['sourceSha256'],normalizedFromSha256=group['sourceSha256'])
    expected['groups']=[{key:value for key,value in group.items() if key!='body'} for group in groups]
    payload={key:manifest[key] for key in ['marketDate','previousTradingDate','source','generatedAt']};payload['groups']=groups
    built=build_market_cache(payload,expected)
    for path in backup.iterdir(): path.unlink()
    files={**built['files'],'manifest.json':canonical(built['manifest']),'proof.json':canonical(built['proof']),'expected.json':canonical(expected)}
    for name,raw in files.items(): (backup/name).write_bytes(raw)
    descriptor={'schemaVersion':'market-cache-restore-v1','repository':'pingpongtech-uskg/stock-web-pages','marketDate':trust['market_date'],
                'source':trust['source'],'manifestHash':built['manifest']['manifestHash'],
                'files':[{'name':name,'sha256':sha(raw),'bytes':len(raw)} for name,raw in sorted(files.items())]}
    raw=canonical(descriptor);(backup/'restore.json').write_bytes(raw)
    return {**trust,'descriptor_sha256':sha(raw)}


@pytest.mark.parametrize('mutation',['institutional_values','institutional_raw_date','calendar','volume','stock','volume_url'])
def test_correct_hashes_and_producer_proof_cannot_replace_source_semantic_validation(tmp_path, mutation):
    from pipeline.market_cache_restore import restore_market_cache
    backup, trust, *_ = restore_fixture(tmp_path)
    trust=replace_semantics(backup,trust,mutation)
    with pytest.raises(MarketCacheError):
        restore_market_cache(backup,source_cache_dir=tmp_path/'out',stock_cache_dir=tmp_path/'stocks',target_market_date='2026-10-02',**trust)
    assert not (tmp_path/'out').exists()


def test_existing_date_metadata_membership_cannot_bypass_revalidation(tmp_path):
    from pipeline.market_cache_restore import restore_market_cache
    backup,trust,*_=restore_fixture(tmp_path)
    cache=tmp_path/'out';stocks=tmp_path/'stocks'
    kwargs=dict(source_cache_dir=cache,stock_cache_dir=stocks,target_market_date='2026-10-02',**trust)
    restore_market_cache(backup,**kwargs)
    path=next(cache.glob('institutional-TWSE-*-validated.json'))
    value=json.loads(path.read_bytes());value['codes']=[];path.write_bytes(canonical(value))
    with pytest.raises(MarketCacheError):restore_market_cache(backup,**kwargs)
    assert json.loads(path.read_bytes())['codes']==[]


@pytest.mark.parametrize('competing', ['different', 'symlink'])
def test_restore_install_never_clobbers_competing_fresh_destination(tmp_path, monkeypatch, competing):
    from pipeline.market_cache_restore import restore_market_cache
    import os
    backup, trust, *_ = restore_fixture(tmp_path)
    cache = tmp_path / 'cache'; sentinel = tmp_path / 'sentinel'; sentinel.write_bytes(b'fresh collector')
    link, replace = os.link, os.replace
    injected = []
    def compete(install):
        def operation(source, destination, *args, **kwargs):
            destination = Path(destination)
            if not injected and destination.parent == cache and destination.name.endswith('.raw.json'):
                injected.append(destination)
                if competing == 'symlink': destination.symlink_to(sentinel)
                else: destination.write_bytes(b'fresh collector')
            return install(source, destination, *args, **kwargs)
        return operation
    monkeypatch.setattr(os, 'link', compete(link))
    monkeypatch.setattr(os, 'replace', compete(replace))
    with pytest.raises(MarketCacheError):
        restore_market_cache(backup,source_cache_dir=cache,stock_cache_dir=tmp_path/'stocks',target_market_date='2026-10-02',**trust)
    assert injected and injected[0].read_bytes() == b'fresh collector'
    assert sentinel.read_bytes() == b'fresh collector'
    assert not list(cache.glob('.restore-*'))


def test_missing_installer_equal_race_and_permission_failure_cleanup(tmp_path, monkeypatch):
    from pipeline.market_cache_restore import _install_missing
    import os
    original = os.link
    target = tmp_path / 'same.json'
    inodes = []
    def equal_race(source, destination, **kwargs):
        Path(destination).write_bytes(b'same')
        inodes.append(Path(destination).stat().st_ino)
        return original(source, destination, **kwargs)
    monkeypatch.setattr(os, 'link', equal_race)
    _install_missing(target, b'same')
    assert target.stat().st_ino == inodes[0]
    assert not list(tmp_path.glob('.restore-*'))
    def inaccessible(*args, **kwargs): raise PermissionError('sensitive path never logged')
    monkeypatch.setattr(os, 'link', inaccessible)
    with pytest.raises(PermissionError): _install_missing(tmp_path / 'denied.json', b'data')
    assert not (tmp_path / 'denied.json').exists()
    assert not list(tmp_path.glob('.restore-*'))
