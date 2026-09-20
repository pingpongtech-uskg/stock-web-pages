from scripts.refresh_snapshot import next_expected_update_for_market_date


def test_next_expected_update_skips_weekend_after_friday_market_date():
    assert next_expected_update_for_market_date("2026-09-18") == "2026-09-21T15:17:00+00:00"


def test_next_expected_update_uses_next_day_for_weekday_market_date():
    assert next_expected_update_for_market_date("2026-09-17") == "2026-09-18T15:17:00+00:00"
