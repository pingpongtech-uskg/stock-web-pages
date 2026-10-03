"""Clock-driven regressions for the shared rolling-hour HTTP allowance."""
import json

import pytest

from pipeline.finmind_client import BudgetExceeded, FinMindError
from pipeline.finmind_incremental import DailyBudget


@pytest.fixture
def clock(monkeypatch):
    instant = [1790956799.0]
    monkeypatch.setattr('pipeline.finmind_incremental.time.time', lambda: instant[0])
    return instant


def test_project_cap_is_sliding_and_midnight_never_renews_it(tmp_path, clock):
    budget = DailyBudget(tmp_path / 'state.json', '2026-10-02', hard_cap=3)
    budget.configure(600, 0)
    for _ in range(3):
        budget.consume(require_known=True)
    clock[0] += 2
    recovered = DailyBudget(budget.path, '2026-10-03', hard_cap=3)
    with pytest.raises(BudgetExceeded):
        recovered.consume(require_known=True)
    clock[0] += 3598
    with pytest.raises(FinMindError, match='expired'):
        recovered.consume(require_known=True)
    recovered.consume()  # Only a metered quota check may cross an expired observation.
    recovered.configure(600, 1, checks_started_at=3)
    recovered.consume(require_known=True)
    assert recovered.used == 5 and recovered.rolling_used == 2


def test_staggered_attempts_expire_individually(tmp_path, clock):
    budget = DailyBudget(tmp_path / 'state.json', '2026-10-02', hard_cap=2)
    budget.consume()
    clock[0] += 1800
    budget.consume()
    clock[0] += 1800
    budget.consume()
    assert budget.rolling_used == 2 and budget.used == 3
    with pytest.raises(BudgetExceeded):
        budget.consume()


def test_same_count_within_window_does_not_renew_and_lower_count_confirms_reset(tmp_path, clock):
    budget = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    budget.configure(10, 5)
    for _ in range(3):
        budget.consume(require_known=True)
    budget.consume()
    budget.configure(10, 5, checks_started_at=3)
    with pytest.raises(BudgetExceeded):
        budget.consume(require_known=True)
    clock[0] += 3600
    budget.consume()
    budget.configure(10, 0, checks_started_at=4)
    budget.consume(require_known=True)
    assert budget.account_remaining == 6


def test_quota_checks_consume_observed_allocation_and_are_bounded(tmp_path, clock):
    budget = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    budget.configure(10, 5)
    for _ in range(4):
        budget.consume()
    with pytest.raises(BudgetExceeded):
        budget.consume()
    assert budget.used == 4


def test_equal_zero_usage_renews_only_after_charged_cohort_has_expired(tmp_path, clock):
    budget = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    budget.consume()
    budget.configure(600, 0, checks_started_at=0)
    for _ in range(299):
        budget.consume(require_known=True)
    first_ceiling = budget.record['accountCeiling']
    clock[0] += 3601
    budget.consume()
    budget.configure(600, 0, checks_started_at=300)
    assert budget.record['accountCeiling'] == 780
    budget.consume(require_known=True)
    budget.consume()
    budget.configure(600, 0, checks_started_at=302)
    assert budget.record['accountCeiling'] == 780 and first_ceiling == 480


def test_legacy_unknown_timestamp_blocks_and_migration_never_restarts_timer(tmp_path, clock):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'version': 2, 'days': {'2026-10-02': {'attempts': 9, 'ceiling': 300}}, 'queue': ['preserved']}))
    budget = DailyBudget(path, '2026-10-03')
    with pytest.raises(BudgetExceeded, match='legacy'):
        budget.consume()
    clock[0] += 3599
    recovered = DailyBudget(path, '2026-10-04')
    with pytest.raises(BudgetExceeded):
        recovered.consume()
    clock[0] += 1
    recovered.consume()
    assert recovered.used == 10
    assert json.loads(path.read_text())['queue'] == ['preserved']


def test_credible_legacy_recent_count_is_debt_and_old_count_expires(tmp_path, clock):
    from datetime import datetime, timezone
    path = tmp_path / 'state.json'
    saved = datetime.fromtimestamp(clock[0], timezone.utc).isoformat()
    path.write_text(json.dumps({'version': 2, 'checkpointAt': saved, 'days': {'2026-10-02': {'attempts': 299, 'ceiling': 300}}}))
    budget = DailyBudget(path, '2026-10-03')
    budget.consume()
    with pytest.raises(BudgetExceeded):
        budget.consume()
    clock[0] += 3600
    recovered = DailyBudget(path, '2026-10-04')
    recovered.consume()
    assert recovered.rolling_used == 1 and recovered.used == 301


def test_two_live_budget_instances_cannot_overwrite_each_others_attempts(tmp_path, clock):
    path = tmp_path / 'state.json'
    first = DailyBudget(path, '2026-10-02', hard_cap=2)
    second = DailyBudget(path, '2026-10-02', hard_cap=2)
    first.consume()
    second.consume()
    with pytest.raises(BudgetExceeded):
        first.consume()
    assert DailyBudget(path, '2026-10-02', hard_cap=2).used == 2


def test_legacy_known_account_allowance_and_block_survive_migration(tmp_path, clock):
    from datetime import datetime, timezone
    from pipeline.finmind_client import SourceBlocked
    saved = datetime.fromtimestamp(clock[0], timezone.utc).isoformat()
    path = tmp_path / 'state.json'
    record = {'attempts': 3, 'ceiling': 300, 'quotaKnown': True,
              'accountLimit': 10, 'accountUsed': 5, 'accountCeiling': 4}
    path.write_text(json.dumps({'version': 2, 'checkpointAt': saved, 'days': {'2026-10-02': record}}))
    budget = DailyBudget(path, '2026-10-03')
    budget.consume()
    budget.configure(10, 5, checks_started_at=3)
    with pytest.raises(BudgetExceeded):
        budget.consume(require_known=True)
    blocked_path = tmp_path / 'blocked.json'
    blocked_path.write_text(json.dumps({'version': 2, 'checkpointAt': saved,
        'days': {'2026-10-02': {**record, 'blocked': 'HTTP 429', 'retryAfterSeconds': None}}}))
    blocked = DailyBudget(blocked_path, '2026-10-03')
    with pytest.raises(SourceBlocked):
        blocked.consume()
    clock[0] += 3601
    blocked.consume()
    with pytest.raises(SourceBlocked):
        blocked.consume(require_known=True)
    blocked.configure(600, 0, checks_started_at=3)
    blocked.consume(require_known=True)


def test_legacy_unknown_quota_block_recovers_after_one_hour_and_fresh_observation(tmp_path, clock):
    from datetime import datetime, timezone
    from pipeline.finmind_client import SourceBlocked
    saved = datetime.fromtimestamp(clock[0], timezone.utc).isoformat()
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'version': 2, 'checkpointAt': saved, 'days': {
        '2026-10-02': {'attempts': 1, 'ceiling': 300, 'blocked': 'HTTP 429'}}}))
    budget = DailyBudget(path, '2026-10-03')
    with pytest.raises(SourceBlocked):
        budget.consume()
    clock[0] += 3601
    budget.consume()
    budget.configure(600, 0, checks_started_at=1)
    budget.consume(require_known=True)
    assert budget.used == 3


def test_tighter_legacy_project_cap_is_preserved(tmp_path, clock):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'version': 2, 'days': {'2026-10-02': {'attempts': 0, 'ceiling': 2}}}))
    budget = DailyBudget(path, '2026-10-03')
    budget.consume(); budget.consume()
    with pytest.raises(BudgetExceeded):
        budget.consume()


def test_progress_and_attempt_writers_share_same_lock(tmp_path, clock):
    from concurrent.futures import ThreadPoolExecutor
    from pipeline.institutional_probe import _save_progress
    path = tmp_path / 'state.json'
    budget = DailyBudget(path, '2026-10-02')
    def attempts():
        for _ in range(20): budget.consume()
    def summaries():
        for index in range(20): _save_progress(path, {'fixture': index}, '2026-10-02')
    with ThreadPoolExecutor(max_workers=2) as workers:
        for future in (workers.submit(attempts), workers.submit(summaries)):
            future.result()
    recovered = DailyBudget(path, '2026-10-02')
    assert recovered.used == 20 and recovered.rolling_used == 20
    assert recovered.state['institutionalProbe'] == {'fixture': 19}


@pytest.mark.parametrize('bad', [float('nan'), -1, True])
def test_invalid_event_timestamps_fail_closed(tmp_path, clock, bad):
    path = tmp_path / 'state.json'
    path.write_text(json.dumps({'version': 3, 'days': {}, 'rollingHour': {
        'events': [{'id': 'fixture', 'at': bad}], 'totalAttempts': 1, 'projectCap': 300, 'legacyDebt': []}}))
    with pytest.raises(FinMindError):
        DailyBudget(path, '2026-10-02')


@pytest.mark.parametrize('field,value', [('lastClock', None), ('retryNotBefore', None),
    ('blockedAt', None), ('quotaWindowId', 42), ('quotaWindowId', ''), ('retryAfterSeconds', -1)])
def test_malformed_rolling_metadata_fails_closed_at_load(tmp_path, clock, field, value):
    path = tmp_path / 'state.json'
    record = {'events': [], 'totalAttempts': 0, 'projectCap': 300, 'legacyDebt': [], field: value}
    path.write_text(json.dumps({'version': 3, 'days': {}, 'rollingHour': record}))
    with pytest.raises(FinMindError): DailyBudget(path, '2026-10-02')


@pytest.mark.parametrize('changes', [{'version': []}, {'version': True}, {'checkpointDay': []},
    {'checkpointDay': '20261002'}, {'checkpointAt': 'unknown'}, {'checkpointAt': '2026-10-02T00:00:00'}])
def test_malformed_checkpoint_envelope_fails_before_any_write(tmp_path, clock, changes):
    path = tmp_path / 'state.json'
    state = {'version': 3, 'days': {}, 'rollingHour': {
        'events': [], 'totalAttempts': 0, 'projectCap': 300, 'legacyDebt': []}, **changes}
    original = json.dumps(state)
    path.write_text(original)
    with pytest.raises(FinMindError): DailyBudget(path, '2026-10-02')
    assert path.read_text() == original


def test_client_run_cap_survives_rolling_hour_expiry(tmp_path, clock, monkeypatch):
    from pipeline.finmind_client import FinMindClient
    from io import BytesIO
    budget = DailyBudget(tmp_path / 'state.json', '2026-10-02')
    calls = []
    def respond(request, **kwargs):
        calls.append(request.full_url)
        payload = {'api_request_limit': 600, 'user_count': 0} if 'user_info' in request.full_url else {'status': 200, 'data': []}
        return BytesIO(json.dumps(payload).encode())
    monkeypatch.setattr('urllib.request.urlopen', respond)
    client = FinMindClient('fixture', hard_cap=2, daily_budget=budget, min_interval=0)
    client.configure_account_budget()
    client.get('fixture')
    clock[0] += 3601
    with pytest.raises(BudgetExceeded): client.configure_account_budget()
    assert len(calls) == 2 and budget.used == 2
