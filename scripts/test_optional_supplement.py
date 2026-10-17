"""Optional provider failures must never partially mutate the official release."""
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


def module():
    # Keep a missing implementation an explicit assertion during the RED run.
    assert (Path(__file__).parent / "run_optional_supplement.py").is_file()
    return importlib.import_module("scripts.run_optional_supplement")


def provider(tmp_path, *, exit_code=0, delay=0, skipped=None):
    script = tmp_path / "provider.py"
    script.write_text(
        "import json,pathlib,sys,time\n"
        "out=pathlib.Path(sys.argv[sys.argv.index('--output')+1])\n"
        "(out/'latest.json').write_bytes(b'enriched')\n"
        "(out/'new.json').write_bytes(b'new')\n"
        f"pathlib.Path({str(tmp_path / 'durable-budget')!r}).write_bytes(b'used')\n"
        f"time.sleep({delay})\n"
        f"print(json.dumps({{'skipped': {skipped!r}}}))\n"
        f"sys.exit({exit_code})\n"
    )
    return [sys.executable, str(script)]


def official(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "latest.json").write_bytes(b'official')
    (data / "stocks").mkdir()
    (data / "stocks" / "2330.json").write_bytes(b'official stock')
    return data


def bytes_by_path(data):
    return {str(path.relative_to(data)): path.read_bytes() for path in data.rglob('*') if path.is_file()}


@pytest.mark.parametrize("exit_code,delay,timeout,expected", [
    (1, 0, 5, "provider_failed"), (0, 2, 0.3, "provider_timeout"),
])
def test_failed_or_timed_out_partial_provider_keeps_all_official_bytes(
    tmp_path, exit_code, delay, timeout, expected,
):
    data = official(tmp_path)
    before = bytes_by_path(data)
    outcome = module().run_optional_supplement(
        data, provider(tmp_path, exit_code=exit_code, delay=delay), timeout_seconds=timeout,
    )
    assert outcome == expected
    assert bytes_by_path(data) == before
    assert (tmp_path / "durable-budget").read_bytes() == b'used'


def test_success_promotes_complete_staging_and_preserves_existing_files(tmp_path):
    data = official(tmp_path)
    assert module().run_optional_supplement(data, provider(tmp_path), timeout_seconds=5) == "supplemented"
    assert bytes_by_path(data) == {
        'latest.json': b'enriched', 'new.json': b'new', 'stocks/2330.json': b'official stock',
    }


@pytest.mark.parametrize('skipped', ['runtime_limit', 'dataset_unavailable', 'FinMindError', 'SourceBlocked', 'BudgetExceeded'])
def test_completed_partial_acquisitions_remain_available_to_mandatory_recompute_gate(tmp_path, skipped):
    data = official(tmp_path)
    assert module().run_optional_supplement(
        data, provider(tmp_path, skipped=skipped), timeout_seconds=5,
    ) == 'supplemented'
    assert (data / 'latest.json').read_bytes() == b'enriched'
    assert (tmp_path / 'durable-budget').read_bytes() == b'used'


def test_failed_promotion_rolls_back_original_and_remains_fatal(tmp_path, monkeypatch):
    data = official(tmp_path)
    before = bytes_by_path(data)
    wrapper = module()
    replace = wrapper.os.replace

    def fail_staging_promotion(source, destination):
        if Path(source).name == "staged":
            raise OSError("promotion refused")
        return replace(source, destination)

    monkeypatch.setattr(wrapper.os, "replace", fail_staging_promotion)
    with pytest.raises(OSError, match="promotion refused"):
        wrapper.run_optional_supplement(data, provider(tmp_path), timeout_seconds=5)
    assert bytes_by_path(data) == before


def test_process_launch_failure_is_fatal_and_keeps_official_bytes(tmp_path):
    data = official(tmp_path)
    before = bytes_by_path(data)
    with pytest.raises(OSError):
        module().run_optional_supplement(data, [str(tmp_path / 'missing-command')], timeout_seconds=5)
    assert bytes_by_path(data) == before


def test_failed_rollback_preserves_original_backup_for_recovery(tmp_path, monkeypatch):
    data = official(tmp_path)
    before = bytes_by_path(data)
    wrapper = module()
    replace = wrapper.os.replace

    def fail_promote_and_rollback(source, destination):
        if Path(source).name in {'staged', 'official-backup'}:
            raise OSError('rename failed')
        return replace(source, destination)

    monkeypatch.setattr(wrapper.os, 'replace', fail_promote_and_rollback)
    with pytest.raises(OSError, match='rename failed'):
        wrapper.run_optional_supplement(data, provider(tmp_path), timeout_seconds=5)
    backups = list(tmp_path.glob('.optional-supplement-*/official-backup'))
    assert len(backups) == 1
    assert bytes_by_path(backups[0]) == before


def test_staging_filesystem_error_is_fatal_and_keeps_official_bytes(tmp_path, monkeypatch):
    data = official(tmp_path)
    before = bytes_by_path(data)

    def refuse_copy(*args, **kwargs):
        raise OSError('copy refused')

    monkeypatch.setattr(module().shutil, 'copytree', refuse_copy)
    with pytest.raises(OSError, match='copy refused'):
        module().run_optional_supplement(data, provider(tmp_path), timeout_seconds=5)
    assert bytes_by_path(data) == before


@pytest.mark.parametrize('exit_code,expected', [(0, 'supplemented'), (1, 'provider_failed')])
def test_cli_reports_advisory_provider_failure_with_successful_exit(tmp_path, exit_code, expected):
    data = official(tmp_path)
    command = provider(tmp_path, exit_code=exit_code)
    result = subprocess.run([
        sys.executable, str(Path(__file__).parent / 'run_optional_supplement.py'),
        '--data-dir', str(data), '--timeout-seconds', '5', '--', *command,
    ], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout.splitlines()[-1]) == {'optionalSupplement': expected}
    assert ('::warning::' in result.stdout) == (exit_code != 0)


def test_workflow_uses_bounded_staged_supplement_and_advisory_cache_upload():
    text = (Path(__file__).resolve().parents[1] / '.github/workflows/daily.yml').read_text()
    supplement = text.split('- name: Supplement remaining financial gaps', 1)[1].split('\n      - name:', 1)[0]
    assert 'scripts/run_optional_supplement.py' in supplement
    assert '--timeout-seconds 1440' in supplement
    assert '--max-runtime-seconds 1380' in supplement
    assert 'continue-on-error' not in supplement
    upload = text.split('- name: Preserve validated complete market cache', 1)[1].split('\n      - ', 1)[0]
    assert 'id: market-cache-upload' in upload
    assert 'timeout-minutes: 3' in upload
    assert 'continue-on-error: true' in upload
    assert "if: steps.market-cache-upload.outcome == 'failure'" in text
