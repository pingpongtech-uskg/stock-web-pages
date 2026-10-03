"""Guard the manually dispatched probe's budget and publication boundaries."""
from pathlib import Path
import re
import os
import subprocess
import sys

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/daily.yml'


def sections():
    text = WORKFLOW.read_text()
    jobs = text.split('\njobs:\n', 1)[1]
    assert '\n  institutional_probe:\n' in jobs, 'isolated institutional probe job is missing'
    snapshot, probe = jobs.split('\n  institutional_probe:\n', 1)
    return text, snapshot, probe


def test_manual_choice_and_exact_job_guards():
    text, snapshot, probe = sections()
    assert re.search(r'source_mode:\n.*?type: choice\n.*?default: publish\n.*?options:\n.*?- publish\n.*?- institutional_probe', text, re.S)
    assert "inputs.source_mode == 'publish' || inputs.source_mode == ''" in snapshot
    assert "github.ref == 'refs/heads/main' && inputs.source_mode == 'institutional_probe'" in probe
    assert 'group: daily-snapshot' in text
    assert 'cancel-in-progress: false' in text
    assert '\n  schedule:' not in text


def test_probe_validates_inputs_and_identifies_exact_source():
    _, snapshot, probe = sections()
    for job in (snapshot, probe):
        assert 'SOURCE_MODE: ${{ inputs.source_mode }}' in job
        assert "in {'publish', 'institutional_probe'}" in job
        assert "date.fromisoformat(os.environ['MARKET_DATE'])" in job
        assert "re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}'" in job
    assert 'ref: ${{ github.sha }}' in probe
    assert 'SOURCE_GIT_COMMIT=$(git rev-parse HEAD)' in probe
    for field in ('requestId', 'marketDate', 'sourceGitCommit', 'actionsRunId', 'repository'):
        assert field in probe


def test_probe_shares_budget_restore_and_three_request_slice():
    _, _, probe = sections()
    assert 'finmind-v1-${{ env.BUDGET_DATE }}-' in probe
    assert 'finmind-v1-\n' in probe
    restore = probe.index('scripts/restore_finmind_checkpoint.py')
    prepare = probe.index('scripts/prepare_finmind_budget.py')
    fetch = probe.index('scripts/probe_institutional_history.py')
    assert restore < prepare < fetch
    assert '--calendar .cache/institutional-probe/trading-calendar.json' in probe
    assert '--max-data-requests 3' in probe
    assert '--budget-date "$BUDGET_DATE"' in probe
    assert '--cache-dir .cache/finmind' in probe
    assert 'timeout-minutes:' in probe


def test_probe_cannot_publish_or_change_tracked_universe():
    _, snapshot, probe = sections()
    assert 'Publish validated release to main' in snapshot
    for forbidden in ('git push', 'git commit', 'git add', 'npm ', 'screening-export', 'validated-static-release',
                      'fetch_research_universe.py', 'refresh_snapshot.py', 'config/tracked_symbols.json'):
        assert forbidden not in probe
    assert 'public/data' not in probe
    assert 'scripts/build_trading_calendar.py --market-date "$MARKET_DATE" --output .cache/institutional-probe/trading-calendar.json' in probe


def test_probe_preserves_budget_and_sanitized_summary_on_failure():
    _, _, probe = sections()
    for title in ('Persist probe checkpoint', 'Preserve checkpoint evidence', 'Preserve sanitized probe evidence'):
        block = probe.split('- name: ' + title, 1)[1].split('\n      - ', 1)[0]
        assert 'if: always()' in block
    assert 'name: finmind-checkpoint-${{ github.run_attempt }}' in probe
    assert 'name: institutional-probe' in probe
    assert 'path: .artifacts/institutional-probe' in probe


def test_finmind_secret_scoped_to_probe_step_and_never_printed():
    _, _, probe = sections()
    assert probe.count('FINMIND_TOKEN: ${{ secrets.FINMIND_TOKEN }}') == 1
    before, after = probe.split('- name: Probe institutional source within shared free budget', 1)
    assert 'FINMIND_TOKEN' not in before
    assert 'finmind_token_present=true' in after
    assert 'finmind_token_present=false' in after
    assert 'set -x' not in probe
    assert 'echo "$FINMIND_TOKEN"' not in probe
    assert 'printenv' not in probe


@pytest.mark.parametrize('overrides,valid', [
    ({}, True),
    ({'SOURCE_MODE': 'unknown'}, False),
    ({'SOURCE_MODE': 'publish'}, False),
    ({'REQUEST_ID': 'unsafe request'}, False),
    ({'MARKET_DATE': '2026-10-99'}, False),
])
def test_probe_boundary_validator_rejects_invalid_dispatch(overrides, valid):
    _, _, probe = sections()
    validator = probe.split("python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
    script = '\n'.join(line.removeprefix('          ') for line in validator.splitlines())
    env = {**os.environ, 'SOURCE_MODE': 'institutional_probe', 'REQUEST_ID': 'probe-20261002',
           'MARKET_DATE': '2026-10-02', **overrides}
    result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True)
    assert (result.returncode == 0) is valid


def test_probe_shell_blocks_have_valid_syntax():
    _, _, probe = sections()
    blocks = re.findall(r'        run: \|\n((?:          .*\n)+)', probe + '\n')
    assert len(blocks) == 3
    for block in blocks:
        script = '\n'.join(line.removeprefix('          ') for line in block.splitlines())
        result = subprocess.run(['bash', '-n'], input=script, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
