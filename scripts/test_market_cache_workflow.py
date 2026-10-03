"""Guard complete-cache publication ordering and failure recovery boundaries."""
from pathlib import Path


def snapshot_job():
    text = (Path(__file__).resolve().parents[1] / '.github/workflows/daily.yml').read_text()
    return text.split('\njobs:\n', 1)[1].split('\n  institutional_probe:\n', 1)[0]


def test_restore_source_receipts_before_collection_and_capture_all_inputs():
    job = snapshot_job()
    assert job.index('Restore complete daily source receipts') < job.index('Fetch authoritative exchange calendar')
    assert 'market-source-v1-\n' in job
    for script in ['build_trading_calendar.py', 'fetch_research_universe.py', 'refresh_snapshot.py --as-of']:
        line = next(line for line in job.splitlines() if script in line and ('run:' in line or line.strip().startswith(('python ', 'if python '))))
        assert '--source-cache-dir .cache/market-source' in line


def test_complete_cache_must_validate_before_main_publication():
    job = snapshot_job()
    export = job.index('scripts/build_screening_export.py')
    index = job.index('scripts/build_market_cache_index.py')
    validation = job.index('scripts/export_market_cache.py')
    publication = job.index('Publish validated release to main')
    assert export < index < validation < publication
    assert '--source-git-commit "$SOURCE_GIT_COMMIT"' in job[index:validation]
    assert '--actions-run-id "$GITHUB_RUN_ID"' in job[index:validation]
    assert '--export-payload-hash' in job[index:validation]


def test_complete_artifact_and_partial_receipts_are_distinct():
    job = snapshot_job()
    completed = job.split('- name: Preserve validated complete market cache', 1)[1].split('\n      - ', 1)[0]
    assert 'name: market-cache' in completed and 'path: .artifacts/market-cache' in completed
    assert 'if-no-files-found: error' in completed and 'if: always()' not in completed
    partial = job.split('- name: Preserve raw source receipts after failure', 1)[1].split('\n      - ', 1)[0]
    assert 'if: always()' in partial and 'name: market-source-checkpoint-' in partial
    assert 'path: .cache/market-source' in partial and 'if-no-files-found: warn' in partial
    assert '.cache/finmind' not in partial and 'FINMIND_TOKEN' not in partial


def test_cache_artifact_uses_stored_zip_for_bounded_remote_readback():
    # gzip members are already compressed; remote Code has no bounded inflate.
    completed = snapshot_job().split('- name: Preserve validated complete market cache', 1)[1].split('\n      - ', 1)[0]
    assert 'compression-level: 0' in completed


def test_institutional_collection_uses_authoritative_calendar_before_holiday_probes():
    job = snapshot_job()
    assert job.index('Fetch authoritative exchange calendar') < job.index('Fetch official institutional universe')
    command = next(line for line in job.splitlines() if 'if python scripts/fetch_research_universe.py' in line)
    assert '--calendar public/data/trading-calendar.json' in command
