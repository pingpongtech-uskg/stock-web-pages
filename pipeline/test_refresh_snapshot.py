from scripts.refresh_snapshot import _attach_valuation
from scripts.refresh_snapshot import growth_health_qualifies
from scripts.refresh_snapshot import new_entry_rows
from scripts.refresh_snapshot import next_expected_update_for_market_date


def test_growth_health_requires_four_known_passes():
    assert growth_health_qualifies({"status": "pass", "passCount": 4, "total": 5}) is True
    assert growth_health_qualifies({"status": "unknown", "passCount": 4, "total": 5}) is False
    assert growth_health_qualifies({"status": "pass", "passCount": 3, "total": 5}) is False


def test_next_expected_update_skips_weekend_after_friday_market_date():
    assert next_expected_update_for_market_date("2026-09-18") == "2026-09-21T15:17:00+00:00"


def test_next_expected_update_uses_next_day_for_weekday_market_date():
    assert next_expected_update_for_market_date("2026-09-17") == "2026-09-18T15:17:00+00:00"


def test_trust_strategy_keeps_only_new_entries():
    rows = [
        {"code": "A", "entryStatus": "retained"},
        {"code": "B", "entryStatus": "new"},
        {"code": "C", "entryStatus": "unknown"},
    ]

    assert [row["code"] for row in new_entry_rows(rows)] == ["B"]


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


def test_extreme_revenue_proxy_is_retained_for_non_growth_observation():
    rows = [{"code": "2330", "rank": 1, "value": 25}]
    details = {"2330": {"valuation": {
        "growth_method": "three_month_revenue_proxy",
        "growth_method_label": "三月營收成長代理",
        "eps_growth": 1.5,
        "current_price": 100,
        "fair_price": 500,
        "below_075": True,
    }}}
    result = _attach_valuation(rows, details, require_peg_below_075=False, exclude_extreme=False)
    assert result[0]["code"] == "2330"
    assert result[0]["extremeExtrapolation"] is True
    assert result[0]["valuationEvidenceLevel"] == "proxy"


def test_growth_route_uses_teacher_total_return_pe_and_keeps_zulu_cross_check():
    rows = [{"code": "2330", "rank": 1, "value": 25}]
    details = {"2330": {
        "valuation": {"current_peg": 0.52, "below_075": True, "below_066": True},
        "growthValuation": {
            "status": "available",
            "method": "growth-total-return-pe",
            "formula_version": "growth-total-return-pe-v1",
            "current_price": 100,
            "current_pe": 13,
            "ttm_eps": 7.69,
            "earnings_growth": 0.20,
            "growth_method": "five_year_eps_cagr",
            "growth_method_label": "多年度 EPS CAGR（可得完整年度）",
            "dividend_yield": 0.05,
            "conservative_growth": 0.16,
            "total_return_pct": 21.0,
            "total_return_pe": 21 / 13,
            "forward_eps": 8.92,
            "fair_pe": 21.0,
            "fair_price": 187.32,
            "buy_zone_price": 156.1,
            "undervalued": True,
            "reasonable": False,
            "extreme_extrapolation": False,
        },
    }}

    result = _attach_valuation(rows, details, valuation_key="growthValuation", require_growth_total_return_pe=1.2)

    assert len(result) == 1
    assert result[0]["growthTotalReturnPe"] == 21 / 13
    assert result[0]["growthFairPrice"] == 187.32
    assert result[0]["currentPeg"] == 0.52
    assert result[0]["valuationFormulaVersion"] == "growth-total-return-pe-v1"


def test_growth_route_rejects_extreme_formal_valuation():
    rows = [{"code": "2330", "rank": 1, "value": 25}]
    details = {"2330": {"growthValuation": {
        "status": "extreme",
        "total_return_pe": 2.0,
        "extreme_extrapolation": True,
        "reason": "基期效應／極端外推，不發布主合理價",
    }}}

    assert _attach_valuation(rows, details, valuation_key="growthValuation", require_growth_total_return_pe=1.2) == []
