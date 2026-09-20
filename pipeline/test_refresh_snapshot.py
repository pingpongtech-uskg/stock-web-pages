from scripts.refresh_snapshot import next_expected_update_for_market_date
from scripts.refresh_snapshot import _attach_valuation


def test_next_expected_update_skips_weekend_after_friday_market_date():
    assert next_expected_update_for_market_date("2026-09-18") == "2026-09-21T15:17:00+00:00"


def test_next_expected_update_uses_next_day_for_weekday_market_date():
    assert next_expected_update_for_market_date("2026-09-17") == "2026-09-18T15:17:00+00:00"


def test_official_trust_row_without_valuation_is_retained():
    rows = [{"code": "2330", "rank": 1, "sourceRank": 1, "previousRank": 2, "entryStatus": "retained"}]
    result = _attach_valuation(rows, {"2330": {}}, require_peg_below_075=False)
    assert result[0]["code"] == "2330"
    assert result[0]["currentPeg"] is None
    assert result[0]["sourceRank"] == 1


def test_extreme_revenue_proxy_is_not_published_as_growth_candidate():
    rows = [{"code": "2330", "rank": 0, "value": 25}]
    details = {"2330": {"valuation": {
        "growth_method": "three_month_revenue_proxy",
        "growth_method_label": "三月營收成長代理",
        "eps_growth": 1.5,
        "current_price": 100,
        "fair_price": 500,
        "below_075": True,
    }}}
    assert _attach_valuation(rows, details) == []
