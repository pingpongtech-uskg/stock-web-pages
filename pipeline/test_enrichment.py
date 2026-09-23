from datetime import date, timedelta

from pipeline.enrichment import clip_price_window, low_base_growth_gates, low_base_quality_gates, low_position_gates, merge_adjusted_prices


def proxy_checks(statuses: list[str]) -> list[dict[str, str]]:
    return [
        {"label": f"proxy-{index}", "status": status, "value": "1", "period": "2025", "explanation": "test", "sourceRefs": []}
        for index, status in enumerate(statuses)
    ]


def test_low_base_growth_does_not_require_institutional_buying():
    result = low_base_growth_gates(
        z=-1.25,
        slope=0.4,
        price_eligible=True,
        growth=0.2,
        operating_profit_growth=None,
    )

    assert result["status"] == "pass"
    assert not any(gate["key"] == "institutionalTop100" for gate in result["gates"])


def test_low_base_growth_keeps_missing_price_or_growth_unknown():
    result = low_base_growth_gates(
        z=-1.25,
        slope=0.4,
        price_eligible=None,
        growth=None,
    )

    assert result["status"] == "unknown"
    assert {gate["key"] for gate in result["gates"] if gate["status"] == "unknown"} >= {"priceEligible", "growthProxy"}


def test_low_base_quality_requires_anchors_and_four_of_five():
    result = low_base_quality_gates(
        z=-1.5,
        slope=0.2,
        price_eligible=True,
        quality_checks=proxy_checks(["pass", "pass", "pass", "pass", "fail"]),
    )

    assert result["status"] == "pass"
    assert result["qualityPasses"] == 4


def test_low_base_quality_does_not_promote_unknown_anchor():
    result = low_base_quality_gates(
        z=-1.5,
        slope=0.2,
        price_eligible=True,
        quality_checks=proxy_checks(["unknown", "pass", "pass", "pass", "pass"]),
    )

    assert result["status"] == "unknown"
    assert any(gate["key"] == "qualityAnchors" and gate["status"] == "unknown" for gate in result["gates"])


def test_low_position_price_only_row_keeps_growth_health_unknown():
    result = low_position_gates(z=-0.5, slope=0.2, price_eligible=True, growth_health="unknown")
    assert result["status"] == "unknown"
    assert result["growthHealth"]["status"] == "unknown"


def test_low_position_formal_row_requires_growth_health():
    result = low_position_gates(z=-0.5, slope=0.2, price_eligible=True, growth_health="pass")
    assert result["status"] == "pass"


def test_merge_adjusted_prices_keeps_live_quote_and_volume_without_baseline():
    merged = merge_adjusted_prices(
        [],
        [{"date": "2026-09-23", "close": 343.0, "volume": 21255470, "adjustedClose": 343.0}],
    )

    assert merged == [{"date": "2026-09-23", "close": 343.0, "volume": 21255470, "amount": None, "adjustedClose": 343.0}]


def test_merge_adjusted_prices_fills_missing_live_fields_on_existing_point():
    merged = merge_adjusted_prices(
        [{"date": "2026-09-23", "close": None, "volume": None}],
        [{"date": "2026-09-23", "close": 343.0, "volume": 21255470, "adjustedClose": 343.0}],
    )

    assert merged[0]["close"] == 343.0
    assert merged[0]["volume"] == 21255470


def test_clip_price_window_keeps_only_the_fixed_3_5_year_frame():
    points = [
        {"date": "2022-09-12"},  # four-year history from an older fetch
        {"date": "2023-03-12"},
        {"date": "2023-03-13"},
        {"date": "2026-09-11"},
        {"date": "2026-09-14"},
        {"date": "not-a-date"},
    ]

    clipped = clip_price_window(points, start=date(2023, 3, 13), end=date(2026, 9, 11))

    assert [point["date"] for point in clipped] == ["2023-03-13", "2026-09-11"]


def test_clip_price_window_anchors_on_market_end():
    end = date(2026, 9, 11)
    start = end - timedelta(days=1278)
    points = [{"date": (start + timedelta(days=offset)).isoformat()} for offset in range(0, 1500)]

    clipped = clip_price_window(points, start=start, end=end)

    assert clipped[0]["date"] == start.isoformat()
    assert clipped[-1]["date"] == end.isoformat()
    assert len(clipped) == 1279
