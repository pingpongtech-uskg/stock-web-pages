from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.verify_tracked_universe import tracked_universe_error

NOW = datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc)


def valid_payload(now: datetime = NOW) -> dict[str, object]:
    symbols = [f"{1000 + index:04d}" for index in range(100)]
    dates = [(date(2026, 10, 1) - timedelta(days=index)).isoformat() for index in range(10)]
    return {
        "stale": False,
        "symbols": symbols,
        "metadata": {
            code: {"name": f"Stock {index}", "market": "TWSE"}
            for index, code in enumerate(symbols)
        },
        "universe": {
            "asOfFetchedAt": (now - timedelta(minutes=1)).isoformat(),
            "marketDates": dates,
            "rows": [{"code": code, "rank": index + 1} for index, code in enumerate(symbols)],
        },
    }


def test_current_matching_official_payload_passes() -> None:
    snapshot = valid_payload()
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW) is None


def test_config_must_match_official_output() -> None:
    snapshot = valid_payload()
    changed_config = deepcopy(snapshot)
    changed_config["symbols"][0] = "9999"  # type: ignore[index]
    assert tracked_universe_error(changed_config, snapshot, now=NOW) is not None


@pytest.mark.parametrize(
    "fetched_at",
    [
        (NOW - timedelta(hours=37)).isoformat(),
        (NOW + timedelta(seconds=1)).isoformat(),
        "not-a-date",
    ],
)
def test_stale_future_or_unparsed_fetch_timestamp_fails(fetched_at: str) -> None:
    snapshot = valid_payload()
    snapshot["universe"]["asOfFetchedAt"] = fetched_at  # type: ignore[index]
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW) is not None


def test_stale_universe_flag_fails() -> None:
    snapshot = valid_payload()
    snapshot["stale"] = True
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW) is not None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["universe"].__setitem__("marketDates", payload["universe"]["marketDates"][:-1]),
        lambda payload: payload["universe"]["marketDates"].__setitem__(1, payload["universe"]["marketDates"][0]),
        lambda payload: payload["universe"]["marketDates"].__setitem__(0, "2026-99-99"),
        lambda payload: payload["universe"]["marketDates"].reverse(),
    ],
)
def test_market_dates_must_be_ten_unique_iso_dates_in_descending_order(mutate) -> None:
    snapshot = valid_payload()
    mutate(snapshot)
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW) is not None


@pytest.mark.parametrize(
    "bad_symbol",
    ["", "ABC", "123", "12345", "７８５６", " 7856", "7856 ", "7856\n", 7856],
)
def test_symbol_codes_require_exactly_four_ascii_digits_and_string_type(bad_symbol) -> None:
    snapshot = valid_payload()
    snapshot["symbols"][0] = bad_symbol  # type: ignore[index]
    snapshot["metadata"].pop("1000")  # type: ignore[union-attr]
    snapshot["metadata"][bad_symbol] = {"name": "Bad", "market": "TWSE"}  # type: ignore[index]
    snapshot["universe"]["rows"][0]["code"] = bad_symbol  # type: ignore[index]
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW) is not None


def test_symbol_codes_must_be_exactly_one_hundred_and_unique() -> None:
    snapshot = valid_payload()
    snapshot["symbols"][1] = snapshot["symbols"][0]  # type: ignore[index]
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW) is not None


def test_symbol_count_must_be_exactly_one_hundred() -> None:
    snapshot = valid_payload()
    snapshot["symbols"] = snapshot["symbols"][:-1]  # type: ignore[index]
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW) is not None


def test_metadata_and_rows_must_match_symbol_list_order() -> None:
    snapshot = valid_payload()
    snapshot["metadata"].pop(snapshot["symbols"][0])  # type: ignore[union-attr,index]
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW) is not None

    snapshot = valid_payload()
    snapshot["universe"]["rows"].reverse()  # type: ignore[index]
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW) is not None


def test_final_release_market_date_must_match_official_universe() -> None:
    snapshot = valid_payload()
    latest = {"marketDate": "2026-09-30"}
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW, latest=latest) is not None


def test_final_release_matching_market_date_passes() -> None:
    snapshot = valid_payload()
    latest = {"marketDate": "2026-10-01"}
    assert tracked_universe_error(snapshot, deepcopy(snapshot), now=NOW, latest=latest) is None


def test_final_recheck_rejects_config_mutation_after_fetch_gate() -> None:
    snapshot = valid_payload()
    config_after_fetch = deepcopy(snapshot)
    assert tracked_universe_error(config_after_fetch, snapshot, now=NOW) is None
    config_after_fetch["metadata"]["1000"]["name"] = "unexpected change"  # type: ignore[index]
    assert tracked_universe_error(config_after_fetch, snapshot, now=NOW) is not None
