"""Three-case historical source probe. Checkpoints never imply market coverage."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.finmind_client import BudgetExceeded, FinMindClient, FinMindError, SourceBlocked
from pipeline.finmind_incremental import DailyBudget, atomic_json, read_json

DATASET = 'TaiwanStockInstitutionalInvestorsBuySell'
OFFICIAL_URL = 'https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading'
BUY = 'SecuritiesInvestmentTrustCompanies-TotalBuy'
SELL = 'SecuritiesInvestmentTrustCompanies-TotalSell'
NET = 'SecuritiesInvestmentTrustCompanies-Difference'


def exact_date(value: str) -> str:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('Expected exact ISO date')
    return value


def integer(value: Any, *, nonnegative: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError('Expected integer source units')
    if not re.fullmatch(r'-?\d+', str(value)):
        raise ValueError('Expected integer source units')
    result = int(value)
    if nonnegative and result < 0:
        raise ValueError('Negative source buy/sell')
    return result


def select_probe_cases(rows: Any, market_date: str) -> list[dict[str, Any]]:
    day = date.fromisoformat(exact_date(market_date))
    roc = f'{day.year - 1911:03d}{day:%m%d}'
    if not isinstance(rows, list) or not rows:
        raise ValueError('Official source must be a nonempty array')
    validated = []; codes = set()
    for row in rows:
        if not isinstance(row, dict) or row.get('Date') != roc:
            raise ValueError('Official source date mismatch')
        code = row.get('SecuritiesCompanyCode')
        if not isinstance(code, str) or not code or code in codes:
            raise ValueError('Official source code missing or duplicate')
        codes.add(code)
        buy, sell, net = integer(row.get(BUY)), integer(row.get(SELL)), integer(row.get(NET), nonnegative=False)
        if buy - sell != net:
            raise ValueError('Official source net mismatch')
        if re.fullmatch(r'[1-9]\d{3}', code):
            validated.append({'code': code, 'buy': buy, 'sell': sell, 'net': net})
    cases = []
    for label, sign in [('positive', 1), ('negative', -1), ('zero', 0)]:
        matches = [row for row in validated if (row['net'] > 0) - (row['net'] < 0) == sign]
        if not matches:
            raise ValueError('Official source lacks all three probe cases')
        cases.append({**min(matches, key=lambda row: row['code']), 'case': label})
    return cases


def validate_probe_rows(rows: Any, case: dict[str, Any], dates: list[str]) -> dict[str, Any]:
    if not isinstance(rows, list):
        raise ValueError('Source rows must be an array')
    by_date = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Malformed source row')
        if row.get('name') != 'Investment_Trust':
            continue
        day = row.get('date')
        if row.get('stock_id') != case['code'] or day not in dates or day in by_date:
            raise ValueError('Source code/date/uniqueness mismatch')
        buy, sell = integer(row.get('buy')), integer(row.get('sell'))
        by_date[day] = {'date': day, 'code': case['code'], 'buy': buy, 'sell': sell,
                        'net': buy - sell, 'unit': 'shares'}
    current = by_date.get(dates[-1])
    if current and (current['buy'], current['sell']) != (case['buy'], case['sell']):
        raise ValueError('Source current-day units or amounts mismatch')
    missing = [day for day in dates if day not in by_date]
    return {'rows': [by_date[day] for day in sorted(by_date)], 'missingDates': missing,
            'status': 'partial' if missing else 'complete', 'coverage': len(by_date) / len(dates)}


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _key(code: str, dates: list[str]) -> str:
    return f'institutionalProbe:{dates[-1]}:{code}:{dates[0]}:{dates[-1]}'


def _category(exc: Exception, *, quota: bool = False) -> str:
    if isinstance(exc, BudgetExceeded):
        return 'budget_exhausted'
    if isinstance(exc, SourceBlocked):
        return 'source_blocked'
    return 'quota_unavailable' if quota else 'transport_unavailable'


def _save_progress(path: Path, summary: dict[str, Any], budget_date: str) -> None:
    DailyBudget(path, budget_date).update_metadata({'institutionalProbe': summary})


def _budget_metadata(path: Path, day: str) -> dict[str, Any]:
    value = {'quotaPolicy': 'rolling-hour-v1', 'rollingHourAttempts': 0,
             'projectHourlyCap': 300, 'accountAllowanceRemaining': None, 'quotaObservedAt': None}
    if not path.exists():
        return value
    try:
        budget = DailyBudget(path, day)
        return {**value, 'rollingHourAttempts': min(300, budget.rolling_used),
                'projectHourlyCap': budget.record['projectCap'],
                'accountAllowanceRemaining': budget.account_remaining,
                'quotaObservedAt': budget.record.get('quotaCheckedAt')}
    except (FinMindError, ValueError, OSError):
        return {**value, 'rollingHourAttempts': None, 'errorCategory': 'checkpoint_unavailable'}


def _cache_result(entry: Any, case: dict[str, Any], dates: list[str]) -> dict[str, Any] | None:
    if not isinstance(entry, dict) or entry.get('status') not in {'complete', 'partial'}:
        return None
    params = {'dataset': DATASET, 'data_id': case['code'], 'start_date': dates[0], 'end_date': dates[-1]}
    if entry.get('sourceParams') != params or entry.get('unit') != 'shares':
        return None
    rows, raw = entry.get('rows'), entry.get('rawRows')
    if (not isinstance(rows, list) or not isinstance(raw, list) or
        entry.get('sha256') != _hash(rows) or entry.get('rawSha256') != _hash(raw) or
        entry.get('sourceUrl') != 'https://api.finmindtrade.com/api/v4/data' or
        entry.get('officialSourceUrl') != OFFICIAL_URL):
        return None
    try:
        fetched_at = datetime.fromisoformat(entry.get('fetchedAt', ''))
        if fetched_at.tzinfo is None:
            return None
        result = validate_probe_rows(raw, case, dates)
    except (ValueError, TypeError):
        return None
    return result if result['status'] == entry['status'] and result['rows'] == rows else None


def run_institutional_probe(official_rows: Any, *, market_date: str, expected_dates: list[str],
        cache_dir: Path, budget_date: str, token: str, max_data_requests: int = 3,
        client_factory=FinMindClient) -> dict[str, Any]:
    """Use shared rolling-hour quota and durable case caches; make at most three data calls."""
    exact_date(budget_date); exact_date(market_date)
    if (not isinstance(expected_dates, list) or len(expected_dates) != 11 or
        [exact_date(day) for day in expected_dates] != sorted(set(expected_dates)) or
        expected_dates[-1] != market_date or type(max_data_requests) is not int or
        not 1 <= max_data_requests <= 3):
        raise ValueError('Probe requires eleven unique ordered sessions and at most three calls')
    cases = select_probe_cases(official_rows, market_date)
    state_path, rows_path = Path(cache_dir) / 'state.json', Path(cache_dir) / 'rows.json'
    stored = read_json(rows_path, {})
    if not isinstance(stored, dict):
        raise FinMindError('Invalid source checkpoint')
    entries = stored
    summary = {'probeVersion': 'institutional-probe-v1', 'marketDate': market_date,
        'expectedDates': expected_dates, 'globalCompleteness': False, 'publicationEligible': False,
        'tokenPresent': bool(token.strip()), 'actualAttempts': 0, 'dataRequests': 0,
        'cacheHits': 0, 'accountLimit': None, 'observedRemaining': None, 'cases': [],
        'outcome': 'unavailable', 'errorCategory': None,
        **_budget_metadata(state_path, budget_date)}
    if summary['errorCategory'] == 'checkpoint_unavailable':
        return summary
    pending = []
    for case in cases:
        cached = _cache_result(entries.get(_key(case['code'], expected_dates)), case, expected_dates)
        if cached:
            summary = {**summary, 'cacheHits': summary['cacheHits'] + 1,
                'cases': [*summary['cases'], {**case, **{key: cached[key]
                    for key in ('status', 'coverage', 'missingDates')}, 'errorCategory': None}]}
        else:
            pending.append(case)
    budget = None; client = None; before = 0
    if pending and token.strip():
        try:
            budget = DailyBudget(state_path, budget_date, hard_cap=300)
            before = budget.used
            client = client_factory(token, hard_cap=300, max_attempts=1, timeout=20, daily_budget=budget)
            info = client.configure_account_budget()
            summary = {**summary, 'accountLimit': int(info['api_request_limit']),
                       'observedRemaining': max(0, int(info['api_request_limit']) - int(info['user_count']))}
        except (FinMindError, ValueError, OSError) as exc:
            summary = {**summary, 'errorCategory': _category(exc, quota=True)}
            client = None
    elif pending:
        summary = {**summary, 'errorCategory': 'token_missing'}
    for case in pending:
        result = {'status': 'unavailable', 'coverage': 0, 'missingDates': expected_dates}
        error = summary['errorCategory']
        if client and summary['dataRequests'] < max_data_requests:
            params = {'dataset': DATASET, 'data_id': case['code'],
                      'start_date': expected_dates[0], 'end_date': expected_dates[-1]}
            attempted_before = budget.used
            try:
                raw = client.get(DATASET, data_id=case['code'], start_date=expected_dates[0], end_date=expected_dates[-1])
                fetched_at = datetime.now(timezone.utc).isoformat()
                # Persist successful source responses before validation/progress, including incomplete evidence.
                source_rows = [{key: row.get(key) for key in ('date', 'stock_id', 'name', 'buy', 'sell')}
                               for row in raw]
                entry = {'sourceParams': params, 'sourceUrl': 'https://api.finmindtrade.com/api/v4/data',
                    'officialSourceUrl': OFFICIAL_URL, 'fetchedAt': fetched_at, 'unit': 'shares',
                    'rawRows': source_rows, 'rawSha256': _hash(source_rows), 'rows': [], 'status': 'unvalidated'}
                entries = {**entries, _key(case['code'], expected_dates): entry}
                stored = entries
                atomic_json(rows_path, stored)
                try:
                    result = validate_probe_rows(source_rows, case, expected_dates)
                    entry = {**entry, **result, 'sha256': _hash(result['rows'])}
                    entries = {**entries, _key(case['code'], expected_dates): entry}
                    stored = entries
                    atomic_json(rows_path, stored)
                    error = None
                except ValueError:
                    error = 'invalid_source_rows'
            except (FinMindError, OSError) as exc:
                error = _category(exc)
                if isinstance(exc, (BudgetExceeded, SourceBlocked)):
                    summary = {**summary, 'errorCategory': error}
                    client = None
            summary = {**summary, 'dataRequests': summary['dataRequests'] + budget.used - attempted_before}
        elif client:
            error = 'operation_limit'
        summary = {**summary, 'cases': [*summary['cases'], {**case, **{key: result[key]
            for key in ('status', 'coverage', 'missingDates')}, 'errorCategory': error}],
            'actualAttempts': budget.used - before if budget else 0,
            **_budget_metadata(state_path, budget_date)}
        _save_progress(state_path, summary, budget_date)
        if budget:
            budget.state = read_json(state_path, {})
    complete = sum(case['status'] == 'complete' for case in summary['cases'])
    has_evidence = any(case['coverage'] > 0 for case in summary['cases'])
    summary = {**summary, 'outcome': 'complete' if complete == 3 else 'partial' if has_evidence else 'unavailable',
        'actualAttempts': budget.used - before if budget else 0,
        **_budget_metadata(state_path, budget_date),
        'cases': sorted(summary['cases'], key=lambda case: ['positive', 'negative', 'zero'].index(case['case']))}
    _save_progress(state_path, summary, budget_date)
    return summary
