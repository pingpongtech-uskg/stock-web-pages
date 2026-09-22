from datetime import date

from pipeline.market_indicators import compute_volume_multiple


def row(day: str, volume: str):
    return {"date": day, "volume": volume}


def test_volume_multiple_excludes_current_day_and_turns_green_at_two():
    result = compute_volume_multiple(
        [row("2026-09-15", "1,500"), row("2026-09-16", "1,500"), row("2026-09-17", "1,500"), row("2026-09-18", "1,500"), row("2026-09-21", "1,500"), row("2026-09-22", "3,000")],
        as_of=date(2026, 9, 22),
    )
    assert result["currentVolume"] == 3000
    assert result["previous5AverageVolume"] == 1500
    assert result["multiple"] == 2.0
    assert result["signal"] == "green"


def test_volume_multiple_below_two_is_yellow():
    result = compute_volume_multiple([row(f"2026-09-{day:02d}", "1,500") for day in range(15, 22)], as_of=date(2026, 9, 22))
    assert result["multiple"] == 1.0
    assert result["signal"] == "yellow"


def test_volume_multiple_fails_closed_without_five_prior_sessions():
    result = compute_volume_multiple([row("2026-09-18", "3,000")], as_of=date(2026, 9, 18))
    assert result["status"] == "unavailable"
    assert result["multiple"] is None
    assert result["signal"] == "unknown"


def test_volume_multiple_does_not_skip_a_missing_prior_session():
    rows = [row(f"2026-09-{day:02d}", "1,500") for day in range(15, 22)]
    rows[2]["volume"] = ""
    result = compute_volume_multiple(rows, as_of=date(2026, 9, 22))
    assert result["status"] == "unavailable"
    assert result["signal"] == "unknown"
