import base64
import hashlib
import io
import json

import pytest


def capture(tmp_path, **changes):
    from pipeline.source_receipts import capture_raw
    args = {'prefix': 'calendar-2026', 'raw': b'  {"official":true}\n',
            'source_url': 'https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule',
            'unit': 'calendar', 'request_period': {'requestYear': 2026},
            'retrieved_at': '2026-10-04T01:00:00+00:00'}
    return capture_raw(tmp_path, **{**args, **changes})


def test_capture_preserves_exact_unparsed_response_bytes(tmp_path):
    receipt = capture(tmp_path)
    raw = (tmp_path / receipt['rawFile']).read_bytes()
    assert raw == b'  {"official":true}\n'
    assert base64.b64decode(receipt['rawBase64']) == raw
    assert receipt['rawSha256'] == hashlib.sha256(raw).hexdigest()
    assert receipt['rawBytes'] == len(raw)
    assert receipt['requestYear'] == 2026
    assert list(tmp_path.glob('*.receipt.json'))


@pytest.mark.parametrize('url', ['http://example.org/report', 'https://user:dummy@example.org/report',
                               'https://example.org/report?%74oken=dummy'])
def test_receipt_rejects_private_or_authenticated_source_urls_before_write(tmp_path, url):
    with pytest.raises(ValueError): capture(tmp_path, source_url=url)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('prefix', ['../outside', 'a/b', '..'])
def test_receipt_internal_path_cannot_escape_directory(tmp_path, prefix):
    with pytest.raises(ValueError): capture(tmp_path, prefix=prefix)
    assert not list(tmp_path.iterdir())


def test_read_is_bounded_and_does_not_accept_partial_oversize():
    from pipeline.source_receipts import read_raw, MAX_SOURCE_BYTES
    class Response(io.BytesIO):
        def read(self, size=-1):
            assert size == MAX_SOURCE_BYTES + 1
            return super().read(size)
    assert read_raw(Response(b'{"valid":true}')) == b'{"valid":true}'
    with pytest.raises(ValueError): read_raw(Response(b'x' * (MAX_SOURCE_BYTES + 1)))
    with pytest.raises(ValueError): read_raw(io.StringIO('not raw bytes'))


def test_bundle_binds_exact_original_source_and_normalized_output(tmp_path):
    from pipeline.source_receipts import write_bundle
    receipt = capture(tmp_path)
    group = {'kind': 'calendar', 'market': 'TWSE', 'codes': [], 'dates': ['2026-10-02'],
             'unit': 'calendar', 'sourceUrl': receipt['sourceUrl']}
    normalized = {'year': 2026, 'timezone': 'Asia/Taipei', 'closedDates': [], 'openExceptions': []}
    result = write_bundle(tmp_path, prefix='calendar', receipts=[receipt], normalized=normalized, group=group)
    raw, derived = result['groups']
    content = (tmp_path / raw['bodyFile']).read_bytes()
    assert raw['sourceSha256'] == hashlib.sha256(content).hexdigest()
    assert derived['normalizedFromSha256'] == raw['sourceSha256']
    assert json.loads(content)['receipts'] == [receipt]
    assert json.loads((tmp_path / derived['bodyFile']).read_text()) == normalized
    assert json.loads((tmp_path / 'calendar-receipt-index.json').read_text()) == result


def test_capture_does_not_follow_existing_internal_file_symlink(tmp_path):
    raw = b'  {"official":true}\n'
    outside = tmp_path / 'outside'
    outside.write_bytes(b'unchanged')
    filename = f'calendar-2026-{hashlib.sha256(raw).hexdigest()}.raw.json'
    (tmp_path / filename).symlink_to(outside)
    with pytest.raises(ValueError): capture(tmp_path)
    assert outside.read_bytes() == b'unchanged'


def test_bundle_does_not_read_raw_file_through_symlink(tmp_path):
    from pipeline.source_receipts import write_bundle
    receipt = capture(tmp_path)
    raw_file = tmp_path / receipt['rawFile']
    outside = tmp_path / 'outside'
    outside.write_bytes(raw_file.read_bytes())
    raw_file.unlink()
    raw_file.symlink_to(outside)
    with pytest.raises(ValueError):
        write_bundle(tmp_path, prefix='calendar', receipts=[receipt], normalized={},
                     group={'kind': 'calendar', 'market': 'TWSE', 'codes': [], 'dates': ['2026-10-02'],
                            'unit': 'calendar', 'sourceUrl': receipt['sourceUrl']})
    assert not (tmp_path / 'calendar-receipt-index.json').exists()


@pytest.mark.parametrize('changes', [{'retrieved_at': '2026-10-02T18:00:00'}, {'unit': 'unknown'},
                                    {'request_period': {'requestYear': True}}, {'request_period': {'requestMonth': '2026-13'}},
                                    {'request_period': {'requestDate': '2026-10-2'}}, {'request_period': {'unexpected': '2026'}}])
def test_invalid_receipt_metadata_is_rejected_before_file_creation(tmp_path, changes):
    with pytest.raises(ValueError): capture(tmp_path, **changes)
    assert not list(tmp_path.iterdir())


def test_bundle_rejects_altered_raw_metadata(tmp_path):
    from pipeline.source_receipts import write_bundle
    receipt = capture(tmp_path)
    with pytest.raises(ValueError):
        write_bundle(tmp_path, prefix='calendar', receipts=[{**receipt, 'rawSha256': '0' * 64}], normalized={},
                     group={'kind': 'calendar', 'market': 'TWSE', 'codes': [], 'dates': ['2026-10-02'],
                            'unit': 'calendar', 'sourceUrl': receipt['sourceUrl']})
    assert not (tmp_path / 'calendar-receipt-index.json').exists()


@pytest.mark.parametrize('nested', [False, True])
def test_capture_rejects_symlink_directory_and_ancestor_without_external_writes(tmp_path, nested):
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = tmp_path / 'cache-link'
    link.symlink_to(outside, target_is_directory=True)
    directory = link / 'new-child' if nested else link
    with pytest.raises(ValueError):
        capture(directory)
    assert list(outside.iterdir()) == []


def test_bundle_rejects_symlink_directory_before_reading_or_writing(tmp_path):
    from pipeline.source_receipts import write_bundle
    outside = tmp_path / 'outside'
    outside.mkdir()
    receipt = capture(outside)
    original = {path.name: path.read_bytes() for path in outside.iterdir()}
    link = tmp_path / 'cache-link'
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        write_bundle(link, prefix='calendar', receipts=[receipt], normalized={},
                     group={'kind': 'calendar', 'market': 'TWSE', 'codes': [], 'dates': ['2026-10-02'],
                            'unit': 'calendar', 'sourceUrl': receipt['sourceUrl']})
    assert {path.name: path.read_bytes() for path in outside.iterdir()} == original


def test_capture_accepts_normal_system_temporary_directory(tmp_path):
    # pytest's actual TMPDIR may sit under /var -> /private/var on macOS.
    receipt = capture(tmp_path / 'normal' / 'cache')
    assert (tmp_path / 'normal' / 'cache' / receipt['rawFile']).is_file()


@pytest.mark.parametrize('alias,canonical', [('/var', '/private/var'), ('/tmp', '/private/tmp')])
def test_safe_directory_accepts_verified_macos_system_aliases(tmp_path, alias, canonical):
    import tempfile
    from pathlib import Path
    from pipeline.source_receipts import safe_directory
    alias_path = Path(alias)
    if not alias_path.is_symlink() or alias_path.resolve() != Path(canonical):
        pytest.skip('macOS system alias unavailable')
    assert safe_directory(alias_path) == Path(canonical)
    if tmp_path.is_relative_to(canonical):
        directory = alias_path / tmp_path.relative_to(canonical) / 'cache'
        receipt = capture(directory)
        assert safe_directory(directory) == directory.resolve()
        assert (directory / receipt['rawFile']).is_file()
    elif alias == '/tmp':
        with tempfile.TemporaryDirectory(dir=alias) as directory:
            receipt = capture(Path(directory) / 'cache')
            assert (Path(directory) / 'cache' / receipt['rawFile']).is_file()
