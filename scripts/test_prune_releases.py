import json
import os

from scripts.prune_releases import main


def _release(data, name, size, mtime):
    directory = data / 'releases' / name
    directory.mkdir(parents=True)
    (directory / 'payload').write_bytes(b'x' * size)
    os.utime(directory, (mtime, mtime))
    return directory


def _latest(data, run_id):
    (data / 'latest.json').write_text(json.dumps({'runId': run_id}))


def test_prune_keeps_current_and_two_previous_when_under_cap(tmp_path):
    data = tmp_path / 'data'
    _release(data, 'oldest', 10, 1)
    _release(data, 'middle', 10, 2)
    _release(data, 'current', 10, 3)
    _release(data, 'extra', 10, 0)
    _latest(data, 'current')

    assert main(['--data-dir', str(data), '--keep', '3', '--max-bytes', '10000']) == 0
    assert {path.name for path in (data / 'releases').iterdir()} == {'oldest', 'middle', 'current'}


def test_prune_drops_oldest_optional_releases_until_under_cap(tmp_path):
    data = tmp_path / 'data'
    _release(data, 'oldest', 100, 1)
    _release(data, 'middle', 100, 2)
    _release(data, 'current', 100, 3)
    _latest(data, 'current')
    cap = (data / 'latest.json').stat().st_size + 100 + 100 + 100

    assert main(['--data-dir', str(data), '--keep', '3', '--max-bytes', str(cap - 1)]) == 0
    assert {path.name for path in (data / 'releases').iterdir()} == {'middle', 'current'}


def test_prune_keeps_current_if_size_guard_cannot_be_met(tmp_path, capsys):
    data = tmp_path / 'data'
    current = _release(data, 'current', 100, 1)
    _release(data, 'older', 100, 0)
    _latest(data, 'current')

    assert main(['--data-dir', str(data), '--keep', '3', '--max-bytes', '1']) == 1
    assert current.exists()
    assert not (data / 'releases' / 'older').exists()
    assert 'prune_blocked=size:' in capsys.readouterr().out


def test_prune_guard_missing_current(tmp_path, capsys):
    data = tmp_path / 'data'
    releases = data / 'releases'
    releases.mkdir(parents=True)
    (releases / 'other').mkdir()
    _latest(data, 'missing')

    assert main(['--data-dir', str(data)]) == 1
    assert (releases / 'other').exists()
    assert 'prune_blocked=current missing' in capsys.readouterr().out


def test_prune_guard_missing_latest(tmp_path, capsys):
    data = tmp_path / 'data'
    data.mkdir()

    assert main(['--data-dir', str(data)]) == 1
    assert 'prune_blocked=latest missing' in capsys.readouterr().out


def test_prune_guard_rejects_current_symlink(tmp_path, capsys):
    data = tmp_path / 'data'
    releases = data / 'releases'
    releases.mkdir(parents=True)
    (releases / 'real').mkdir()
    (releases / 'current').symlink_to(releases / 'real', target_is_directory=True)
    _latest(data, 'current')

    assert main(['--data-dir', str(data)]) == 1
    assert (releases / 'real').exists()
    assert 'prune_blocked=current missing' in capsys.readouterr().out
