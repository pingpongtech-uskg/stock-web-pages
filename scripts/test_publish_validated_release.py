"""Exercise publication against real local Git remotes and concurrent commits."""
from pathlib import Path
import subprocess

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
