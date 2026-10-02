#!/usr/bin/env python3
"""Fail closed when a daily release did not reach the current market session."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object expected: {path}")
    return value


def latest_market_date(config: dict[str, Any]) -> str | None:
    universe = config.get("universe")
    dates = universe.get("marketDates") if isinstance(universe, dict) else []
    valid: list[str] = []
    for value in dates if isinstance(dates, list) else []:
        text = str(value or "")[:10]
        try:
            date.fromisoformat(text)
        except ValueError:
            continue
        valid.append(text)
    return max(valid) if valid else None


def freshness_errors(data_dir: Path, config_path: Path, requested_market_date: str | None = None) -> list[str]:
    release = load(data_dir / "latest.json")
    config = load(config_path)
    expected = latest_market_date(config)
    errors: list[str] = []
    if requested_market_date:
        try:
            if date.fromisoformat(requested_market_date).isoformat() != requested_market_date:
                raise ValueError('exact ISO date required')
        except ValueError:
            return ['requested_market_date_invalid']
        if expected != requested_market_date:
            errors.append(f'official_market_date:{expected}!={requested_market_date}')
        expected = requested_market_date
    if (config.get('universe') or {}).get('stale') or (release.get('coverage') or {}).get('universeStale'):
        errors.append('official_universe_stale')
    if expected is None:
        return ["official_universe_market_date_missing"]
    if str(release.get("marketDate") or "") != expected:
        errors.append(f"release_market_date:{release.get('marketDate')}!={expected}")

    indicator = (release.get("marketIndicators") or {}).get("volumeMultiple00631L")
    if not isinstance(indicator, dict):
        errors.append("00631L_indicator_missing")
    elif str(indicator.get("marketDate") or "") != expected:
        errors.append(f"00631L_market_date:{indicator.get('marketDate')}!={expected}")

    run_id = str(release.get("runId") or "")
    if not run_id:
        return [*errors, "release_run_id_missing"]
    for summary in release.get("stocks", []):
        if not isinstance(summary, dict):
            continue
        code = str(summary.get("code") or "")
        if not code:
            continue
        detail_path = data_dir / "releases" / run_id / "stocks" / f"{code}.json"
        try:
            detail = load(detail_path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append(f"detail_missing:{code}")
            continue
        if str(detail.get("asOf") or "") != expected:
            errors.append(f"price_date:{code}:{detail.get('asOf')}!={expected}")
        regression = detail.get("regression")
        if not isinstance(regression, dict):
            errors.append(f"regression_missing:{code}")
        else:
            if str(regression.get("historyEnd") or "") != expected:
                errors.append(f"regression_date:{code}:{regression.get('historyEnd')}!={expected}")
            if regression.get("priceBasis") != "adjusted":
                errors.append(f"regression_not_adjusted:{code}")
        if str(detail.get("institutionDataAsOf") or "") != expected:
            errors.append(f"institution_date:{code}:{detail.get('institutionDataAsOf')}!={expected}")
        daily = detail.get("institutionalDaily")
        if (
            not isinstance(daily, list)
            or len(daily) != 10
            or any(not isinstance(row, dict) or row.get("status") != "pass" for row in daily)
        ):
            errors.append(f"institution_window_incomplete:{code}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--market-date")
    parser.add_argument("--universe-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.universe_only:
            expected = latest_market_date(load(Path(args.config)))
            if not args.market_date or date.fromisoformat(args.market_date).isoformat() != args.market_date:
                raise ValueError('exact requested market date required')
            errors = [] if expected == args.market_date else [f'official_market_date:{expected}!={args.market_date}']
            if (load(Path(args.config)).get('universe') or {}).get('stale'):
                errors.append('official_universe_stale')
        else:
            errors = freshness_errors(Path(args.data_dir), Path(args.config), args.market_date)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"daily_freshness_failed={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps({"valid": True}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
