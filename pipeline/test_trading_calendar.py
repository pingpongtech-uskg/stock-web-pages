import pytest
from pipeline.trading_calendar import build_calendar, is_open, next_deadline
ROWS = [
 {'Name': '國曆新年開始交易日', 'Date': '1150102', 'Weekday':'五','Description':'交易'},
 {'Name': '農曆春節前最後交易日', 'Date': '1150211', 'Weekday':'三','Description':'交易'},
 {'Name': '市場無交易，僅辦理結算交割作業', 'Date': '1150212', 'Weekday':'四','Description':''},
 {'Name': '農曆春節後開始交易日', 'Date': '1150223', 'Weekday':'一','Description':'交易'},
 {'Name': '國慶日', 'Date': '1151009', 'Weekday':'五','Description':'休市'},
]


def test_official_open_exceptions_and_closures():
 value = build_calendar(ROWS, year=2026, fetched_at='2026-10-02T10:00:00Z')
 assert is_open(value, '2026-02-11')
 assert not is_open(value, '2026-02-12')
 assert not is_open(value, '2026-10-09')
 assert is_open(value, '2026-10-02')
 assert not is_open(value, '2026-10-03')


@pytest.mark.parametrize('rows,year', [([],2026), (ROWS,2027), ({'error':'bad'},2026), ([{'Name':'new','Date':'1150101'}],2026)])
def test_calendar_unknown_or_wrong_year_fails_closed(rows, year):
 with pytest.raises(ValueError): build_calendar(rows,year=year,fetched_at='now')


@pytest.mark.parametrize('changes', [{'Date':'20261009'}, {'Weekday':'一'}, {'Name':'unknown'}])
def test_unknown_event_or_invalid_date_or_weekday_is_rejected(changes):
 with pytest.raises(ValueError): build_calendar([*ROWS[:-1],{**ROWS[-1],**changes}],year=2026,fetched_at='now')


def test_next_deadline_and_year_rollover_require_calendar():
 value = build_calendar(ROWS,year=2026,fetched_at='now')
 assert next_deadline(value,'2026-10-08') == '2026-10-12T19:30:00+08:00'
 with pytest.raises(ValueError): is_open(value,'2027-01-04')
 with pytest.raises(ValueError): next_deadline(value,'2026-12-31')
