from datetime import date
import io
import json
import base64
import hashlib
import pytest

from pipeline.market_indicators import compute_volume_multiple


def row(day: str, volume: str):
    return {"date": day, "volume": volume}


def test_volume_multiple_excludes_current_day_and_turns_green_at_two():
    result = compute_volume_multiple(
        [row("2026-09-15", "1,500"), row("2026-09-16", "1,500"), row("2026-09-17", "1,500"), row("2026-09-18", "1,500"), row("2026-09-21", "1,500"), row("2026-09-22", "3,000")],
        as_of=date(2026, 9, 22),
    )
    assert result["currentVolume"] == 3000
    assert result["previous5AverageVolume"] == 1500
    assert result["multiple"] == 2.0
    assert result["signal"] == "green"


def test_volume_multiple_below_two_is_yellow():
    result = compute_volume_multiple([row(f"2026-09-{day:02d}", "1,500") for day in range(15, 22)], as_of=date(2026, 9, 22))
    assert result["multiple"] == 1.0
    assert result["signal"] == "yellow"


def test_volume_multiple_fails_closed_without_five_prior_sessions():
    result = compute_volume_multiple([row("2026-09-18", "3,000")], as_of=date(2026, 9, 18))
    assert result["status"] == "unavailable"
    assert result["multiple"] is None
    assert result["signal"] == "unknown"


def test_volume_multiple_does_not_skip_a_missing_prior_session():
    rows = [row(f"2026-09-{day:02d}", "1,500") for day in range(15, 22)]
    rows[2]["volume"] = ""
    result = compute_volume_multiple(rows, as_of=date(2026, 9, 22))
    assert result["status"] == "unavailable"
    assert result["signal"] == "unknown"


CALENDAR = {'schemaVersion': 'trading-calendar-v1', 'year': 2026, 'timezone': 'Asia/Taipei',
            'closedDates': ['2026-09-25', '2026-09-28'], 'openExceptions': []}
VOLUME_DATES = ['2026-09-22', '2026-09-23', '2026-09-24', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02']


def volume_raw(month, days):
    return ('  ' + json.dumps({'stat': 'OK', 'date': f'2026{month:02d}01',
                              'fields': ['日期', '成交股數'], 'data': [[f'115/{month:02d}/{day:02d}', str(day * 100)] for day in days]}) + '\n').encode()


def test_volume_capture_exact_month_bytes_and_seven_calendar_sessions(tmp_path, monkeypatch):
    from pipeline.market_indicators import build_00631l_volume_indicator
    october = volume_raw(10, [1, 2])
    september = volume_raw(9, [22, 23, 24, 29, 30])
    calls = []
    def respond(request, **kwargs):
        calls.append((request.full_url, kwargs))
        return io.BytesIO(october if 'date=20261001' in request.full_url else september)
    monkeypatch.setattr('pipeline.market_indicators.urlopen', respond)
    result = build_00631l_volume_indicator('2026-10-02', source_cache_dir=tmp_path, calendar=CALENDAR)
    assert result['status'] == 'available' and result['marketDate'] == '2026-10-02'
    assert len(calls) == 2 and all(call[1]['timeout'] <= 30 for call in calls)
    index = json.loads((tmp_path / 'volume-receipt-index.json').read_text())
    raw_group, normalized = index['groups']
    bundle = json.loads((tmp_path / raw_group['bodyFile']).read_text())
    assert [r['requestMonth'] for r in bundle['receipts']] == ['2026-09', '2026-10']
    for receipt, raw in zip(bundle['receipts'], [september, october]):
        assert base64.b64decode(receipt['rawBase64']) == raw
        assert (tmp_path / receipt['rawFile']).read_bytes() == raw
        assert receipt['rawSha256'] == hashlib.sha256(raw).hexdigest()
        assert receipt['rawBytes'] == len(raw) and receipt['unit'] == 'shares'
    assert raw_group['dates'] == VOLUME_DATES and raw_group['codes'] == ['00631L']
    assert raw_group['sourceSha256'] == hashlib.sha256((tmp_path / raw_group['bodyFile']).read_bytes()).hexdigest()
    assert normalized['normalizedFromSha256'] == raw_group['sourceSha256']
    values = json.loads((tmp_path / normalized['bodyFile']).read_text())['rows']
    assert [r['marketDate'] for r in values] == VOLUME_DATES
    assert all(r['code'] == '00631L' and r['unit'] == 'shares' and type(r['volume']) is int for r in values)


def test_capture_missing_calendar_fails_before_network(tmp_path, monkeypatch):
    from pipeline.market_indicators import build_00631l_volume_indicator
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError('unexpected HTTP')
    monkeypatch.setattr('pipeline.market_indicators.urlopen', forbidden)
    result = build_00631l_volume_indicator('2026-10-02', source_cache_dir=tmp_path)
    assert result['status'] == 'unavailable'
    assert calls == []
    assert not list(tmp_path.iterdir())


def test_capture_missing_prior_volume_preserves_receipts_without_index(tmp_path, monkeypatch):
    from pipeline.market_indicators import build_00631l_volume_indicator
    monkeypatch.setattr('pipeline.market_indicators.urlopen', lambda req, **kwargs: io.BytesIO(volume_raw(10, [1, 2]) if '20261001' in req.full_url else volume_raw(9, [22, 24, 29, 30])))
    result = build_00631l_volume_indicator('2026-10-02', source_cache_dir=tmp_path, calendar=CALENDAR)
    assert result['status'] == 'unavailable'
    assert len(list(tmp_path.glob('*.raw.json'))) == 2
    assert not (tmp_path / 'volume-receipt-index.json').exists()


@pytest.mark.parametrize('change', ['wrong_month', 'fractional_volume', 'duplicate_date'])
def test_month_report_validates_actual_period_and_integer_shares(tmp_path, monkeypatch, change):
    from pipeline.market_indicators import fetch_twse_stock_day
    value = json.loads(volume_raw(10, [1, 2]))
    if change == 'wrong_month': value['date'] = '20260901'
    elif change == 'fractional_volume': value['data'][0][1] = '1.5'
    else: value['data'].append(value['data'][0])
    raw = json.dumps(value).encode()
    monkeypatch.setattr('pipeline.market_indicators.urlopen', lambda *args, **kwargs: io.BytesIO(raw))
    with pytest.raises(ValueError): fetch_twse_stock_day(date(2026, 10, 2), source_cache_dir=tmp_path)
    assert any(path.read_bytes() == raw for path in tmp_path.glob('*.raw.json'))


def test_volume_capture_unsafe_directory_rejected_before_http(tmp_path, monkeypatch):
    from pipeline.market_indicators import build_00631l_volume_indicator, fetch_twse_stock_day
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(outside, target_is_directory=True)
    calls = []
    monkeypatch.setattr('pipeline.market_indicators.urlopen', lambda *args, **kwargs: calls.append(args) or io.BytesIO(volume_raw(10, [1, 2])))
    result = build_00631l_volume_indicator('2026-10-02', source_cache_dir=link / 'nested', calendar=CALENDAR)
    assert result['status'] == 'unavailable'
    with pytest.raises(ValueError):
        fetch_twse_stock_day(date(2026, 10, 2), source_cache_dir=link)
    assert calls == []
    assert list(outside.iterdir()) == []
