"""Stage optional provider enrichment so failures retain official snapshot bytes."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def _promote(staged: Path, data_dir: Path, backup: Path) -> None:
    os.replace(data_dir, backup)
    try:
        os.replace(staged, data_dir)
    except OSError:
        # Rollback errors remain fatal too; the caller preserves the backup.
        os.replace(backup, data_dir)
        raise


def run_optional_supplement(
    data_dir: Path, command: list[str], *, timeout_seconds: float,
) -> str:
    """Only provider exit/timeout is advisory; filesystem/launch errors are fatal.

    The command receives a staged --output directory. Cache/budget arguments
    remain external so failed attempts cannot reset already consumed quota.
    """
    if not command or any(arg == '--output' or arg.startswith('--output=') for arg in command):
        raise ValueError('supplement command must omit --output')
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError('timeout must be finite and positive')
    data_dir = data_dir.resolve(strict=True)
    workspace = Path(tempfile.mkdtemp(prefix='.optional-supplement-', dir=data_dir.parent))
    staged, backup = workspace / 'staged', workspace / 'official-backup'
    try:
        shutil.copytree(data_dir, staged)
        try:
            completed = subprocess.run(
                [*command, '--output', str(staged)], timeout=timeout_seconds, check=False,
            )
        except subprocess.TimeoutExpired:
            # subprocess.run kills and waits for the child before returning.
            return 'provider_timeout'
        if completed.returncode != 0:
            return 'provider_failed'
        _promote(staged, data_dir, backup)
        return 'supplemented'
    finally:
        # A failed rollback must retain the original bytes for recovery.
        if backup.exists() and not data_dir.exists():
            print(f'Official snapshot backup retained at {backup}', flush=True)
        else:
            shutil.rmtree(workspace)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=float, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    outcome = run_optional_supplement(args.data_dir, command, timeout_seconds=args.timeout_seconds)
    if outcome != 'supplemented':
        print(f'::warning::Optional financial supplement {outcome}; retained official snapshot. Missing data remains disclosed.')
    print(json.dumps({'optionalSupplement': outcome}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
