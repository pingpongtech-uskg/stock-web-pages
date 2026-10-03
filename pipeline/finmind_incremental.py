"""Durable, gap-directed supplements to an existing official public snapshot.

The checkpoint is written before each HTTP attempt. Actions must retain the
whole cache directory even when subsequent refresh or publication fails.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from contextlib import contextmanager
import fcntl

from pipeline.finmind_client import BudgetExceeded, FinMindClient, FinMindError, SourceBlocked
from pipeline.financial_periods import dividend_period, normalized_date, normalized_period
from pipeline.growth_health import evaluate_growth_health, expected_revenue_month
from pipeline.health_inputs import merge_health_inputs, normalize_finmind_health_inputs
from pipeline.valuation import GROWTH_EXTREME_RATE_MAX, derive_stable_eps_growth, derive_ttm_eps

FINANCIAL = 'TaiwanStockFinancialStatements'
REVENUE = 'TaiwanStockMonthRevenue'
PER = 'TaiwanStockPER'
DIVIDEND = 'TaiwanStockDividend'
QUEUE_POLICY = 'valuation-chain-v1'


def current_taipei_day() -> str:
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    temporary.replace(path)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise FinMindError('FinMind checkpoint cannot be read; supplemental requests disabled') from exc


HOUR_SECONDS = 3600


@contextmanager
def budget_lock(path: Path):
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent.parent / ('.' + path.parent.name + '-finmind-budget.lock')
    with lock_path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _finite_time(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _checkpoint_time(state: dict[str, Any]) -> float | None:
    value = state.get('checkpointAt')
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError('Checkpoint requires timezone')
        return parsed.timestamp()
    except (ValueError, TypeError) as exc:
        raise FinMindError('Invalid FinMind checkpoint timestamp') from exc


def normalize_budget_state(state: Any, now: float) -> dict[str, Any]:
    """Validate v3 events or conservatively migrate counters with unknown timings."""
    if not isinstance(state, dict) or not isinstance(state.get('days'), dict):
        raise FinMindError('Invalid FinMind budget checkpoint')
    version = state.get('version', 2)
    if type(version) is not int or version not in {1, 2, 3}:
        raise FinMindError('Unsupported FinMind budget checkpoint')
    checkpoint_day = state.get('checkpointDay')
    if checkpoint_day is not None:
        try:
            if not isinstance(checkpoint_day, str) or date.fromisoformat(checkpoint_day).isoformat() != checkpoint_day:
                raise ValueError('Invalid checkpoint day')
        except (ValueError, TypeError) as exc:
            raise FinMindError('Invalid FinMind checkpoint day') from exc
    _checkpoint_time(state)
    if state.get('version') != 3:
        counts = []
        caps = []
        for day, record in state['days'].items():
            date.fromisoformat(day)
            if not isinstance(record, dict) or type(record.get('attempts')) is not int or not 0 <= record['attempts'] <= 300:
                raise FinMindError('Invalid FinMind legacy attempt count')
            counts.append(record['attempts'])
            cap = record.get('projectCap', record.get('ceiling', 300) if state.get('version', 2) == 2 else 300)
            if type(cap) is not int or not 1 <= cap <= 300:
                raise FinMindError('Invalid FinMind legacy project cap')
            caps.append(cap)
        total = sum(counts)
        saved = _checkpoint_time(state)
        until = (saved if saved is not None else now) + HOUR_SECONDS
        fingerprint = hashlib.sha256(json.dumps(state['days'], sort_keys=True).encode()).hexdigest()
        debt = [{'id': fingerprint, 'count': min(300, total), 'until': until,
                 'unknown': saved is None}] if total else []
        rolling = {'events': [], 'totalAttempts': total, 'projectCap': min(caps, default=300), 'legacyDebt': debt}
        latest_day = state.get('checkpointDay') or max(state['days'], default='')
        latest = state['days'].get(latest_day, {})
        if latest.get('quotaKnown'):
            old_ceiling = latest.get('accountCeiling', latest.get('ceiling') if state.get('version') == 1 else None)
            if old_ceiling is not None:
                if type(old_ceiling) is not int or old_ceiling < 0:
                    raise FinMindError('Invalid FinMind legacy account ceiling')
                rolling = {**rolling, 'accountCeiling': total + max(0, old_ceiling - latest['attempts']),
                           'observedAt': saved if saved is not None else now,
                           'quotaCheckedAt': datetime.fromtimestamp(saved if saved is not None else now, timezone.utc).isoformat(),
                           'quotaWindowId': 'legacy-' + fingerprint,
                           **{key: latest[key] for key in ('accountLimit', 'accountUsed') if key in latest}}
        if latest.get('blocked'):
            rolling = {**rolling, 'blocked': latest['blocked'],
                       'blockedAt': saved if saved is not None else now,
                       'retryAfterSeconds': latest.get('retryAfterSeconds'),
                       'retryNotBefore': state.get('retryNotBefore', 0)}
        state = {**state, 'version': 3, 'rollingHour': rolling}
    rolling = state.get('rollingHour')
    if not isinstance(rolling, dict) or type(rolling.get('totalAttempts')) is not int or rolling['totalAttempts'] < 0:
        raise FinMindError('Invalid FinMind rolling total')
    if type(rolling.get('projectCap')) is not int or not 1 <= rolling['projectCap'] <= 300:
        raise FinMindError('Invalid FinMind rolling cap')
    events, debts = rolling.get('events'), rolling.get('legacyDebt')
    if not isinstance(events, list) or not isinstance(debts, list):
        raise FinMindError('Invalid FinMind rolling event list')
    seen = set()
    for event in events:
        if (not isinstance(event, dict) or not isinstance(event.get('id'), str) or not event['id'] or
            event['id'] in seen or not _finite_time(event.get('at'))):
            raise FinMindError('Invalid FinMind rolling attempt')
        seen.add(event['id'])
    if len(events) > rolling['totalAttempts']:
        raise FinMindError('FinMind event total mismatch')
    for debt in debts:
        if (not isinstance(debt, dict) or not isinstance(debt.get('id'), str) or
            type(debt.get('count')) is not int or not 0 <= debt['count'] <= 300 or
            not _finite_time(debt.get('until')) or type(debt.get('unknown')) is not bool):
            raise FinMindError('Invalid FinMind legacy debt')
    for key in ('accountCeiling', 'accountLimit', 'accountUsed'):
        if key in rolling and (type(rolling[key]) is not int or rolling[key] < 0):
            raise FinMindError('Invalid FinMind quota observation')
    for key in ('observedAt', 'lastClock', 'retryNotBefore', 'blockedAt', 'retryAfterSeconds'):
        if key in {'observedAt', 'retryAfterSeconds'} and rolling.get(key) is None:
            continue
        if key in rolling and not _finite_time(rolling[key]):
            raise FinMindError('Invalid FinMind quota clock')
    if not _finite_time(state.get('retryNotBefore', 0)):
        raise FinMindError('Invalid FinMind source retry clock')
    if rolling.get('quotaWindowId') is not None and (not isinstance(rolling['quotaWindowId'], str) or not rolling['quotaWindowId']):
        raise FinMindError('Invalid FinMind quota cohort identity')
    if rolling.get('blocked') is not None and not isinstance(rolling['blocked'], str):
        raise FinMindError('Invalid FinMind source block')
    if rolling.get('quotaCheckedAt') is not None:
        _checkpoint_time({'checkpointAt': rolling['quotaCheckedAt']})
    return state


class DailyBudget:
    """Compatibility name for the durable shared 300-attempt rolling-hour budget."""
    def __init__(self, path: Path, budget_date: str, *, hard_cap: int = 300) -> None:
        date.fromisoformat(budget_date)
        if type(hard_cap) is not int or not 1 <= hard_cap <= 300:
            raise ValueError('FinMind project hourly cap must be between 1 and 300')
        self.path, self.day, self.hard_cap = path, budget_date, hard_cap
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Sibling lock stays outside the state.json/rows.json artifact allowlist.
        with self._locked():
            self._load()
            self.record = {**self.record, 'projectCap': min(hard_cap, self.record['projectCap'])}
            self.save()

    def _locked(self):
        return budget_lock(self.path)

    def _load(self) -> None:
        self.state = normalize_budget_state(read_json(self.path, {'version': 2, 'days': {}, 'queue': []}), time.time())
        self.record = self.state['rollingHour']

    @property
    def used(self) -> int:
        return self.record['totalAttempts']

    @property
    def rolling_used(self) -> int:
        cutoff = time.time() - HOUR_SECONDS
        events = sum(event['at'] > cutoff for event in self.record['events'])
        debt = sum(item['count'] for item in self.record['legacyDebt'] if item['until'] > time.time())
        return events + debt

    @property
    def quota_fresh(self) -> bool:
        observed = self.record.get('observedAt')
        return observed is not None and 0 <= time.time() - observed < HOUR_SECONDS

    @property
    def account_remaining(self) -> int | None:
        if not self.quota_fresh or 'accountCeiling' not in self.record:
            return None
        return max(0, self.record['accountCeiling'] - self.used)

    @property
    def allowance(self) -> int:
        return self.used + min(max(0, self.record['projectCap'] - self.rolling_used), self.account_remaining or 0)

    def save(self) -> None:
        self.state = {**self.state, 'version': 3, 'rollingHour': self.record,
                      'checkpointDay': self.day,
                      'checkpointAt': datetime.fromtimestamp(time.time(), timezone.utc).isoformat()}
        atomic_json(self.path, self.state)

    def consume(self, *, require_known: bool = False) -> None:
        import uuid
        with self._locked():
            self._load()
            now = time.time()
            if now < self.record.get('lastClock', 0):
                raise BudgetExceeded('FinMind clock moved backwards; retain checkpoint')
            if any(item['unknown'] and item['until'] > now for item in self.record['legacyDebt']):
                raise BudgetExceeded('FinMind legacy attempt timestamps unknown; wait for safe expiry')
            if self.rolling_used >= self.record['projectCap']:
                raise BudgetExceeded('FinMind rolling-hour project allowance exhausted')
            until = self.record.get('retryNotBefore', self.state.get('retryNotBefore', 0))
            blocked = self.record.get('blocked')
            if now < until or (blocked and require_known):
                raise SourceBlocked('FinMind source backoff remains blocked')
            if blocked and not require_known and self.record.get('retryAfterSeconds') is None and now - self.record.get('blockedAt', now) < HOUR_SECONDS:
                raise SourceBlocked('FinMind source recovery requires a fresh hourly quota check')
            if require_known and not self.quota_fresh:
                raise FinMindError('FinMind account quota observation expired or unavailable')
            if self.quota_fresh and self.account_remaining == 0:
                raise BudgetExceeded('FinMind account observation allowance exhausted')
            events = [event for event in self.record['events'] if event['at'] > now - 2 * HOUR_SECONDS]
            self.record = {**self.record, 'events': [*events, {'id': uuid.uuid4().hex, 'at': now}],
                           'totalAttempts': self.used + 1, 'lastClock': now}
            self.save()

    def configure(self, account_limit: int, account_used: int, *, checks_started_at: int = 0) -> None:
        import uuid
        if type(account_limit) is not int or type(account_used) is not int or account_limit <= 0 or account_used < 0:
            raise FinMindError('Invalid FinMind account quota')
        with self._locked():
            self._load()
            candidate = checks_started_at + math.floor(max(0, account_limit - account_used) * 0.8)
            previous = self.record.get('accountCeiling')
            reset = 'accountUsed' in self.record and account_used < self.record['accountUsed']
            # A fresh server observation can fund a later cohort even when its
            # counter equals the original observation (e.g. zero in both hours).
            # Time alone cannot renew: every previously charged attempt and
            # unknown legacy cohort must have aged out before this quota check.
            checks = max(0, self.used - checks_started_at)
            previous_events = self.record['events'][:-checks] if checks else self.record['events']
            previous_basis = self.record.get('observedAt')
            if previous_basis is None:
                previous_basis = self.record.get('blockedAt')
            cohort_expired = (not self.quota_fresh and previous_basis is not None and
                              time.time() - previous_basis >= HOUR_SECONDS and
                              all(event['at'] <= time.time() - HOUR_SECONDS for event in previous_events) and
                              all(item['until'] <= time.time() for item in self.record['legacyDebt']))
            reset = reset or cohort_expired
            ceiling = candidate if previous is None or reset else min(previous, candidate)
            self.record = {**self.record, 'accountLimit': account_limit, 'accountUsed': account_used,
                           'accountCeiling': ceiling, 'observedAt': time.time(),
                           'quotaWindowId': uuid.uuid4().hex if previous is None or reset else self.record.get('quotaWindowId'),
                           'quotaCheckedAt': datetime.fromtimestamp(time.time(), timezone.utc).isoformat()}
            if account_used < account_limit and (not self.record.get('blocked') or reset):
                self.record = {**self.record, 'blocked': None, 'retryAfterSeconds': None}
            self.save()

    def block(self, reason: str, retry_after: float | None = None) -> None:
        with self._locked():
            self._load()
            self.record = {**self.record, 'blocked': reason, 'blockedAt': time.time(), 'retryAfterSeconds': retry_after,
                           'retryNotBefore': max(self.record.get('retryNotBefore', 0), time.time() + (retry_after or 0))}
            self.save()

    def queue(self, jobs: list[dict[str, str]]) -> None:
        with self._locked():
            metadata = {key: self.state[key] for key in ('queuePolicy', 'lastResult') if key in self.state}
            self._load()
            self.state = {**self.state, 'queue': jobs, **metadata}
            self.save()

    def update_metadata(self, changes: dict[str, Any]) -> None:
        if set(changes) - {'institutionalProbe', 'lastResult', 'queuePolicy'}:
            raise FinMindError('Budget metadata update cannot replace request authority')
        with self._locked():
            self._load()
            self.state = {**self.state, **changes}
            self.save()


def financial_period(end: date) -> str:
    """Latest period whose ordinary filing deadline has passed."""
    for month, day, quarter in ((11, 15, 3), (8, 15, 2), (5, 15, 1), (3, 31, 4)):
        if (end.month, end.day) >= (month, day):
            return f'{end.year if quarter != 4 else end.year - 1}-Q{quarter}'
    return f'{end.year - 1}-Q3'


def merge_raw_rows(base: list[dict[str, Any]], overlay: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = {}
    for row in [*base, *overlay]:
        if not isinstance(row, dict):
            continue
        key = (str(row.get('date') or ''), str(row.get('type') or ''), str(row.get('revenue_year') or ''), str(row.get('revenue_month') or ''), str(row.get('year') or ''))
        rows[key] = {**rows.get(key, {}), **row}
    return [rows[key] for key in sorted(rows)]


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def complete_dividend(rows: list[dict[str, Any]], year: int, as_of: str) -> bool:
    periods = set()
    for row in rows:
        parsed = dividend_period(row.get('period') or row.get('year'), row.get('year'))
        cash = number(row.get('cashPerShare'))
        dates = [normalized_date(row[field]) for field in ('approvedAt', 'publishedAt', 'availableAt', 'exDate', 'exDividendDate') if row.get(field) not in (None, '')]
        if row.get('confirmed') is not True or cash is None or cash < 0 or parsed is None or not dates or any(day is None or len(day) != 10 or day > as_of for day in dates):
            continue
        if parsed[0] == year:
            periods.add(parsed[1])
    return 'annual' in periods or periods == {'Q1', 'Q2', 'Q3', 'Q4'} or periods == {'H1', 'H2'}


def plan_gaps(details: list[dict[str, Any]], cache: dict[str, Any], as_of: str, *, budget_date: str | None = None) -> list[dict[str, str]]:
    from pipeline.valuation import derive_growth_inputs

    end = date.fromisoformat(as_of)
    retry_day = budget_date or as_of
    jobs = []
    for detail in sorted(details, key=lambda item: item['code']):
        code, health = detail['code'], detail.get('healthInputs') or {}
        income = health.get('incomeQuarterly') or []
        valuation = derive_growth_inputs(detail)
        validated_income = valuation['rows']
        same_day = valuation['cutoff'] == as_of
        safe_pe = same_day and number(valuation['current_pe']) is not None and valuation['current_pe'] > 0
        growth = valuation['growth'].get('growth')
        closes_valuation = safe_pe and valuation['ttm_eps'] is not None and growth is not None and 0 < growth <= GROWTH_EXTREME_RATE_MAX
        growth_health = evaluate_growth_health(health.get('monthlyRevenueOfficial') or [],
                                               [*income, *(health.get('incomeYtd') or [])], as_of=as_of)
        due_year, due_quarter = financial_period(end).split('-Q')
        latest_period = max((normalized_period(row) for row in income if normalized_period(row) is not None), default=(0, 0))
        financial_missing = (latest_period < (int(due_year), int(due_quarter)) or derive_ttm_eps(validated_income, as_of=as_of) is None or derive_stable_eps_growth(validated_income, as_of=as_of).get('growth') is None
                             or any(check['status'] == 'unknown' for check in growth_health['checks'][1:]))
        requests = [
            (FINANCIAL, financial_missing, financial_period(end), f'{end.year - 4}-01-01'),
            (PER, not safe_pe, as_of, (end - timedelta(days=10)).isoformat()),
            (DIVIDEND, not complete_dividend(health.get('dividends') or [], end.year - 1, as_of), str(end.year), f'{end.year - 1}-01-01'),
            (REVENUE, growth_health['checks'][0]['status'] == 'unknown', expected_revenue_month(as_of, health.get('monthlyRevenueOfficial') or []), (end - timedelta(days=550)).isoformat()),
        ]
        for priority, (dataset, missing, period, start) in enumerate(requests):
            stored = cache.get(f'{code}:{dataset}') or {}
            checked = stored.get('checkedPeriod') == period
            next_check = stored.get('nextCheckAt')
            if not missing or (checked and not next_check):
                continue
            history_complete = derive_stable_eps_growth(validated_income, as_of=as_of).get('valid_years', 0) >= 4
            if dataset == FINANCIAL and history_complete and stored.get('rows'):
                dates = [row['date'] for row in stored['rows'] if isinstance(row, dict) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(row.get('date') or ''))]
                if dates:
                    start = max(dates)
            jobs.append({'code': code, 'dataset': dataset, 'period': period, 'start_date': start,
                         'end_date': as_of, 'priority': '0' if dataset == DIVIDEND and closes_valuation else str(priority + 1),
                         **({'notBefore': next_check} if checked and next_check and next_check > retry_day else {})})
    return sorted(jobs, key=lambda job: (job['priority'], job['code']))


def job_key(job: dict[str, str]) -> tuple[str, str, str]:
    return job['code'], job['dataset'], job['period']


def resume_queue(planned: list[dict[str, str]], pending: list[dict[str, str]]) -> list[dict[str, str]]:
    """Promote untried closing chains; retain FIFO for deferred and failed jobs."""
    available = {job_key(job): job for job in planned}
    retained = [{**available[job_key(job)], **({'attempted': 'true'} if job.get('attempted') else {})}
                for job in pending if job_key(job) in available]
    retained_keys = {job_key(job) for job in retained}
    added = [job for job in planned if job_key(job) not in retained_keys]
    urgent = [job for job in [*retained, *added] if job['priority'] == '0' and not job.get('attempted')]
    urgent_keys = {job_key(job) for job in urgent}
    return [*urgent, *(job for job in [*retained, *added] if job_key(job) not in urgent_keys)]


def normalize_supplement(detail: dict[str, Any], cache: dict[str, Any], as_of: str) -> dict[str, Any]:
    code = detail['code']
    financial = detail.get('financialInputs') or {}
    income = (cache.get(f'{code}:{FINANCIAL}') or {}).get('rows') or []
    financial = {**financial, 'incomeStatement': merge_raw_rows(financial.get('incomeStatement') or [], income)}
    revenue = (cache.get(f'{code}:{REVENUE}') or {}).get('rows') or []
    retrieved = max((str(entry.get('fetchedAt') or '') for key, entry in cache.items() if key.startswith(f'{code}:')), default='') or None
    normalized = normalize_finmind_health_inputs(financial, [*(detail.get('revenueMonthly') or []), *revenue], fetched_at=retrieved)
    health = merge_health_inputs(detail.get('healthInputs'), normalized)
    per = (cache.get(f'{code}:{PER}') or {}).get('rows') or []
    usable = [row for row in per if number(row.get('PER')) is not None and str(row.get('date') or '') <= as_of]
    existing = health.get('valuationCurrent') or {}
    if usable and (number(existing.get('pe')) is None or str(existing.get('date') or '') < max(str(row.get('date') or '') for row in usable)):
        row = max(usable, key=lambda item: str(item.get('date') or ''))
        health = {**health, 'valuationCurrent': {'date': row['date'], 'pe': number(row.get('PER')),
                  'pb': number(row.get('PBR')), 'dividendYield': number(row.get('dividend_yield')), 'source': f'FinMind:{PER}'}}
    raw_dividends = (cache.get(f'{code}:{DIVIDEND}') or {}).get('rows') or []
    if raw_dividends:
        financial = {**financial, 'dividend': merge_raw_rows(financial.get('dividend') or [], raw_dividends)}
    dividends = []
    for row in (cache.get(f'{code}:{DIVIDEND}') or {}).get('rows') or []:
        earnings, surplus = number(row.get('CashEarningsDistribution')), number(row.get('CashStatutorySurplus'))
        announced = str(row.get('AnnouncementDate') or '')
        ex_date = str(row.get('CashExDividendTradingDate') or '')
        if earnings is None or surplus is None or not announced or announced > as_of or not ex_date:
            continue
        parsed_period = dividend_period(row.get('year'))
        if parsed_period is None:
            continue
        year, period = parsed_period
        dividends.append({'year': str(year), 'period': period, 'cashPerShare': earnings + surplus,
                          'stockPerShare': (number(row.get('StockEarningsDistribution')) or 0) + (number(row.get('StockStatutorySurplus')) or 0),
                          'availableAt': announced, 'exDividendDate': ex_date, 'source': f'FinMind:{DIVIDEND}', 'confirmed': True})
    health = merge_health_inputs(health, {'dividends': dividends})
    return {**detail, 'financialInputs': financial, 'healthInputs': health}


def supplement_snapshot(codes: list[str], output: Path, as_of: str | None = None, *, cache_dir: Path,
                        budget_date: str, token: str | None = None, max_requests: int = 300,
                        max_runtime_seconds: int = 1500) -> dict[str, Any]:
    as_of = as_of or budget_date
    date.fromisoformat(as_of)
    state = DailyBudget(cache_dir / 'state.json', budget_date, hard_cap=max_requests)
    attempts_before = state.used
    cache = read_json(cache_dir / 'rows.json', {})
    if not isinstance(cache, dict):
        raise FinMindError('Invalid FinMind row cache; supplemental requests disabled')
    latest = read_json(output / 'latest.json', {})
    run_id = latest.get('runId')
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9._-]+', run_id):
        raise FinMindError('Public snapshot missing; run official refresh before FinMind supplement')
    paths = {code: output / 'releases' / run_id / 'stocks' / f'{code}.json' for code in codes if re.fullmatch(r'\d{4,6}', code)}
    details = [read_json(path, {}) for path in paths.values() if path.exists()]
    details = [item for item in details if item.get('code') in paths]
    # Rehydrate durable cached history before deciding which inputs are missing.
    merged = [normalize_supplement(item, cache, as_of) for item in details]
    pending = state.state.get('queue', []) if state.state.get('queuePolicy') == QUEUE_POLICY else []
    jobs = resume_queue(plan_gaps(merged, cache, as_of, budget_date=budget_date), pending)
    state.state = {**state.state, 'queuePolicy': QUEUE_POLICY}
    state.queue(jobs)
    skipped, completed = None, 0
    failed_jobs = []
    deferred_jobs = []
    token = os.environ.get('FINMIND_TOKEN', '') if token is None else token
    started = time.monotonic()
    if not token.strip():
        skipped = 'missing_token'
    elif any(job.get('notBefore', '') <= budget_date for job in jobs):
        client = FinMindClient(token, hard_cap=max_requests, daily_budget=state)
        try:
            client.configure_account_budget()
            while jobs:
                if time.monotonic() - started >= max_runtime_seconds:
                    skipped = 'runtime_limit'
                    break
                job = jobs[0]
                if job.get('notBefore', '') > budget_date:
                    deferred_jobs = [*deferred_jobs, {**job, 'attempted': 'true'}]
                    jobs = jobs[1:]
                    state.queue([*jobs, *deferred_jobs, *failed_jobs])
                    continue
                try:
                    rows = client.get(job['dataset'], data_id=job['code'], start_date=job['start_date'], end_date=job['end_date'])
                except (BudgetExceeded, SourceBlocked):
                    raise
                except FinMindError:
                    # Retain unsuccessful jobs for recovery, without a tight retry loop.
                    skipped = 'dataset_unavailable'
                    failed_jobs = [*failed_jobs, {**job, 'attempted': 'true'}]
                    jobs = jobs[1:]
                    state.queue([*jobs, *deferred_jobs, *failed_jobs])
                    continue
                key = f"{job['code']}:{job['dataset']}"
                stored = {name: value for name, value in (cache.get(key) or {}).items() if name != 'nextCheckAt'}
                cache = {**cache, key: {**stored, 'rows': merge_raw_rows(stored.get('rows') or [], rows),
                         'checkedPeriod': job['period'], 'checkedAt': budget_date, 'fetchedAt': datetime.now(timezone.utc).isoformat()}}
                updated = normalize_supplement(next(item for item in details if item['code'] == job['code']), cache, as_of)
                unresolved = any(item['dataset'] == job['dataset'] for item in plan_gaps([updated], {}, as_of, budget_date=budget_date))
                if unresolved:
                    cache = {**cache, key: {**cache[key], 'nextCheckAt': (date.fromisoformat(budget_date) + timedelta(days=7)).isoformat()}}
                atomic_json(cache_dir / 'rows.json', cache)
                refreshed = [normalize_supplement(item, cache, as_of) for item in details]
                parked_keys = {job_key(item) for item in [*failed_jobs, *deferred_jobs]}
                planned = [item for item in plan_gaps(refreshed, cache, as_of, budget_date=budget_date) if job_key(item) not in parked_keys]
                jobs = resume_queue(planned, jobs[1:])
                state.queue([*jobs, *deferred_jobs, *failed_jobs])
                completed += 1
        except (BudgetExceeded, SourceBlocked, FinMindError) as exc:
            skipped = type(exc).__name__
    elif jobs:
        skipped = 'deferred'
    jobs = [*jobs, *deferred_jobs, *failed_jobs]
    # Never replace the tracked universe with only the subset fetched today.
    changed = 0
    for original in details:
        updated = normalize_supplement(original, cache, as_of)
        if updated != original and any(key.startswith(f"{original['code']}:") for key in cache):
            atomic_json(paths[original['code']], updated)
            changed += 1
    result = {'run_id': run_id, 'stocks': len(details), 'updated': changed, 'completed': completed,
              'queued': len(jobs), 'requests': state.rolling_used,
              'allowed_attempts': state.rolling_used + max(0, state.allowance - state.used),
              'actual_attempts': state.used - attempts_before, 'skipped': skipped}
    state.state = {**state.state, 'lastResult': result}
    state.queue(jobs)
    return result
