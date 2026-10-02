from datetime import datetime

import pytest

from scripts import prepare_finmind_budget as budget


@pytest.mark.parametrize('previous,current,recoveries', [
    ('2026-10-02', '2026-10-02', []),
    ('2026-10-02', '2026-10-03', ['2026-10-03']),
])
def test_budget_day_recovers_new_day_without_resetting_existing_cache(tmp_path, monkeypatch, capsys, previous, current, recoveries):
    cache = tmp_path / 'cache'
    cache.mkdir()
    ledger = cache / 'state.json'
    ledger.write_text('{"days":{"2026-10-02":{"attempts":299}}}')
    calls = []
    monkeypatch.setattr(budget, 'today_taipei', lambda: current)
    def recover(args):
        calls.append(args[args.index('--budget-date') + 1])
        print('checkpoint_artifacts_recovered=1')
        assert ledger.read_text() == '{"days":{"2026-10-02":{"attempts":299}}}'
        return 0
    monkeypatch.setattr(budget, 'restore_checkpoint', recover)
    assert budget.main(['--previous-date', previous, '--cache-dir', str(cache)]) == 0
    assert calls == recoveries
    assert capsys.readouterr().out == current + '\n'
    assert ledger.exists()


def test_new_day_recovery_failure_does_not_enable_supplement(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(budget, 'today_taipei', lambda: '2026-10-03')
    monkeypatch.setattr(budget, 'restore_checkpoint', lambda args: 1)
    assert budget.main(['--previous-date', '2026-10-02', '--cache-dir', str(tmp_path)]) == 1
    output = capsys.readouterr()
    assert output.out == ''
    assert 'current-day checkpoint recovery failed' in output.err


@pytest.mark.parametrize('previous', ['20261002', '2026-10-99', 'bad\nBUDGET_DATE=2026-10-03'])
def test_invalid_previous_budget_day_rejected_before_recovery(tmp_path, monkeypatch, capsys, previous):
    monkeypatch.setattr(budget, 'restore_checkpoint', lambda args: pytest.fail('recovery must not run'))
    assert budget.main(['--previous-date', previous, '--cache-dir', str(tmp_path)]) == 1
    assert capsys.readouterr().out == ''


def test_real_clock_uses_taipei_timezone(monkeypatch):
    class Clock:
        @staticmethod
        def now(zone):
            assert zone.key == 'Asia/Taipei'
            return datetime(2026, 10, 3, 0, 1, tzinfo=zone)
    monkeypatch.setattr(budget, 'datetime', Clock)
    assert budget.today_taipei() == '2026-10-03'
