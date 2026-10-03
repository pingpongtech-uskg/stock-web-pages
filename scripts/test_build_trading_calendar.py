import io
import json
import hashlib
import base64
from scripts.build_trading_calendar import main
from pipeline.test_trading_calendar import ROWS


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
