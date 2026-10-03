"""Artifact export is bounded, atomic and never writes publication/quota state."""
import json
from pathlib import Path

import pytest

from pipeline.test_market_cache import fixture


def inputs(tmp_path):
    payload, expected = fixture()
    for index, group in enumerate(payload['groups']):
        if isinstance(group['body'], bytes):
            name = f'receipt-{index}.json'
            (tmp_path / name).write_bytes(group['body'])
            group['bodyFile'] = name
            del group['body']
    source, trusted = tmp_path / 'inputs.json', tmp_path / 'trusted.json'
    source.write_text(json.dumps(payload))
    trusted.write_text(json.dumps(expected))
    return source, trusted


def test_cli_export_is_atomic_and_independently_verifiable(tmp_path, capsys):
    from scripts.export_market_cache import main
    source, trusted = inputs(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    destination = tmp_path / 'artifact'
    assert main(['--input', str(source), '--expected', str(trusted), '--output', str(destination)]) == 0
    manifest = json.loads((destination / 'manifest.json').read_text())
    proof = json.loads((destination / 'proof.json').read_text())
    assert manifest['schemaVersion'] == 'market-cache-v1' and proof['cacheComplete']
    assert len(list(destination.glob('*.gz'))) == 9
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    assert 'market_cache_exported=' in capsys.readouterr().out
    existing = (destination / 'manifest.json').read_bytes()
    assert main(['--input', str(source), '--expected', str(trusted), '--output', str(destination)]) == 1
    assert (destination / 'manifest.json').read_bytes() == existing


@pytest.mark.parametrize('bad', ['../outside', '/tmp/outside', 'symlink', 'raw_body_json', 'duplicate_key', 'missing_source', 'untrusted', 'oversize'])
def test_cli_failure_leaves_no_partial_artifact_or_raw_error(tmp_path, capsys, bad, monkeypatch):
    from scripts import export_market_cache as exporter
    source, trusted = inputs(tmp_path)
    payload = json.loads(source.read_text())
    if bad == 'symlink':
        (tmp_path / 'link').symlink_to(tmp_path.parent / 'outside')
        payload['groups'][0]['bodyFile'] = 'link'
    elif bad in {'../outside', '/tmp/outside'}:
        payload['groups'][0]['bodyFile'] = bad
    elif bad == 'raw_body_json':
        del payload['groups'][0]['bodyFile']; payload['groups'][0]['body'] = {'rows': []}
    elif bad == 'missing_source': payload['groups'][0]['bodyFile'] = 'missing'
    elif bad == 'untrusted':
        value = json.loads(trusted.read_text()); value['source']['requestId'] = 'different'; trusted.write_text(json.dumps(value))
    elif bad == 'oversize': monkeypatch.setattr(exporter, 'MAX_INPUT_BYTES', 10)
    source.write_text(json.dumps(payload))
    if bad == 'duplicate_key': source.write_text('{"token":"sensitive-fixture", "token":"sensitive-fixture"}')
    assert exporter.main(['--input', str(source), '--expected', str(trusted), '--output', str(tmp_path / 'artifact')]) == 1
    assert not (tmp_path / 'artifact').exists()
    assert not list(tmp_path.glob('.artifact.*'))
    out = capsys.readouterr()
    assert 'sensitive-fixture' not in out.err and 'outside' not in out.err


def test_normalized_body_file_is_loaded_as_json(tmp_path):
    from scripts.export_market_cache import main
    source, trusted = inputs(tmp_path)
    value = json.loads(source.read_text())
    body = value['groups'][1].pop('body')
    (tmp_path / 'normalized.json').write_text(json.dumps(body))
    value['groups'][1]['bodyFile'] = 'normalized.json'
    source.write_text(json.dumps(value))
    assert main(['--input', str(source), '--expected', str(trusted), '--output', str(tmp_path / 'artifact')]) == 0


def test_loader_limits_aggregate_receipts_before_retaining_next_file(tmp_path, monkeypatch):
    from scripts import export_market_cache as exporter
    source, _ = inputs(tmp_path)
    monkeypatch.setattr(exporter, 'MAX_TOTAL_RAW', 1800)
    limits = []
    original = exporter._read
    def read(path, limit):
        if path != source: limits.append(limit)
        return original(path, limit)
    monkeypatch.setattr(exporter, '_read', read)
    with pytest.raises(exporter.MarketCacheError): exporter.load_inputs(source)
    assert len(limits) <= 2
    assert all(limit <= 1800 for limit in limits)


def test_flat_object_key_limit_rejects_before_iterating_pairs():
    from scripts.export_market_cache import _pairs, MarketCacheError
    class OversizedPairs(list):
        def __len__(self): return 10001
        def __iter__(self): pytest.fail('oversized object must fail before traversal')
    with pytest.raises(MarketCacheError): _pairs(OversizedPairs())
