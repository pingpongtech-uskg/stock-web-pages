"""Exercise publication against real local Git remotes and concurrent commits."""
from pathlib import Path
import subprocess
import shlex

import pytest

SCRIPT = Path(__file__).with_name('publish_validated_release.sh')


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def checkout(tmp_path):
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    first = tmp_path / 'producer'
    subprocess.run(['git', 'clone', str(remote), str(first)], check=True, capture_output=True)
    for repo in [first]:
        git(repo, 'config', 'user.name', 'Test')
        git(repo, 'config', 'user.email', 'test@example.com')
        git(repo, 'config', 'core.hooksPath', '/dev/null')
    (first/'public/data').mkdir(parents=True)
    (first/'public/data/latest.json').write_text('old')
    (first/'source.txt').write_text('old source')
    git(first, 'add', '.')
    git(first, 'commit', '-m', 'initial')
    git(first, 'branch', '-M', 'main')
    git(first, 'push', 'origin', 'main')
    other = tmp_path/'other'
    subprocess.run(['git', 'clone', '-b', 'main', str(remote), str(other)], check=True, capture_output=True)
    git(other, 'config', 'user.name', 'Test')
    git(other, 'config', 'user.email', 'test@example.com')
    git(other, 'config', 'core.hooksPath', '/dev/null')
    return first, other


def publish(repo):
    assert SCRIPT.exists()
    return subprocess.run(['bash', str(SCRIPT)], cwd=repo, capture_output=True, text=True)


def test_concurrent_source_commit_is_preserved_and_validated_data_publishes(tmp_path):
    producer, other = checkout(tmp_path)
    (other/'source.txt').write_text('new source')
    git(other, 'commit', '-am', 'source repair')
    git(other, 'push', 'origin', 'main')
    (producer/'public/data/latest.json').write_text('new validated data')
    result = publish(producer)
    assert result.returncode == 0, result.stderr
    assert (producer/'source.txt').read_text() == 'new source'
    assert git(other, 'fetch', 'origin', 'main') == ''
    assert git(other, 'show', 'origin/main:public/data/latest.json') == 'new validated data'
    assert git(other, 'show', 'origin/main:source.txt') == 'new source'


def test_conflicting_publication_is_rejected_without_overwriting_remote(tmp_path):
    producer, other = checkout(tmp_path)
    (other/'public/data/latest.json').write_text('concurrent approved data')
    git(other, 'commit', '-am', 'other approved release')
    git(other, 'push', 'origin', 'main')
    approved = git(other, 'rev-parse', 'HEAD')
    (producer/'public/data/latest.json').write_text('producer data')
    assert publish(producer).returncode != 0
    git(other, 'fetch', 'origin', 'main')
    assert git(other, 'rev-parse', 'origin/main') == approved


def test_unrelated_staged_code_is_never_published_as_data(tmp_path):
    producer, other = checkout(tmp_path)
    (producer/'source.txt').write_text('unreviewed source')
    git(producer, 'add', 'source.txt')
    assert publish(producer).returncode != 0
    assert git(other, 'show', 'origin/main:source.txt') == 'old source'


def test_workflow_uses_bounded_data_only_publication():
    workflow = (SCRIPT.parent.parent / '.github/workflows/daily.yml').read_text()
    step = workflow.split('- name: Publish validated release to main', 1)[1].split('      - uses:', 1)[0]
    assert 'bash scripts/publish_validated_release.sh' in step
    assert 'git push origin HEAD:main' not in step


def test_disjoint_concurrent_data_cannot_be_silently_merged_into_validated_release(tmp_path):
    producer, other = checkout(tmp_path)
    (other/'public/data/other-release.json').write_text('other candidate')
    git(other, 'add', 'public/data/other-release.json')
    git(other, 'commit', '-m', 'concurrent data')
    git(other, 'push', 'origin', 'main')
    approved = git(other, 'rev-parse', 'HEAD')
    (producer/'public/data/latest.json').write_text('validated producer data')
    assert publish(producer).returncode != 0
    git(other, 'fetch', 'origin', 'main')
    assert git(other, 'rev-parse', 'origin/main') == approved


def seed_shared_file(producer, other, relative_path, content):
    target = producer / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(producer, 'add', relative_path)
    git(producer, 'commit', '-m', 'seed protected file')
    git(producer, 'push', 'origin', 'main')
    git(other, 'pull', '--ff-only', 'origin', 'main')


@pytest.mark.parametrize('operation', ['add', 'change', 'delete'])
def test_concurrent_protected_config_is_rejected(tmp_path, operation):
    producer, other = checkout(tmp_path)
    relative_path = 'config/tracked_symbols.json'
    if operation != 'add':
        seed_shared_file(producer, other, relative_path, '["2330"]')
    target = other / relative_path
    if operation == 'delete':
        target.unlink()
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('["2330", "6173"]')
    git(other, 'add', '--', relative_path)
    git(other, 'commit', '-m', 'concurrent universe change')
    git(other, 'push', 'origin', 'main')
    approved = git(other, 'rev-parse', 'HEAD')
    (producer / 'public/data/latest.json').write_text('validated producer data')
    assert publish(producer).returncode != 0
    git(other, 'fetch', 'origin', 'main')
    assert git(other, 'rev-parse', 'origin/main') == approved


def test_disjoint_concurrent_data_deletion_is_rejected(tmp_path):
    producer, other = checkout(tmp_path)
    relative_path = 'public/data/detail.json'
    seed_shared_file(producer, other, relative_path, 'validated detail')
    git(other, 'rm', relative_path)
    git(other, 'commit', '-m', 'concurrent detail deletion')
    git(other, 'push', 'origin', 'main')
    approved = git(other, 'rev-parse', 'HEAD')
    (producer / 'public/data/latest.json').write_text('validated producer data')
    assert publish(producer).returncode != 0
    git(other, 'fetch', 'origin', 'main')
    assert git(other, 'rev-parse', 'origin/main') == approved


@pytest.mark.parametrize('concurrent_path,expected_success', [
    ('public/data/racing-release.json', False),
    ('source.txt', True),
])
def test_push_race_rechecks_protected_tree(tmp_path, concurrent_path, expected_success):
    producer, other = checkout(tmp_path)
    (other / concurrent_path).write_text('concurrent approved content')
    git(other, 'add', concurrent_path)
    git(other, 'commit', '-m', 'racing commit')
    approved = git(other, 'rev-parse', 'HEAD')
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    marker = tmp_path / 'race-injected'
    hook = hooks / 'pre-push'
    hook.write_text(
        '#!/usr/bin/env bash\nset -eu\n'
        f'if [ ! -f {shlex.quote(str(marker))} ]; then\n'
        f'  touch {shlex.quote(str(marker))}\n'
        f'  git -C {shlex.quote(str(other))} push origin HEAD:main >/dev/null\n'
        'fi\n'
    )
    hook.chmod(0o755)
    git(producer, 'config', 'core.hooksPath', str(hooks))
    (producer / 'public/data/latest.json').write_text('validated producer data')
    result = publish(producer)
    assert marker.exists(), result.stderr
    assert (result.returncode == 0) == expected_success, result.stderr
    git(other, 'fetch', 'origin', 'main')
    if expected_success:
        assert git(other, 'show', 'origin/main:source.txt') == 'concurrent approved content'
        assert git(other, 'show', 'origin/main:public/data/latest.json') == 'validated producer data'
        git(other, 'merge-base', '--is-ancestor', approved, 'origin/main')
    else:
        assert git(other, 'rev-parse', 'origin/main') == approved


def test_push_retries_are_bounded(tmp_path):
    producer, other = checkout(tmp_path)
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    attempts = tmp_path / 'push-attempts'
    hook = hooks / 'pre-push'
    hook.write_text(
        '#!/usr/bin/env bash\n'
        f'echo attempted >> {shlex.quote(str(attempts))}\n'
        'exit 1\n'
    )
    hook.chmod(0o755)
    git(producer, 'config', 'core.hooksPath', str(hooks))
    original = git(other, 'rev-parse', 'HEAD')
    (producer / 'public/data/latest.json').write_text('validated producer data')
    result = publish(producer)
    assert result.returncode != 0
    assert len(attempts.read_text().splitlines()) == 3
    assert 'publication_failed=bounded_push_attempts_exhausted' in result.stderr
    git(other, 'fetch', 'origin', 'main')
    assert git(other, 'rev-parse', 'origin/main') == original


def test_unchanged_candidate_is_a_noop(tmp_path):
    producer, other = checkout(tmp_path)
    original = git(producer, 'rev-parse', 'HEAD')
    result = publish(producer)
    assert result.returncode == 0, result.stderr
    assert git(producer, 'rev-parse', 'HEAD') == original
    git(other, 'fetch', 'origin', 'main')
    assert git(other, 'rev-parse', 'origin/main') == original


def test_successful_remote_push_with_ambiguous_local_failure_is_safe_to_retry(tmp_path):
    producer, other = checkout(tmp_path)
    hooks = tmp_path / 'hooks'
    hooks.mkdir()
    marker = tmp_path / 'accepted-push'
    hook = hooks / 'pre-push'
    hook.write_text(
        '#!/usr/bin/env bash\nset -eu\n'
        f'if [ ! -f {shlex.quote(str(marker))} ]; then\n'
        '  git -c core.hooksPath=/dev/null push origin HEAD:main >/dev/null\n'
        f'  git rev-parse HEAD > {shlex.quote(str(marker))}\n'
        '  exit 1\n'
        'fi\n'
    )
    hook.chmod(0o755)
    git(producer, 'config', 'core.hooksPath', str(hooks))
    (producer / 'public/data/latest.json').write_text('validated producer data')
    result = publish(producer)
    assert result.returncode == 0, result.stderr
    accepted_commit = marker.read_text().strip()
    git(other, 'fetch', 'origin', 'main')
    assert git(other, 'rev-parse', 'origin/main') == accepted_commit
    assert git(producer, 'rev-parse', 'HEAD') == accepted_commit
    assert git(other, 'show', 'origin/main:public/data/latest.json') == 'validated producer data'
