#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _total_bytes(data: Path) -> int:
    return sum(path.stat().st_size for path in data.rglob('*') if path.is_file())


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--keep', type=int, default=3)
    parser.add_argument('--max-bytes', type=int, default=250_000_000)
    args = parser.parse_args(argv)

    data = args.data_dir
    latest_path = data / 'latest.json'
    if not latest_path.exists():
        print('prune_blocked=latest missing')
        return 1

    latest = json.loads(latest_path.read_text(encoding='utf-8'))
    current = str(latest.get('runId', ''))
    releases = data / 'releases'
    current_candidate = releases / current
    current_path = current_candidate.resolve()
    if (
        not current
        or current_candidate.is_symlink()
        or current_path.parent != releases.resolve()
        or not current_path.is_dir()
    ):
        print('prune_blocked=current missing')
        return 1

    dirs = sorted(
        (path for path in releases.iterdir() if path.is_dir() and not path.is_symlink()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    keep = {current}
    target_count = max(1, args.keep)
    for path in dirs:
        if path.name != current and len(keep) < target_count:
            keep.add(path.name)

    for path in dirs:
        if path.name not in keep:
            shutil.rmtree(path)

    total = _total_bytes(data)
    for path in reversed(dirs):
        if total <= args.max_bytes:
            break
        if path.name == current or path.name not in keep:
            continue
        shutil.rmtree(path)
        keep.remove(path.name)
        print(f'prune_removed_for_size={path.name}')
        total = _total_bytes(data)

    if total > args.max_bytes:
        print(f'prune_blocked=size:{total}')
        return 1
    print('prune_ok')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
