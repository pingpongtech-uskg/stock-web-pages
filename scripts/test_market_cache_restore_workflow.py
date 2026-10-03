"""Execute the dispatch validator and guard restoration before collection."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/daily.yml'
FIELDS = ['CACHE_RESTORE_COMMIT', 'CACHE_DESCRIPTOR_SHA256', 'CACHE_MARKET_DATE',
          'CACHE_SOURCE_GIT_COMMIT', 'CACHE_ACTIONS_RUN_ID', 'CACHE_REQUEST_ID']
RESTORE = dict(zip(FIELDS, ['a'*40, 'b'*64, '2026-10-01', 'c'*40, '123456', 'screening:20261001:v1']))


def snapshot():
    return WORKFLOW.read_text().split('\njobs:\n', 1)[1].split('\n  institutional_probe:\n', 1)[0]


@pytest.mark.parametrize('values,valid', [
    ({}, True), (RESTORE, True), ({'CACHE_RESTORE_COMMIT': 'a'*40}, False),
    ({**RESTORE, 'CACHE_RESTORE_COMMIT': 'main'}, False),
    ({**RESTORE, 'CACHE_DESCRIPTOR_SHA256': 'b'*63}, False),
    ({**RESTORE, 'CACHE_MARKET_DATE': '2026-10-03'}, False),
    ({**RESTORE, 'CACHE_MARKET_DATE': '2026-02-30'}, False),
    ({**RESTORE, 'CACHE_SOURCE_GIT_COMMIT': 'https://example.com'}, False),
    ({**RESTORE, 'CACHE_ACTIONS_RUN_ID': '12;echo'}, False),
    ({**RESTORE, 'CACHE_REQUEST_ID': 'unsafe request'}, False),
])
def test_restore_dispatch_boundary(values, valid):
    code = snapshot().split("python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
    code = '\n'.join(line.removeprefix('          ') for line in code.splitlines())
    env = {**os.environ, 'SOURCE_MODE': 'publish', 'REQUEST_ID': 'screening:20261002:v3',
           'MARKET_DATE': '2026-10-02', **dict.fromkeys(FIELDS, ''), **values}
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True)
    assert (result.returncode == 0) is valid


def test_restore_uses_main_code_before_live_collection_and_preserves_original_context():
    job = snapshot()
    assert job.index('Restore verified Notion operational cache') < job.index('Fetch authoritative exchange calendar')
    block = job.split('- name: Restore verified Notion operational cache', 1)[1].split('\n      - ', 1)[0]
    assert "if: inputs.restore_commit != ''" in block
    assert 'GITHUB_TOKEN: ${{ github.token }}' in block
    for field in FIELDS:
        assert field in block
    assert '--market-date="$MARKET_DATE"' in block
    assert 'ref: ${{ github.sha }}' in job
    assert '--stock-cache-dir .cache/restored-stock-details' in job
    assert 'git checkout' not in block and 'git push' not in block


def test_calendar_receives_original_restored_cache_before_window_collection():
    job = snapshot()
    calendar = job.split('- name: Fetch authoritative exchange calendar', 1)[1].split('\n      - ', 1)[0]
    assert 'calendar_restore_args=()' in calendar
    assert 'if [ -n "$CACHE_MARKET_DATE" ]' in calendar
    assert '--prior-calendar-cache-dir ".cache/market-source/restored/$CACHE_MARKET_DATE"' in calendar
    assert '"${calendar_restore_args[@]}"' in calendar
    assert 'set -euo pipefail' in calendar
