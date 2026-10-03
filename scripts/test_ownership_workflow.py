"""A reference-only acquisition must finish before its Actions timeout."""
from scripts.test_market_cache_workflow import snapshot_job


def test_ownership_acquisition_is_bounded_and_uses_the_requested_market_date():
    job = snapshot_job()
    block = job.split('- name: Fetch ownership reference cache', 1)[1].split('\n      - ', 1)[0]
    assert '--as-of "$MARKET_DATE"' in block
    assert '--max-runtime-seconds 180' in block
    assert '--max-requests 40' in block
    assert '--max-history-requests 20' in block
    assert 'timeout-minutes: 8' in block
    assert 'continue-on-error' not in block


def test_ownership_checkpoint_is_reused_and_preserved_even_after_later_failure():
    job = snapshot_job()
    before = job.split('- name: Restore ownership reference checkpoint', 1)[1].split('\n      - ', 1)[0]
    after = job.split('- name: Persist ownership reference checkpoint', 1)[1].split('\n      - ', 1)[0]
    assert 'actions/cache/restore@v4' in before
    assert 'actions/cache/save@v4' in after
    assert 'path: .cache/ownership_snapshot.json' in before
    assert 'path: .cache/ownership_snapshot.json' in after
    assert 'ownership-reference-v1-' in before
    assert 'if: always()' in after
    assert job.index('Restore ownership reference checkpoint') < job.index('Fetch ownership reference cache')
    assert job.index('Fetch ownership reference cache') < job.index('Persist ownership reference checkpoint')
    assert job.index('Persist ownership reference checkpoint') < job.index('Refresh official public-source snapshot first')
