"""Taiwan exchange trading calendar from TWSE's published holiday schedule."""
from __future__ import annotations
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

SOURCE_URL = 'https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule'
TIMEZONE = 'Asia/Taipei'
CLOSED_NAMES = {'中華民國開國紀念日', '市場無交易，僅辦理結算交割作業', '農曆除夕及春節',
                '和平紀念日', '兒童節及民族掃墓節', '勞動節', '端午節', '中秋節',
                '孔子誕辰紀念日/教師節', '國慶日', '臺灣光復暨金門古寧頭大捷紀念日', '行憲紀念日'}
OPEN_NAMES = {'國曆新年開始交易日', '農曆春節前最後交易日', '農曆春節後開始交易日'}


def build_calendar(rows: Any, *, year: int, fetched_at: str) -> dict[str, Any]:
    if not isinstance(rows, list) or not rows:
        raise ValueError('official calendar must be a nonempty array')
    closed: set[str] = set(); opened: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not all(row.get(key) for key in ('Name', 'Date', 'Weekday')) or not isinstance(row.get('Description'), str):
            raise ValueError('unknown official calendar row')
        raw = str(row['Date'])
        if len(raw) != 7 or not raw.isdigit():
            raise ValueError('invalid ROC calendar date')
        day = date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:7]))
        if row['Weekday'] != '一二三四五六日'[day.weekday()]:
            raise ValueError('official calendar weekday mismatch')
        if day.year != year:
            raise ValueError('official calendar year mismatch')
        name = str(row['Name']).replace(' ', '')
        if name not in OPEN_NAMES | CLOSED_NAMES:
            raise ValueError('unrecognized official calendar event')
        if name in OPEN_NAMES:
            opened.add(day.isoformat())
        else:
            closed.add(day.isoformat())
    if not opened or not closed or opened & closed:
        raise ValueError('official calendar open/closed classification incomplete')
    return {'schemaVersion': 'trading-calendar-v1', 'timezone': TIMEZONE, 'year': year,
            'closedDates': sorted(closed), 'openExceptions': sorted(opened),
            'sourceUrl': SOURCE_URL, 'fetchedAt': fetched_at}


def is_open(calendar: dict[str, Any], day: str) -> bool:
    parsed = date.fromisoformat(day)
    if (calendar.get('schemaVersion') != 'trading-calendar-v1' or parsed.year != calendar.get('year') or
        calendar.get('timezone') != TIMEZONE or not isinstance(calendar.get('closedDates'), list) or
        not isinstance(calendar.get('openExceptions'), list)):
        raise ValueError('authoritative calendar unavailable for requested year')
    if day in calendar['closedDates']:
        return False
    return day in calendar['openExceptions'] or parsed.weekday() < 5


def next_deadline(calendar: dict[str, Any], after: str, *, hour: int = 19, minute: int = 30) -> str:
    day = date.fromisoformat(after) + timedelta(days=1)
    while not is_open(calendar, day.isoformat()):
        day += timedelta(days=1)
    return datetime.combine(day, time(hour, minute), ZoneInfo(TIMEZONE)).isoformat()
