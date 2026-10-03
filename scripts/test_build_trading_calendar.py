import io
import json
import hashlib
import base64
import shutil
import pytest
from scripts.build_trading_calendar import main
from pipeline.test_trading_calendar import ROWS


def _rows_for_year(year):
    from datetime import date
    return [{**row, 'Date': f'{year-1911:03d}{row["Date"][3:]}',
             'Weekday': '一二三四五六日'[date(year, int(row['Date'][3:5]), int(row['Date'][5:])).weekday()]}
            for row in ROWS]


def test_calendar_cli_writes_open_day_and_never_overwrites_on_closed_or_wrong_year(tmp_path,monkeypatch):
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen',lambda *args,**kwargs: io.BytesIO(json.dumps(ROWS).encode()))
    output=tmp_path/'calendar.json'
    assert main(['--market-date','2026-10-02','--output',str(output)])==0
    original=output.read_bytes()
    value=json.loads(original)
    assert value['sourceUrl']=='https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule'
    assert '2026-10-09' in value['closedDates']
    assert main(['--market-date','2026-10-09','--output',str(output)])==1
    assert output.read_bytes()==original
    assert main(['--market-date','2027-01-04','--output',str(output)])==1
    assert output.read_bytes()==original


def test_calendar_cli_rejects_non_json_response(tmp_path,monkeypatch):
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen',lambda *args,**kwargs: io.BytesIO(b'<html>upstream error</html>'))
    output=tmp_path/'calendar.json'
    assert main(['--market-date','2026-10-02','--output',str(output)])==1
    assert not output.exists()


def test_calendar_capture_keeps_exact_bytes_and_binds_normalized_calendar(tmp_path, monkeypatch):
    raw = ('  ' + json.dumps(ROWS, ensure_ascii=False) + '\n').encode()
    calls = []
    def respond(request, **kwargs):
        calls.append((request.full_url, kwargs))
        return io.BytesIO(raw)
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen', respond)
    cache = tmp_path / 'receipts'
    output = tmp_path / 'calendar.json'
    assert main(['--market-date', '2026-10-02', '--output', str(output), '--source-cache-dir', str(cache)]) == 0
    assert len(calls) == 1 and calls[0][1]['timeout'] <= 30
    index = json.loads((cache / 'calendar-receipt-index.json').read_text())
    raw_group, normalized = index['groups']
    bundle = json.loads((cache / raw_group['bodyFile']).read_text())
    receipt = bundle['receipts'][0]
    assert base64.b64decode(receipt['rawBase64']) == raw
    assert (cache / receipt['rawFile']).read_bytes() == raw
    assert receipt['rawSha256'] == hashlib.sha256(raw).hexdigest()
    assert receipt['rawBytes'] == len(raw) and receipt['requestYear'] == 2026
    assert receipt['sourceUrl'] == calls[0][0] and receipt['unit'] == 'calendar'
    assert raw_group['sourceSha256'] == hashlib.sha256((cache / raw_group['bodyFile']).read_bytes()).hexdigest()
    assert normalized['normalizedFromSha256'] == raw_group['sourceSha256']
    assert json.loads((cache / normalized['bodyFile']).read_text()) == json.loads(output.read_text())


def test_calendar_capture_preserves_unparseable_raw_but_no_validated_index(tmp_path, monkeypatch):
    raw = b'<html>official failure</html>'
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen', lambda *args, **kwargs: io.BytesIO(raw))
    cache = tmp_path / 'receipts'
    assert main(['--market-date', '2026-10-02', '--output', str(tmp_path / 'calendar.json'), '--source-cache-dir', str(cache)]) == 1
    assert any(path.read_bytes() == raw for path in cache.glob('*.raw.json'))
    assert not (cache / 'calendar-receipt-index.json').exists()


def test_invalid_calendar_market_date_fails_before_http_or_output(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('unexpected HTTP')
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen', forbidden)
    assert main(['--market-date', '2026-10-2', '--output', str(tmp_path / 'calendar.json')]) == 1
    assert not (tmp_path / 'calendar.json').exists()


def test_calendar_random_atomic_temp_never_follows_legacy_temp_symlink(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen', lambda *args, **kwargs: io.BytesIO(json.dumps(ROWS).encode()))
    output = tmp_path / 'calendar.json'
    outside = tmp_path / 'outside'
    outside.write_bytes(b'unchanged')
    legacy_temp = output.with_suffix('.json.tmp')
    legacy_temp.symlink_to(outside)
    assert main(['--market-date', '2026-10-02', '--output', str(output)]) == 0
    assert outside.read_bytes() == b'unchanged'
    assert legacy_temp.is_symlink()
    assert not output.is_symlink()
    assert json.loads(output.read_bytes())['year'] == 2026


def test_calendar_unsafe_directory_rejected_before_http(tmp_path, monkeypatch):
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(outside, target_is_directory=True)
    calls = []
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen', lambda *args, **kwargs: calls.append(args) or io.BytesIO(json.dumps(ROWS).encode()))
    for option, path in [('--output', link / 'nested' / 'calendar.json'), ('--source-cache-dir', link / 'nested')]:
        args = ['--market-date', '2026-10-02', '--output', str(tmp_path / 'calendar.json'), option, str(path)]
        assert main(args) == 1
    assert calls == []
    assert list(outside.iterdir()) == []


def test_calendar_output_symlink_rejected_before_http(tmp_path, monkeypatch):
    outside = tmp_path / 'outside'
    outside.write_bytes(b'unchanged')
    output = tmp_path / 'calendar.json'
    output.symlink_to(outside)
    calls = []
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen', lambda *args, **kwargs: calls.append(args) or io.BytesIO(json.dumps(ROWS).encode()))
    assert main(['--market-date', '2026-10-02', '--output', str(output)]) == 1
    assert calls == []
    assert outside.read_bytes() == b'unchanged'


def test_calendar_atomic_replace_failure_preserves_existing_output_and_removes_temp(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen', lambda *args, **kwargs: io.BytesIO(json.dumps(ROWS).encode()))
    def fail_replace(*args):
        raise OSError('replace unavailable')
    monkeypatch.setattr('scripts.build_trading_calendar.os.replace', fail_replace)
    output = tmp_path / 'calendar.json'
    output.write_bytes(b'original')
    assert main(['--market-date', '2026-10-02', '--output', str(output)]) == 1
    assert output.read_bytes() == b'original'
    assert list(tmp_path.iterdir()) == [output]


def test_january_calendar_set_reuses_verified_prior_year_cache_without_prior_fetch(tmp_path, monkeypatch):
    from datetime import date
    prior_raw = json.dumps(_rows_for_year(2026), ensure_ascii=False).encode()
    current_raw = json.dumps(_rows_for_year(2027), ensure_ascii=False).encode()
    replies = [prior_raw, current_raw]
    calls = []
    def respond(request, **kwargs):
        calls.append(request.full_url)
        return io.BytesIO(replies.pop(0))
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen', respond)
    prior_cache = tmp_path / 'prior-live'
    prior_output = tmp_path / 'prior.json'
    assert main(['--market-date', '2026-12-31', '--output', str(prior_output),
                 '--source-cache-dir', str(prior_cache)]) == 0
    restored = tmp_path / 'restored' / '2026-12-31'
    restored.mkdir(parents=True)
    for name in ('calendar-receipt-index.json', 'calendar.raw.bundle.json', 'calendar.normalized.json'):
        shutil.copyfile(prior_cache / name, restored / name)
    current_cache = tmp_path / 'current-live'
    output = tmp_path / 'current.json'
    assert main(['--market-date', '2027-01-04', '--output', str(output),
                 '--source-cache-dir', str(current_cache), '--prior-calendar-cache-dir', str(restored)]) == 0
    assert len(calls) == 2
    calendar_set = json.loads(output.read_text())
    assert calendar_set['schemaVersion'] == 'trading-calendar-set-v1'
    assert [item['year'] for item in calendar_set['calendars']] == [2026, 2027]
    index = json.loads((current_cache / 'calendar-receipt-index.json').read_text())
    raw_group = next(group for group in index['groups'] if group['kind'] == 'calendar_raw')
    bundle = json.loads((current_cache / raw_group['bodyFile']).read_bytes())
    assert sorted(receipt['requestYear'] for receipt in bundle['receipts']) == [2026, 2027]
    assert all(receipt['sourceUrl'] == 'https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule'
               for receipt in bundle['receipts'])

    # A later January run restores the already-composite cache and reuses its
    # verified 2026 member rather than requiring a separate one-year fragment.
    replies.append(current_raw)
    later_cache = tmp_path / 'later-live'
    later_output = tmp_path / 'later.json'
    assert main(['--market-date', '2027-01-05', '--output', str(later_output),
                 '--source-cache-dir', str(later_cache), '--prior-calendar-cache-dir', str(current_cache)]) == 0
    assert len(calls) == 3
    assert [item['year'] for item in json.loads(later_output.read_text())['calendars']] == [2026, 2027]


def test_same_year_restored_calendar_is_ignored_when_target_window_stays_in_year(tmp_path, monkeypatch):
    raw = json.dumps(_rows_for_year(2026), ensure_ascii=False).encode()
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen', lambda *args, **kwargs: io.BytesIO(raw))
    prior_cache = tmp_path / 'same-year-cache'
    assert main(['--market-date', '2026-10-02', '--output', str(tmp_path / 'prior.json'),
                 '--source-cache-dir', str(prior_cache)]) == 0
    later_cache = tmp_path / 'same-year-current-cache'
    assert main(['--market-date', '2026-10-02', '--output', str(tmp_path / 'current.json'),
                 '--source-cache-dir', str(later_cache), '--prior-calendar-cache-dir', str(prior_cache)]) == 0


def test_january_calendar_set_requires_verified_prior_year_cache_and_never_fetches_it(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen',
        lambda request, **kwargs: calls.append(request.full_url) or io.BytesIO(json.dumps(_rows_for_year(2027)).encode()))
    output = tmp_path / 'calendar.json'
    cache = tmp_path / 'cache'
    assert main(['--market-date', '2027-01-04', '--output', str(output),
                 '--source-cache-dir', str(cache)]) == 1
    assert len(calls) == 1
    assert not output.exists()


def test_january_calendar_set_rejects_tampered_restored_receipt_before_http(tmp_path, monkeypatch):
    prior_cache = tmp_path / 'prior-live'
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen',
        lambda *args, **kwargs: io.BytesIO(json.dumps(_rows_for_year(2026)).encode()))
    assert main(['--market-date', '2026-12-31', '--output', str(tmp_path / 'prior.json'),
                 '--source-cache-dir', str(prior_cache)]) == 0
    restored = tmp_path / 'restored' / '2026-12-31'
    restored.mkdir(parents=True)
    for name in ('calendar-receipt-index.json', 'calendar.raw.bundle.json', 'calendar.normalized.json'):
        shutil.copyfile(prior_cache / name, restored / name)
    bundle_path = restored / 'calendar.raw.bundle.json'
    bundle = json.loads(bundle_path.read_bytes())
    bundle['receipts'][0]['rawBase64'] = base64.b64encode(b'[]').decode()
    bundle_path.write_text(json.dumps(bundle))
    calls = []
    monkeypatch.setattr('scripts.build_trading_calendar.urlopen',
        lambda *args, **kwargs: calls.append(args) or io.BytesIO(json.dumps(_rows_for_year(2027)).encode()))
    assert main(['--market-date', '2027-01-04', '--output', str(tmp_path / 'new.json'),
                 '--source-cache-dir', str(tmp_path / 'new-cache'), '--prior-calendar-cache-dir', str(restored)]) == 1
    assert calls == []


def test_restored_calendar_file_size_limit_is_applied_during_read(tmp_path, monkeypatch):
    from pathlib import Path
    from scripts.build_trading_calendar import _read_file

    class BoundedReader:
        def __init__(self): self.requested = []
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1):
            self.requested.append(size)
            return b'x' * size

    reader = BoundedReader()
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: reader)
    with pytest.raises(ValueError, match='size limit'):
        _read_file(tmp_path, 'oversized.json', 3)
    assert reader.requested == [4]
