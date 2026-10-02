from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

EXPECTED_SYMBOL_COUNT = 100
EXPECTED_MARKET_DATE_COUNT = 10
MAX_FETCH_AGE = timedelta(hours=36)


def tracked_universe_error(
    config: object,
    official_snapshot: object,
    *,
    now: datetime | None = None,
    latest: object | None = None,
) -> str | None:
    """Return a fail-closed contract error for the tracked official universe."""
    if not isinstance(config, dict) or not isinstance(official_snapshot, dict):
        return "payload_type"
    if config != official_snapshot:
        return "config_output_mismatch"
    if config.get("stale") is not False:
        return "stale_payload"

    universe = config.get("universe")
    if not isinstance(universe, dict):
        return "universe_type"

    fetched_at = universe.get("asOfFetchedAt")
    if not isinstance(fetched_at, str):
        return "fetch_timestamp_missing"
    try:
        fetched_day = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except ValueError:
        return "fetch_timestamp_unparsed"
    if fetched_day.tzinfo is None or fetched_day.utcoffset() is None:
        return "fetch_timestamp_timezone"
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        return "clock_timezone"
    age = current_time.astimezone(timezone.utc) - fetched_day.astimezone(timezone.utc)
    if age < timedelta(0):
        return "fetch_timestamp_future"
    if age > MAX_FETCH_AGE:
        return "fetch_timestamp_stale"

    market_dates = universe.get("marketDates")
    if not isinstance(market_dates, list) or len(market_dates) != EXPECTED_MARKET_DATE_COUNT:
        return "market_date_count"
    parsed_dates: list[date] = []
    for value in market_dates:
        if not isinstance(value, str):
            return "market_date_type"
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return "market_date_unparsed"
        if parsed.isoformat() != value:
            return "market_date_format"
        parsed_dates.append(parsed)
    if len(set(parsed_dates)) != len(parsed_dates):
        return "market_date_duplicate"
    if any(left <= right for left, right in zip(parsed_dates, parsed_dates[1:])):
        return "market_date_order"

    symbols = config.get("symbols")
    if not isinstance(symbols, list) or len(symbols) != EXPECTED_SYMBOL_COUNT:
        return "symbol_count"
    if any(not isinstance(symbol, str) for symbol in symbols):
        return "symbol_type"
    if any(re.fullmatch(r"[0-9]{4}", symbol) is None for symbol in symbols):
        return "symbol_format"
    if len(set(symbols)) != len(symbols):
        return "symbol_duplicate"

    metadata = config.get("metadata")
    if not isinstance(metadata, dict) or set(metadata) != set(symbols):
        return "metadata_symbols_mismatch"
    if any(not isinstance(metadata[symbol], dict) for symbol in symbols):
        return "metadata_row_type"

    rows = universe.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_SYMBOL_COUNT:
        return "universe_row_count"
    if any(not isinstance(row, dict) for row in rows):
        return "universe_row_type"
    if [row.get("code") for row in rows] != symbols:
        return "universe_row_symbols_mismatch"

    if latest is not None:
        if not isinstance(latest, dict):
            return "latest_type"
        if latest.get("marketDate") != market_dates[0]:
            return "latest_market_date_mismatch"
    return None


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Verify official tracked-universe release consistency.")
    parser.add_argument("--config", type=Path, default=root / "config" / "tracked_symbols.json")
    parser.add_argument("--snapshot", type=Path, default=root / "public" / "data" / "institutional_universe.json")
    parser.add_argument("--latest", type=Path, help="Optionally require latest.json marketDate to match the official universe.")
    args = parser.parse_args()

    try:
        config = _load_json(args.config)
        official_snapshot = _load_json(args.snapshot)
        latest = _load_json(args.latest) if args.latest else None
    except (OSError, json.JSONDecodeError) as exc:
        print(f"tracked_universe_invalid=read_error:{type(exc).__name__}")
        return 1

    error = tracked_universe_error(config, official_snapshot, latest=latest)
    if error:
        print("tracked_universe_invalid=" + error)
        return 1
    if not isinstance(config, dict):
        print("tracked_universe_invalid=validated_config_type")
        return 1
    universe = config.get("universe")
    symbols = config.get("symbols")
    if not isinstance(universe, dict) or not isinstance(symbols, list):
        print("tracked_universe_invalid=validated_payload_shape")
        return 1
    print(
        "tracked_universe_valid="
        f"symbols:{len(symbols)};marketDate:{universe['marketDates'][0]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
