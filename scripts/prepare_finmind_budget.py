"""Recover the actual Taipei budget day immediately before supplementary work."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from restore_finmind_checkpoint import main as restore_checkpoint


def today_taipei() -> str:
    return datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--previous-date', required=True)
    parser.add_argument('--cache-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if date.fromisoformat(args.previous_date).isoformat() != args.previous_date:
            raise ValueError('invalid previous budget date')
        actual = today_taipei()
        if actual != args.previous_date:
            with redirect_stdout(sys.stderr):
                result = restore_checkpoint(['--cache-dir', str(args.cache_dir), '--budget-date', actual])
            if result:
                raise ValueError('current-day checkpoint recovery failed')
    except ValueError as exc:
        print(f'budget_prepare_failed={exc}', file=sys.stderr)
        return 1
    print(actual)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
