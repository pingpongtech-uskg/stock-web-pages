"""Taiwan exchange trading calendar from TWSE's published holiday schedule."""
from __future__ import annotations
from datetime import date, datetime, time, timedelta
import re
from typing import Any
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

SOURCE_URL = 'https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule'
REPORT_URL = 'https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule'
TIMEZONE = 'Asia/Taipei'
CLOSED_NAMES = {'中華民國開國紀念日', '市場無交易，僅辦理結算交割作業', '農曆除夕及春節',
                '和平紀念日', '兒童節及民族掃墓節', '勞動節', '端午節', '中秋節',
                '孔子誕辰紀念日/教師節', '國慶日', '臺灣光復暨金門古寧頭大捷紀念日', '行憲紀念日'}
OPEN_NAMES = {'國曆新年開始交易日', '農曆春節前最後交易日', '農曆春節後開始交易日'}


def calendar_request_url(year: int) -> str:
    if type(year) is not int or not 1911 < year < 9999:
        raise ValueError('invalid calendar year')
    return f'{REPORT_URL}?date={year}0101&response=json'


def is_calendar_source(url: Any, *, year: int | None = None) -> bool:
    """Accept the legacy OpenAPI source contract and pinned official TWSE reports."""
    if url == SOURCE_URL:
        return True
    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query, strict_parsing=True)
        if (parsed.scheme != 'https' or parsed.netloc != 'www.twse.com.tw' or
            parsed.path != '/rwd/zh/holidaySchedule/holidaySchedule' or
            set(query) != {'date', 'response'} or query['response'] != ['json']):
            return False
        match = query['date'][0]
        return bool(re.fullmatch(r'(19\d{2}|[2-9]\d{3})0101', match) and
                    (year is None or int(match[:4]) == year))
    except (ValueError, IndexError):
        return False


def normalize_calendar_rows(rows: Any, *, year: int) -> list[dict[str, Any]]:
    if isinstance(rows, dict):
        if rows.get('stat') != 'ok' or type(rows.get('queryYear')) is not int or rows['queryYear'] != year:
            raise ValueError('official calendar year mismatch')
        data = rows.get('data')
        if not isinstance(data, list) or not data:
            raise ValueError('official calendar must be a nonempty array')
        normalized = []
        for item in data:
            if (not isinstance(item, list) or len(item) < 2 or not isinstance(item[0], str) or
                not isinstance(item[1], str) or (len(item) > 2 and not isinstance(item[2], str))):
                raise ValueError('unknown official calendar row')
            try:
                day = date.fromisoformat(item[0])
            except ValueError as exc:
                raise ValueError('invalid official calendar date') from exc
            if day.isoformat() != item[0] or day.year != year:
                raise ValueError('official calendar year mismatch')
            normalized.append({'Name': item[1], 'Date': f'{day.year - 1911:03d}{day.month:02d}{day.day:02d}',
                               'Weekday': '一二三四五六日'[day.weekday()],
                               'Description': item[2] if len(item) > 2 else ''})
        rows = normalized
    if not isinstance(rows, list) or not rows:
        raise ValueError('official calendar must be a nonempty array')
    return rows


def reported_calendar_dates(rows: Any, *, year: int) -> list[str]:
    result = []
    for row in normalize_calendar_rows(rows, year=year):
        if not isinstance(row, dict) or not isinstance(row.get('Date'), str) or not re.fullmatch(r'\d{7}', row['Date']):
            raise ValueError('invalid ROC calendar date')
        raw = row['Date']
        try:
            day = date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:7]))
        except ValueError as exc:
            raise ValueError('invalid ROC calendar date') from exc
        if day.year != year:
            raise ValueError('official calendar year mismatch')
        result.append(day.isoformat())
    return sorted(result)


def build_calendar(rows: Any, *, year: int, fetched_at: str) -> dict[str, Any]:
    rows = normalize_calendar_rows(rows, year=year)
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


def _validate_year_calendar(calendar: Any) -> int:
    if (not isinstance(calendar, dict) or calendar.get('schemaVersion') != 'trading-calendar-v1' or
        type(calendar.get('year')) is not int or calendar.get('timezone') != TIMEZONE or
        ('sourceUrl' in calendar and calendar.get('sourceUrl') != SOURCE_URL)):
        raise ValueError('invalid authoritative calendar')
    for field in ('closedDates', 'openExceptions'):
        values = calendar.get(field)
        if (not isinstance(values, list) or not all(isinstance(value, str) for value in values) or
            values != sorted(set(values))):
            raise ValueError('invalid authoritative calendar dates')
        for value in values:
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError('invalid authoritative calendar date') from exc
            if parsed.isoformat() != value or parsed.year != calendar['year']:
                raise ValueError('invalid authoritative calendar date')
    if set(calendar['closedDates']) & set(calendar['openExceptions']):
        raise ValueError('conflicting authoritative calendar dates')
    return calendar['year']


def compose_calendar_set(calendars: list[dict[str, Any]]) -> dict[str, Any]:
    """Bind adjacent, individually source-validated years without merging their dates."""
    if not isinstance(calendars, list) or len(calendars) != 2:
        raise ValueError('calendar set requires two adjacent years')
    tagged = [(_validate_year_calendar(calendar), calendar) for calendar in calendars]
    if any(calendar.get('sourceUrl') != SOURCE_URL for _, calendar in tagged):
        raise ValueError('calendar set requires official sources')
    years = [year for year, _ in tagged]
    if len(set(years)) != len(years):
        raise ValueError('duplicate calendar year')
    ordered = [calendar for _, calendar in sorted(tagged, key=lambda item: item[0])]
    years = sorted(years)
    if years[1] != years[0] + 1:
        raise ValueError('calendar set years must be adjacent')
    return {'schemaVersion': 'trading-calendar-set-v1', 'timezone': TIMEZONE,
            'calendars': [dict(calendar) for calendar in ordered]}


def calendar_years(calendar: dict[str, Any]) -> list[int]:
    """Return validated calendar years for either the old or composite shape."""
    if isinstance(calendar, dict) and calendar.get('schemaVersion') == 'trading-calendar-v1':
        return [_validate_year_calendar(calendar)]
    if (not isinstance(calendar, dict) or calendar.get('schemaVersion') != 'trading-calendar-set-v1' or
        calendar.get('timezone') != TIMEZONE or not isinstance(calendar.get('calendars'), list)):
        raise ValueError('invalid authoritative calendar set')
    value = compose_calendar_set(calendar['calendars'])
    if value != calendar:
        raise ValueError('calendar set is not canonical')
    return [item['year'] for item in value['calendars']]


def is_open(calendar: dict[str, Any], day: str) -> bool:
    parsed = date.fromisoformat(day)
    if isinstance(calendar, dict) and calendar.get('schemaVersion') == 'trading-calendar-set-v1':
        years = calendar_years(calendar)
        matching = [item for item in calendar['calendars'] if item['year'] == parsed.year]
        if len(matching) != 1:
            raise ValueError('authoritative calendar unavailable for requested year')
        return is_open(matching[0], day)
    if (calendar.get('schemaVersion') != 'trading-calendar-v1' or parsed.year != calendar.get('year') or
        calendar.get('timezone') != TIMEZONE or not isinstance(calendar.get('closedDates'), list) or
        not isinstance(calendar.get('openExceptions'), list)):
        raise ValueError('authoritative calendar unavailable for requested year')
    if day in calendar['closedDates']:
        return False
    return day in calendar['openExceptions'] or parsed.weekday() < 5


def recent_sessions(calendar: dict[str, Any], market_date: str, *, count: int = 11,
                    max_calendar_days: int = 60) -> list[str]:
    """Return newest-first open dates, requiring explicit coverage for every year crossed."""
    target = date.fromisoformat(market_date)
    if target.isoformat() != market_date or type(count) is not int or count < 1 or max_calendar_days < count:
        raise ValueError('invalid trading-session window')
    result = []
    for offset in range(max_calendar_days):
        day = target - timedelta(days=offset)
        if is_open(calendar, day.isoformat()):
            result.append(day.isoformat())
            if len(result) == count:
                return result
    raise ValueError('authoritative calendar has too few covered sessions')


def next_deadline(calendar: dict[str, Any], after: str, *, hour: int = 19, minute: int = 30) -> str:
    day = date.fromisoformat(after) + timedelta(days=1)
    while not is_open(calendar, day.isoformat()):
        day += timedelta(days=1)
    return datetime.combine(day, time(hour, minute), ZoneInfo(TIMEZONE)).isoformat()
