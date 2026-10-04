"""Assembler binds authenticated publication identity to complete source receipts."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest

from pipeline.test_market_cache import fixture
from pipeline.test_screening_export import release
from pipeline.screening_export import build_export, export_bytes
from pipeline.test_official_institutional import _tpex_csv
from pipeline.official_institutional import TWSE_ENDPOINT, TPEX_ENDPOINT
from datetime import date
from urllib.parse import urlencode


def setup_inputs(tmp_path):
    payload, expected = fixture()
    source = tmp_path / 'source'; source.mkdir()
    for family in ['calendar', 'volume']:
        groups = []
        for group in payload['groups']:
            if not group['kind'].startswith(family): continue
            body = group['body']; name = group['kind'] + '.json'
            (source / name).write_bytes(body if isinstance(body, bytes) else json.dumps(body).encode())
            groups.append({**{k: v for k, v in group.items() if k != 'body'}, 'bodyFile': name})
        (source / f'{family}-receipt-index.json').write_text(json.dumps({'groups': groups}))
    snapshots = []
    for day in reversed(expected['sessionDates']):
        rows = []
        for market, code in [('TWSE', '1101'), ('TPEx', '1102' if day != expected['sessionDates'][-1] else '1103')]:
            parsed_day = date.fromisoformat(day)
            raw = (json.dumps({'stat': 'OK', 'date': day.replace('-', ''),
                              'fields': ['證券代號', '證券名稱', '買進股數', '賣出股數', '買賣超股數'],
                              'data': [[code, 'fixture', '0', '0', '0']]}).encode()
                   if market == 'TWSE' else _tpex_csv(code, 'fixture', '0', '0', '0',
                       report_date=f'{parsed_day.year-1911}年{parsed_day.month:02d}月{parsed_day.day:02d}日'))
            raw_name = f'{market}-{day}.raw.json'
            (source / raw_name).write_bytes(raw)
            metadata = {'market': market, 'reportedDate': day, 'requestDate': day, 'validated': True,
                        'codes': [code], 'unit': 'shares', 'sourceUrl': TWSE_ENDPOINT if market == 'TWSE' else TPEX_ENDPOINT+'?'+urlencode({'type':'Daily','sect':'AL','date':parsed_day.strftime('%Y/%m/%d'),'response':'csv'}),
                        'encoding': 'utf-8', 'rawFile': raw_name, 'rawSha256': hashlib.sha256(raw).hexdigest(), 'rawBytes': len(raw)}
            (source / f'institutional-{market}-{day}-validated.json').write_text(json.dumps(metadata))
            rows.append({'market': market, 'code': code, 'name': 'fixture', 'buyShares': 0, 'sellShares': 0, 'netShares': 0})
        snapshots.append({'date': day, 'rows': rows})
    data = tmp_path / 'public'; stock_dir = data / 'releases/run-1/stocks'; stock_dir.mkdir(parents=True)
    value = release(); codes = [str(1000 + index) for index in range(100)]
    value['stocks'] = [{'code': code, 'lastPrice': 100} for code in codes]
    value['rankings'] = {'trust': [], 'growth': [], 'lowPosition': []}
    raw = json.dumps(value).encode(); (data / 'latest.json').write_bytes(raw)
    (data / 'publication.json').write_text(json.dumps({'contentHash': hashlib.sha256(raw).hexdigest(), 'marketDate': value['marketDate'], 'runId': value['runId']}))
    export = build_export(value, request_id='fixture', source_git_commit='a'*40, actions_run_id='123')
    (data / 'screening-export.json').write_bytes(export_bytes(export))
    for code in codes:
        (stock_dir / f'{code}.json').write_text(json.dumps({'code': code, 'asOf': '2026-10-02', 'lastPrice': 100, 'healthInputs': {}, 'reason': 'preserve full evidence'}))
    config = tmp_path / 'tracked.json'; config.write_text(json.dumps({'symbols': codes}))
    kwargs = {'data_dir': data, 'config': config, 'source_cache_dir': source, 'market_date': '2026-10-02',
              'request_id': 'fixture', 'source_git_commit': 'a'*40, 'actions_run_id': '123',
              'publication_sha256': hashlib.sha256(raw).hexdigest(), 'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
              'export_payload_hash': export['payloadHash']}
    return snapshots, kwargs


def test_full_market_index_keeps_per_date_membership_and_all_stock_evidence(tmp_path):
    from scripts.build_market_cache_index import write_institutional_cache, assemble_index
    from pipeline.market_cache import build_market_cache
    snapshots, kwargs = setup_inputs(tmp_path)
    write_institutional_cache(snapshots, kwargs['source_cache_dir'])
    payload, expected = assemble_index(**kwargs)
    result = build_market_cache(payload, expected)
    assert result['proof']['cacheComplete'] and not result['proof']['metricsComplete']
    tpex = next(g for g in payload['groups'] if g['key'] == 'institutional_normalized:TPEx')
    assert tpex['codes'] == ['1102', '1103'] and tpex['codesByDate']['2026-10-02'] == ['1103']
    stocks = payload['groups'][-1]['body']['rows']
    assert len(stocks) == 100 and stocks[0]['evidence']['reason'] == 'preserve full evidence'
    assert stocks[0]['metrics']['cashDividend2025'] is None


@pytest.mark.parametrize('change', ['wrong_publication', 'wrong_config', 'wrong_export', 'wrong_lineage', 'stale_detail', 'missing_detail', 'extra_detail', 'raw_tamper', 'roster_tamper', 'missing_date'])
def test_assembler_rejects_wrong_identity_or_incomplete_sources(tmp_path, change):
    from scripts.build_market_cache_index import write_institutional_cache, assemble_index
    from pipeline.market_cache import MarketCacheError
    snapshots, kwargs = setup_inputs(tmp_path)
    if change == 'raw_tamper': (kwargs['source_cache_dir'] / 'TWSE-2026-10-02.raw.json').write_bytes(b'tampered')
    elif change == 'roster_tamper': snapshots[0]['rows'][0]['code'] = '9999'
    elif change == 'missing_date': snapshots.pop()
    if change in {'raw_tamper', 'roster_tamper', 'missing_date'}:
        with pytest.raises(MarketCacheError): write_institutional_cache(snapshots, kwargs['source_cache_dir'])
        return
    write_institutional_cache(snapshots, kwargs['source_cache_dir'])
    stocks = kwargs['data_dir'] / 'releases/run-1/stocks'
    if change == 'wrong_publication': kwargs['publication_sha256'] = 'b'*64
    elif change == 'wrong_config': kwargs['config_sha256'] = 'b'*64
    elif change == 'wrong_export': kwargs['export_payload_hash'] = 'b'*64
    elif change == 'wrong_lineage': kwargs['request_id'] = 'different'
    elif change == 'stale_detail':
        path = stocks / '1000.json'; row = json.loads(path.read_text()); row['asOf'] = '2026-10-01'; path.write_text(json.dumps(row))
    elif change == 'missing_detail': (stocks / '1000.json').unlink()
    elif change == 'extra_detail': (stocks / '9999.json').write_text('{}')
    with pytest.raises(MarketCacheError): assemble_index(**kwargs)


def test_cli_creates_immutable_local_inputs_then_real_cache_export(tmp_path, capsys):
    from scripts.build_market_cache_index import write_institutional_cache, main
    from scripts.export_market_cache import main as export_main
    snapshots, kwargs = setup_inputs(tmp_path)
    write_institutional_cache(snapshots, kwargs['source_cache_dir'])
    destination = tmp_path / 'index'
    argv = [arg for key, value in kwargs.items() for arg in ['--' + key.replace('_', '-'), str(value)]] + ['--output', str(destination)]
    assert main(argv) == 0
    assert not (destination / 'manifest.json').exists()
    assert export_main(['--input', str(destination / 'input.json'), '--expected', str(destination / 'expected.json'), '--output', str(tmp_path / 'artifact')]) == 0
    manifest = json.loads((tmp_path / 'artifact/manifest.json').read_text())
    assert len(manifest['groups']) == 9
    assert main(argv) == 1
    assert 'market_cache_index_failed=cache_output_exists' in capsys.readouterr().err


def test_complete_explicit_zero_dividend_stays_known_and_future_data_unknown():
    from scripts.build_market_cache_index import stock_metrics
    detail = {'code': '1101', 'asOf': '2026-10-02', 'lastPrice': 100, 'healthInputs': {
        'dividends': [{'year': 2025, 'period': 'annual', 'confirmed': True, 'cashPerShare': 0, 'availableAt': '2026-06-01'}],
        'monthlyRevenueOfficial': [{'month': f'{year}-{month:02d}', 'revenue': 120 if year == 2026 else 100,
                                   'publishedAt': '2026-10-10' if year == 2026 else '2025-10-10'}
                                  for year in [2025, 2026] for month in [7, 8, 9]]}}
    metrics = stock_metrics(detail, '2026-10-02')
    assert metrics['cashDividend2025'] == 0
    assert all(metrics[f'revenueYoY{n}'] is None for n in [1, 2, 3])


def test_fragment_raw_aggregate_rejected_before_loading_bodies(tmp_path, monkeypatch):
    from scripts import build_market_cache_index as assembler
    snapshots, kwargs = setup_inputs(tmp_path)
    assembler.write_institutional_cache(snapshots, kwargs['source_cache_dir'])
    monkeypatch.setattr(assembler, 'MAX_TOTAL_RAW', 100_000)
    (kwargs['source_cache_dir'] / 'calendar_raw.json').write_bytes(b' ' * 100_001)
    calls = []
    monkeypatch.setattr(assembler, 'load_inputs', lambda *a, **kw: calls.append(1) or pytest.fail('unbounded load'))
    with pytest.raises(assembler.MarketCacheError): assembler.assemble_index(**kwargs)
    assert not calls


def test_calendar_independently_rejects_an_eleven_date_window_skipping_open_session(tmp_path):
    from scripts.build_market_cache_index import write_institutional_cache, assemble_index
    from pipeline.market_cache import MarketCacheError
    snapshots, kwargs = setup_inputs(tmp_path)
    write_institutional_cache(snapshots, kwargs['source_cache_dir'])
    calendar_file = kwargs['source_cache_dir'] / 'calendar_normalized.json'
    calendar = json.loads(calendar_file.read_text())
    # Previously omitted Friday would make the supplied first session too old.
    calendar['openExceptions'] = ['2026-09-19']
    calendar_file.write_text(json.dumps(calendar))
    with pytest.raises(MarketCacheError): assemble_index(**kwargs)


def test_assembler_accepts_official_calendar_set_for_cross_year_capable_sources(tmp_path):
    from pipeline.market_cache import canonical, sha
    from pipeline.trading_calendar import compose_calendar_set
    from scripts.build_market_cache_index import write_institutional_cache, assemble_index

    snapshots, kwargs = setup_inputs(tmp_path)
    source = kwargs['source_cache_dir']
    write_institutional_cache(snapshots, source)
    index_path = source / 'calendar-receipt-index.json'
    fragment = json.loads(index_path.read_bytes())
    raw_group = next(group for group in fragment['groups'] if group['kind'] == 'calendar_raw')
    normalized_group = next(group for group in fragment['groups'] if group['kind'] == 'calendar_normalized')
    current = {'schemaVersion': 'trading-calendar-v1', 'timezone': 'Asia/Taipei', 'year': 2026,
               'closedDates': [], 'openExceptions': [],
               'sourceUrl': 'https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule'}
    prior = {**current, 'year': 2025}
    composite = compose_calendar_set([prior, current])
    raw = canonical({'receipts': [{'requestYear': 2025}, {'requestYear': 2026}]})
    normalized = canonical(composite)
    (source / raw_group['bodyFile']).write_bytes(raw)
    (source / normalized_group['bodyFile']).write_bytes(normalized)
    digest = sha(raw)
    raw_group['sourceSha256'] = digest
    normalized_group['sourceSha256'] = digest
    normalized_group['normalizedFromSha256'] = digest
    index_path.write_bytes(canonical(fragment))

    payload, _ = assemble_index(**kwargs)

    calendar = next(group['body'] for group in payload['groups'] if group['key'] == 'calendar_normalized')
    assert calendar == composite


@pytest.mark.parametrize('field,value', [('publishedAt', '2026-10-10'), ('availableAt', '2026-10-10'), ('exDate', '2026-10-10'), ('publishedAt', 'invalid')])
def test_cash_dividend_all_dates_must_be_known_by_cutoff(field, value):
    from scripts.build_market_cache_index import stock_metrics
    detail = {'asOf': '2026-10-02', 'healthInputs': {'dividends': [
        {'year': 2025, 'period': 'annual', 'cashPerShare': 1, 'confirmed': True, 'approvedAt': '2026-09-01', field: value}]}}
    assert stock_metrics(detail, '2026-10-02')['cashDividend2025'] is None


@pytest.mark.parametrize('change', ['fake_zero', 'subset_roster', 'wrong_report_date', 'wrong_source_url', 'copied_stock_values'])
def test_original_source_values_are_reparsed_before_normalized_cache(change, tmp_path):
    from scripts.build_market_cache_index import write_institutional_cache
    from pipeline.market_cache import MarketCacheError
    snapshots, kwargs = setup_inputs(tmp_path)
    source = kwargs['source_cache_dir']; sidecar = source / 'institutional-TWSE-2026-10-02-validated.json'
    metadata = json.loads(sidecar.read_text()); raw_file = source / metadata['rawFile']
    raw = json.loads(raw_file.read_bytes())
    if change == 'fake_zero': raw['data'][0][2:] = ['2', '1', '1']
    elif change == 'subset_roster': raw['data'].append(['1104', 'other', '0', '0', '0'])
    elif change == 'wrong_report_date': raw['date'] = '20261001'
    elif change == 'wrong_source_url': metadata['sourceUrl'] = 'https://example.org/fake'
    elif change == 'copied_stock_values': snapshots[0]['rows'][0].update(buyShares=10, sellShares=0, netShares=10)
    encoded = json.dumps(raw).encode(); raw_file.write_bytes(encoded)
    metadata.update(rawSha256=hashlib.sha256(encoded).hexdigest(), rawBytes=len(encoded)); sidecar.write_text(json.dumps(metadata))
    with pytest.raises(MarketCacheError): write_institutional_cache(snapshots, source)


def test_restored_normalized_values_cannot_change_under_original_raw_hash(tmp_path):
    from scripts.build_market_cache_index import write_institutional_cache, assemble_index
    from pipeline.market_cache import MarketCacheError
    snapshots, kwargs = setup_inputs(tmp_path); source = kwargs['source_cache_dir']
    write_institutional_cache(snapshots, source)
    fragment = json.loads((source / 'institutional-TWSE-receipt-index.json').read_text())
    path = source / fragment['groups'][1]['bodyFile']; body = json.loads(path.read_text())
    body['rows'][0].update(buy=20, sell=10, net=10)
    path.write_text(json.dumps(body))
    with pytest.raises(MarketCacheError): assemble_index(**kwargs)


def test_institutional_index_writer_does_not_follow_fixed_temporary_symlink(tmp_path):
    from scripts.build_market_cache_index import write_institutional_cache
    snapshots, kwargs = setup_inputs(tmp_path)
    source = kwargs['source_cache_dir']
    sentinel = tmp_path / 'outside-sentinel.json'
    original = b'preserve external sentinel'
    sentinel.write_bytes(original)
    (source / 'institutional-TWSE-receipt-index.tmp').symlink_to(sentinel)

    write_institutional_cache(snapshots, source)

    assert sentinel.read_bytes() == original


def test_institutional_index_writer_rejects_symlinked_target(tmp_path):
    from scripts.build_market_cache_index import write_institutional_cache
    from pipeline.market_cache import MarketCacheError
    snapshots, kwargs = setup_inputs(tmp_path)
    source = kwargs['source_cache_dir']
    sentinel = tmp_path / 'outside-sentinel.json'
    sentinel.write_bytes(b'preserve external sentinel')
    (source / 'institutional-TWSE-receipt-index.json').symlink_to(sentinel)

    with pytest.raises(MarketCacheError, match='path'):
        write_institutional_cache(snapshots, source)
    assert sentinel.read_bytes() == b'preserve external sentinel'


def test_stock_directory_symlink_cannot_import_external_evidence(tmp_path):
    import shutil
    from scripts.build_market_cache_index import write_institutional_cache, assemble_index
    from pipeline.market_cache import MarketCacheError
    snapshots, kwargs = setup_inputs(tmp_path)
    write_institutional_cache(snapshots, kwargs['source_cache_dir'])
    directory = kwargs['data_dir'] / 'releases/run-1/stocks'
    outside = tmp_path / 'outside'
    shutil.move(directory, outside)
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MarketCacheError): assemble_index(**kwargs)


def test_actual_captured_tpex_all_788_common_rows_reparse_offline():
    from scripts.build_market_cache_index import _reparse_receipt
    from pipeline.official_institutional import parse_tpex_csv
    raw_file = Path(__file__).resolve().parents[1] / '.cache/official-institutional/tpex-daily-20261002.csv'
    if not raw_file.exists(): pytest.skip('actual captured public receipt unavailable in this checkout')
    raw = raw_file.read_bytes()
    rows = parse_tpex_csv(raw, expected_date=date(2026, 10, 2))
    codes = sorted(row['code'] for row in rows if __import__('re').fullmatch(r'[1-9]\d{3}', row['code']))
    assert len(codes) == 788
    metadata = {'market': 'TPEx', 'reportedDate': '2026-10-02', 'requestDate': '2026-10-02', 'validated': True,
                'codes': codes, 'unit': 'shares', 'encoding': 'MS950', 'sourceUrl': TPEX_ENDPOINT+'?'+urlencode({'type':'Daily','sect':'AL','date':'2026/10/02','response':'csv'}),
                'rawSha256': hashlib.sha256(raw).hexdigest(), 'rawBytes': len(raw)}
    assert len(_reparse_receipt(metadata, raw, 'TPEx', '2026-10-02')) == 788


@pytest.mark.parametrize('change', ['missing_role', 'list_bundle'])
def test_malformed_restored_institutional_packet_is_sanitized(change, tmp_path):
    from scripts.build_market_cache_index import write_institutional_cache, assemble_index
    from pipeline.market_cache import MarketCacheError
    snapshots, kwargs = setup_inputs(tmp_path); source = kwargs['source_cache_dir']
    write_institutional_cache(snapshots, source)
    path = source / 'institutional-TWSE-receipt-index.json'; fragment = json.loads(path.read_text())
    if change == 'missing_role': fragment['groups'].pop()
    else:
        raw = b'[]'; (source / fragment['groups'][0]['bodyFile']).write_bytes(raw)
        for group in fragment['groups']:
            group['sourceSha256'] = hashlib.sha256(raw).hexdigest()
            if group['kind'].endswith('_normalized'): group['normalizedFromSha256'] = group['sourceSha256']
    path.write_text(json.dumps(fragment))
    with pytest.raises(MarketCacheError): assemble_index(**kwargs)


def test_real_python_proof_bytes_verify_in_crypto_only_js_with_synthetic_auth(tmp_path):
    import subprocess
    from scripts.build_market_cache_index import write_institutional_cache, assemble_index
    from pipeline.market_cache import build_market_cache, canonical
    snapshots, kwargs = setup_inputs(tmp_path)
    write_institutional_cache(snapshots, kwargs['source_cache_dir'])
    payload, expected = assemble_index(**kwargs); result = build_market_cache(payload, expected)
    proof_bytes = canonical(result['proof'])
    expected = {**expected, 'manifestHash': result['manifest']['manifestHash'],
                'producerProofSha256': hashlib.sha256(proof_bytes).hexdigest(),
                'artifactLineage': {'repository': 'pingpongtech-uskg/stock-web-pages', 'workflowId': '123',
                                   'artifactId': '456', 'artifactSha256': 'b'*64, **payload['source']}}
    root = tmp_path / 'interop'; root.mkdir()
    (root / 'manifest.json').write_bytes(canonical(result['manifest']))
    (root / 'proof.json').write_bytes(proof_bytes)
    (root / 'expected.json').write_bytes(canonical(expected))
    for name, content in result['files'].items(): (root / name).write_bytes(content)
    module = Path(__file__).resolve().parents[1] / 'scripts/n8n/market-cache.cjs'
    script = "const fs=require('fs');const c=require(process.argv[1]);const p=process.argv[2];const m=JSON.parse(fs.readFileSync(p+'/manifest.json'));const e=JSON.parse(fs.readFileSync(p+'/expected.json'));const f=Object.fromEntries(fs.readdirSync(p).filter(n=>n.endsWith('.gz')).map(n=>[n,fs.readFileSync(p+'/'+n)]));console.log(JSON.stringify(c.verifyCompressedMarketCache(m,f,e,fs.readFileSync(p+'/proof.json'))));"
    result = json.loads(subprocess.check_output(['node', '-e', script, str(module), str(root)]))
    assert result['cacheComplete'] and result['verificationLevel'] == 'compressed_backup_verified'
    assert result['rawSemanticsVerifiedByProducer'] is True and result['independentRawSemanticsVerified'] is False


def test_store_ignores_fixed_temporary_symlink_without_touching_sentinel(tmp_path):
    from scripts.build_market_cache_index import _store
    sentinel = tmp_path / 'sentinel'; sentinel.write_bytes(b'untouched')
    directory = tmp_path / 'receipts'; directory.mkdir()
    target = directory / 'content.json'
    fixed_temporary = directory / 'content.json.tmp'
    fixed_temporary.symlink_to(sentinel)
    _store(target, b'new receipt')
    assert sentinel.read_bytes() == b'untouched'
    assert target.read_bytes() == b'new receipt'
    assert not target.is_symlink()
    assert fixed_temporary.is_symlink()
    assert sorted(item.name for item in directory.iterdir()) == ['content.json', 'content.json.tmp']


@pytest.mark.parametrize('existing', [True, False])
def test_store_rejects_target_symlink_before_read_or_write(tmp_path, existing):
    from scripts.build_market_cache_index import _store
    from pipeline.market_cache import MarketCacheError
    sentinel = tmp_path / 'sentinel'
    if existing: sentinel.write_bytes(b'new receipt')
    target = tmp_path / 'content.json'; target.symlink_to(sentinel)
    with pytest.raises(MarketCacheError, match='cache_path'):
        _store(target, b'new receipt')
    assert target.is_symlink()
    assert sentinel.read_bytes() == b'new receipt' if existing else not sentinel.exists()


def test_store_rejects_symlinked_ancestor_before_creating_files(tmp_path):
    from scripts.build_market_cache_index import _store
    from pipeline.market_cache import MarketCacheError
    outside = tmp_path / 'outside'; outside.mkdir()
    alias = tmp_path / 'alias'; alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MarketCacheError, match='cache_path'):
        _store(alias / 'new' / 'content.json', b'new receipt')
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize('availability', ['2026-10-10', 'invalid-date'])
def test_cash_dividend_ex_dividend_date_cannot_bypass_earlier_approval(availability):
    from scripts.build_market_cache_index import stock_metrics
    detail = {'asOf': '2026-10-02', 'healthInputs': {'dividends': [
        {'year': 2025, 'period': 'annual', 'cashPerShare': 1, 'confirmed': True,
         'approvedAt': '2026-09-01', 'exDividendDate': availability}]}}
    assert stock_metrics(detail, '2026-10-02')['cashDividend2025'] is None


def test_pinned_ownership_state_backed_up_beside_stock_rows(tmp_path):
    from scripts.build_market_cache_index import write_institutional_cache, assemble_index
    from scripts.update_ownership_checkpoint import build_manifest
    from pipeline.ownership_queue import new_state, save_state
    from pipeline.market_cache import validate_ownership_bundle
    snapshots, kwargs = setup_inputs(tmp_path)
    write_institutional_cache(snapshots, kwargs['source_cache_dir'])
    directory = tmp_path / 'ownership'; directory.mkdir()
    save_state(directory, new_state(['2547'], ['2547'], '2026-10-02'))
    (directory / 'snapshot.json').write_text(json.dumps({'schemaVersion': 'ownership-snapshot-v1', 'verifiedMarketDate': '2026-10-02', 'rows': []}))
    build_manifest(directory, directory / 'snapshot.json', 'a'*40, request_id='test', actions_run_id='1', actions_run_attempt='1')
    payload, _ = assemble_index(**kwargs, ownership_state_dir=directory, ownership_generation='b'*40)
    stock = next(group for group in payload['groups'] if group['kind'] == 'published_stock_inputs')
    assert len(stock['body']['rows']) == 100
    bundle = validate_ownership_bundle(stock['body']['ownershipBundle'], '2026-10-02')
    assert bundle['decodedFiles']['queue.json'] == (directory / 'queue.json').read_bytes()
    with pytest.raises(Exception): assemble_index(**kwargs, ownership_state_dir=directory, ownership_generation=None)
