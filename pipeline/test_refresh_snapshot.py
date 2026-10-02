from scripts.refresh_snapshot import _attach_valuation
from scripts.refresh_snapshot import apply_official_institutional_metrics
from scripts.refresh_snapshot import growth_health_qualifies
from scripts.refresh_snapshot import new_entry_rows
from scripts.refresh_snapshot import next_expected_update_for_market_date
import pytest


def test_growth_health_requires_four_known_passes():
    assert growth_health_qualifies({"status": "pass", "passCount": 4, "total": 5}) is True
    assert growth_health_qualifies({"status": "unknown", "passCount": 4, "total": 5}) is False
    assert growth_health_qualifies({"status": "pass", "passCount": 3, "total": 5}) is False


def test_next_expected_update_skips_weekend_after_friday_market_date():
    assert next_expected_update_for_market_date("2026-09-18") == "2026-09-21T11:30:00+00:00"


def test_next_expected_update_uses_next_day_for_weekday_market_date():
    assert next_expected_update_for_market_date("2026-09-17") == "2026-09-18T11:30:00+00:00"


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


def test_official_institutional_metrics_replace_old_values():
    detail = {
        "code": "2330",
        "entryReasons": ["投信舊資料：999"],
        "priceSeries": [
            {"date": f"2026-09-{day:02d}", "volume": 1000}
            for day in range(14, 24)
        ],
    }
    dates = [f"2026-09-{day:02d}" for day in range(23, 13, -1)]
    daily = {
        date: {"netShares": 100 if index % 2 == 0 else -50}
        for index, date in enumerate(dates)
    }
    apply_official_institutional_metrics(
        detail,
        market_dates=dates,
        daily_by_code={"2330": daily},
    )
    assert detail["institutionDataAsOf"] == "2026-09-23"
    assert detail["institutionNetShares10"] == 250
    assert detail["positiveDays10"] == 5
    assert detail["participation10"] == 0.025
    assert len(detail["institutionalDaily"]) == 10
    assert all(row["status"] == "pass" for row in detail["institutionalDaily"])
    assert not any(reason.startswith("投信舊資料") for reason in detail["entryReasons"])


def test_official_institutional_metrics_fail_closed_on_missing_daily_row():
    detail = {
        "code": "2330",
        "institutionNetShares10": 999,
        "participation10": 0.9,
        "positiveDays10": 10,
        "priceSeries": [{"date": "2026-09-23", "volume": 1000}],
    }
    apply_official_institutional_metrics(
        detail,
        market_dates=["2026-09-23"],
        daily_by_code={"2330": {}},
    )
    assert detail["institutionDataStatus"] == "unknown"
    assert detail["institutionNetShares10"] is None
    assert detail["participation10"] is None
    assert detail["positiveDays10"] is None


def test_growth_route_rejects_extreme_formal_valuation():
    rows = [{"code": "2330", "rank": 1, "value": 25}]
    details = {"2330": {"growthValuation": {
        "status": "extreme",
        "total_return_pe": 2.0,
        "extreme_extrapolation": True,
        "reason": "基期效應／極端外推，不發布主合理價",
    }}}

    assert _attach_valuation(rows, details, valuation_key="growthValuation", require_growth_total_return_pe=1.2) == []


def test_enrichment_preserves_merged_financial_history():
    from datetime import date
    from scripts.refresh_snapshot import enrich_detail
    detail = {"code": "2330", "healthInputs": {
        "incomeQuarterly": [{"year": 2025, "quarter": 1, "eps": 2}],
        "balanceQuarterly": [{"year": 2025, "quarter": 1, "equity": 100}],
        "monthlyRevenueOfficial": [{"month": "2025-03", "revenue": 100}],
    }}
    result, _ = enrich_detail(detail, end=date(2026, 10, 1), offline=True, public_inputs={
        "incomeQuarterly": [{"year": 115, "quarter": 2, "eps": 3}],
        "balanceQuarterly": [{"year": 115, "quarter": 2, "equity": 200}],
        "monthlyRevenueOfficial": [{"month": "2026-08", "revenue": 150}],
    })
    assert len(result["healthInputs"]["incomeQuarterly"]) == 2
    assert len(result["healthInputs"]["balanceQuarterly"]) == 2
    assert len(result["healthInputs"]["monthlyRevenueOfficial"]) == 2


def test_dividend_aggregation_rejects_proposals_future_and_incomplete_quarters():
    from scripts.refresh_snapshot import _confirmed_dividend_yield
    detail = {"asOf": "2026-10-01", "healthInputs": {"dividends": [
        {"year": 114, "period": f"114Q{q}", "cashPerShare": 1, "confirmed": True,
         "availableAt": "2026-03-01"} for q in (1, 2, 3, 4)
    ]}}
    assert _confirmed_dividend_yield(detail, 100) == 0.04
    detail["healthInputs"]["dividends"].append({"year": 115, "period": "115", "cashPerShare": 99,
                                               "confirmed": False, "availableAt": "2026-09-01"})
    detail["healthInputs"]["dividends"].append({"year": 115, "period": "115", "cashPerShare": 99,
                                               "confirmed": True, "availableAt": "2026-12-01"})
    assert _confirmed_dividend_yield(detail, 100) == 0.04
    detail["healthInputs"]["dividends"] = detail["healthInputs"]["dividends"][:2]
    assert _confirmed_dividend_yield(detail, 100) is None


def test_primary_valuation_derives_missing_pe_only_from_same_day_price_valid_ttm():
    from scripts.refresh_snapshot import _growth_valuation_from_detail
    detail = {"asOf": "2026-10-01", "lastPrice": 100, "healthInputs": {
        "incomeQuarterly": [{"year": y, "quarter": q, "eps": (4 * 1.2 ** (y - 2022)) / 4}
                             for y in (2022, 2023, 2024, 2025) for q in (1, 2, 3, 4)],
        "dividends": [{"year": 2025, "period": "2025", "cashPerShare": 0, "confirmed": True,
                       "availableAt": "2026-06-01"}],
        "valuationCurrent": {"date": "2026-10-01", "pe": None},
    }}
    result = _growth_valuation_from_detail(detail)
    assert result["current_pe"] == 100 / result["ttm_eps"]
    assert result["inputAudit"]["pe"]["origin"] == "derived"
    detail["healthInputs"]["valuationCurrent"] = {"date": "2026-09-30", "pe": 10}
    result = _growth_valuation_from_detail(detail)
    assert result["inputAudit"]["pe"]["origin"] == "derived"
    assert result["current_pe"] != 10



def test_next_expected_update_respects_known_closed_dates():
    assert next_expected_update_for_market_date("2026-09-18", non_trading_dates={"2026-09-21"}, deadline="20:00") == "2026-09-22T12:00:00+00:00"


def test_three_month_growth_does_not_use_nonconsecutive_months():
    from scripts.refresh_snapshot import _revenue_growth_from_public_inputs
    rows = [{"month": f"{year}-{month:02d}", "revenue": 100 if year == 2025 else 110}
            for year in (2025, 2026) for month in (1, 3, 4)]
    assert _revenue_growth_from_public_inputs({"monthlyRevenueOfficial": rows}) is None


def test_growth_funnel_counts_input_calculation_threshold_health_separately():
    from scripts.refresh_snapshot import growth_funnel
    valuations = [
        {"status": "unavailable", "inputsComplete": False, "missingReasons": ["pe", "ttmEps"]},
        {"status": "extreme", "inputsComplete": True, "total_return_pe": 3},
        {"status": "available", "inputsComplete": True, "total_return_pe": 1},
        {"status": "available", "inputsComplete": True, "total_return_pe": 1.3},
        {"status": "available", "inputsComplete": True, "total_return_pe": 1.4},
    ]
    details = [{"code": str(2000+i), "growthValuation": value, "growthHealthEligible": i == 4} for i,value in enumerate(valuations)]
    result = growth_funnel(details)
    assert result["growthInputComplete"] == 4
    assert result["growthValuationComplete"] == 3
    assert result["growthThresholdCandidates"] == 2
    assert result["growthHealthCandidates"] == 1
    reasons = {row["reason"]: row["count"] for row in result["growthMissingReasons"]}
    assert reasons["pe"] == 1 and reasons["ttmEps"] == 1
    assert reasons["extreme"] == 1 and reasons["threshold"] == 1 and reasons["health"] == 1


def test_known_stock_dividend_blocks_unadjusted_quarter_eps():
    from scripts.refresh_snapshot import _growth_valuation_from_detail
    detail = {"asOf": "2026-10-01", "lastPrice": 100, "healthInputs": {
        "incomeQuarterly": [{"year": y, "quarter": q, "eps": 2} for y in (2022, 2023, 2024, 2025) for q in (1,2,3,4)],
        "dividends": [{"year": 2025, "period": "2025", "cashPerShare": 1, "stockPerShare": 1, "confirmed": True, "availableAt": "2026-01-01"}],
    }}
    result = _growth_valuation_from_detail(detail)
    assert result["ttm_eps"] is None
    assert result["earnings_growth"] is None


def test_cached_recompute_has_no_network_and_selects_growth_without_15_percent_revenue(tmp_path, monkeypatch):
    import json
    import scripts.refresh_snapshot as refresh
    data = tmp_path / "public" / "data"
    data.mkdir(parents=True)
    income = [{"year": year, "quarter": quarter, "eps": 1.2 ** (year - 2022),
               "grossProfit": 100 * 1.2 ** (year - 2022), "operatingProfit": 80 * 1.2 ** (year - 2022),
               "pretaxProfit": 70 * 1.2 ** (year - 2022), "netIncome": 60 * 1.2 ** (year - 2022)}
              for year in (2022, 2023, 2024, 2025) for quarter in (1,2,3,4)]
    revenue = [{"month": f"{year}-{month:02d}", "revenue": 100 if year == 2025 else 101}
               for year in (2025,2026) for month in (6,7,8)]
    detail = {"code": "2330", "name": "Test", "asOf": "2026-10-01", "lastPrice": 80,
              "priceSeries": [{"date": "2026-10-01", "close": 80, "adjustedClose": 80, "volume": 100}],
              "healthInputs": {"incomeQuarterly": income, "monthlyRevenueOfficial": revenue,
                               "dividends": [{"year": 2025,"period": "2025", "cashPerShare": 0,
                                              "confirmed": True, "availableAt": "2026-06-01"}]}}
    (data / "latest.json").write_text(json.dumps({"runId": "baseline", "marketDate": "2026-10-01",
                                                "freshness": "current", "stocks": [detail], "marketIndicators": {"volumeMultiple00631L": {"status": "unavailable"}}}))
    def unexpected_network(*args, **kwargs):
        raise AssertionError("cached recompute called network")
    for key in ("build_health_inputs", "fetch_adjusted_history", "fetch_fundamental_proxies", "build_00631l_volume_indicator"):
        monkeypatch.setattr(refresh, key, unexpected_network)
    result = refresh.build_release(data, [], as_of="2026-10-02", offline=False, recompute_existing=True)
    latest = json.loads((data / "latest.json").read_text())
    assert result["market_date"] == "2026-10-01"
    assert latest["rankings"]["growth"][0]["code"] == "2330"
    assert latest["funnel"]["growthInputComplete"] == 1
    assert latest["funnel"]["growthThresholdCandidates"] == 1
    assert latest["funnel"]["growthHealthCandidates"] == 1
    assert latest["acquisitionMode"] == "cached_recompute"


def test_live_enrichment_does_not_replace_actual_price_date_with_requested_today(monkeypatch):
    from datetime import date
    import scripts.refresh_snapshot as refresh
    monkeypatch.delenv("FAST_REFRESH", raising=False)
    monkeypatch.setattr(refresh, "fetch_adjusted_history", lambda *args: (
        [{"date": "2026-10-01", "close": 100, "adjustedClose": 100, "source": refresh.YFINANCE_PRICE_SOURCE}],
        refresh.YFINANCE_PRICE_SOURCE, None))
    monkeypatch.setattr(refresh, "fetch_fundamental_proxies", lambda *args: (
        {"latestOperatingMargin": .2, "latestNetIncome": 100, "latestOperatingCashFlow": 200},
        refresh.YFINANCE_FUNDAMENTAL_SOURCE, None))
    detail, errors = refresh.enrich_detail({"code": "2330", "asOf": "2026-09-30", "priceSeries": []},
                                         end=date(2026,10,2), offline=False)
    assert errors == []
    assert detail["asOf"] == "2026-10-01"
    assert detail["lastPrice"] == 100


def test_latest_dividend_year_incomplete_blocks_using_older_complete_year():
    from scripts.refresh_snapshot import _confirmed_dividend_yield
    detail = {"asOf": "2026-10-01", "healthInputs": {"dividends": [
        {"year": 2024, "period": "2024", "cashPerShare": 10, "confirmed": True, "availableAt": "2025-03-01"},
        {"year": 2025, "period": "2025Q1", "cashPerShare": 1, "confirmed": True, "availableAt": "2026-03-01"},
    ]}}
    assert _confirmed_dividend_yield(detail, 100) is None


def test_confirmed_annual_zero_dividend_is_available_not_unknown():
    from scripts.refresh_snapshot import _confirmed_dividend_yield
    detail = {"asOf": "2026-10-01", "healthInputs": {"dividends": [
        {"year": 2025, "period": "2025", "cashPerShare": 0, "confirmed": True, "availableAt": "2026-03-01"},
    ]}}
    assert _confirmed_dividend_yield(detail, 100) == 0
    detail["healthInputs"]["dividends"] = []
    assert _confirmed_dividend_yield(detail, 100) is None


def test_release_deadline_uses_authoritative_calendar_and_fails_closed_outside_year(tmp_path):
    import json
    from scripts.refresh_snapshot import release_next_expected_update
    (tmp_path / "trading-calendar.json").write_text(json.dumps({
        "schemaVersion": "trading-calendar-v1", "timezone": "Asia/Taipei", "year": 2026, "closedDates": ["2026-10-09"],
        "openExceptions": [],
    }))
    assert release_next_expected_update(tmp_path, "2026-10-08") == "2026-10-12T11:30:00+00:00"
    assert release_next_expected_update(tmp_path, "2026-12-31") is None


def test_legacy_official_snapshot_is_not_mistaken_for_single_quarter():
    from scripts.refresh_snapshot import _health_inputs_from_detail
    result = _health_inputs_from_detail({"healthInputs": {"source": "TWSE OpenAPI", "incomeQuarterly": [
        {"year": 115, "quarter": 2, "eps": 5},
    ]}})
    assert result["incomeQuarterly"][0]["periodType"] == "ytd"


def test_primary_pe_does_not_use_adjusted_price_as_same_day_raw_close():
    from scripts.refresh_snapshot import _growth_valuation_from_detail
    detail = {"asOf": "2026-10-01", "lastPrice": 100, "priceSeries": [
        {"date": "2026-10-01", "adjustedClose": 100}], "healthInputs": {
        "incomeQuarterly": [{"year": 2025, "quarter": q, "eps": 1} for q in (1,2,3,4)],
    }}
    result = _growth_valuation_from_detail(detail)
    assert result["current_pe"] is None
    assert result["current_price"] is None
    assert result["inputAudit"]["price"]["origin"] == "proxy"


def test_recompute_cli_passes_cached_mode_and_as_of_without_network(monkeypatch, capsys, tmp_path):
    import sys
    import scripts.refresh_snapshot as refresh
    calls = []
    monkeypatch.setattr(sys, "argv", ["refresh_snapshot.py", "--recompute-existing", "--as-of", "2026-10-02", "--output", str(tmp_path)])
    def build(data, codes, **kwargs):
        calls.append((data, codes, kwargs))
        return {"market_date": "2026-10-01"}
    monkeypatch.setattr(refresh, "build_release", build)
    assert refresh.main() == 0
    assert calls[0][2]["recompute_existing"] is True
    assert calls[0][2]["as_of"] == "2026-10-02"
    assert "2026-10-01" in capsys.readouterr().out


def test_deadline_invalid_market_date_does_not_fabricate_today():
    assert next_expected_update_for_market_date("invalid") is None
    assert next_expected_update_for_market_date(None) is None


def test_dividend_annual_and_quarter_rows_are_not_double_counted():
    from scripts.refresh_snapshot import _confirmed_dividend_yield
    rows = [{"year": 2025, "period": "annual", "cashPerShare": 4, "confirmed": True,
             "availableAt": "2026-06-01"}] + [
        {"year": 2025, "period": f"Q{quarter}", "cashPerShare": 1, "confirmed": True,
         "availableAt": "2026-03-01"} for quarter in (1,2,3,4)]
    assert _confirmed_dividend_yield({"asOf": "2026-10-01", "healthInputs": {"dividends": rows}}, 100) == .04


def test_enrichment_returns_new_detail_without_mutating_source_snapshot():
    from datetime import date
    import copy
    from scripts.refresh_snapshot import enrich_detail
    original = {"code": "2330", "priceSeries": [], "revenueMonthly": [{"month": "2025-03", "revenue": 100}]}
    before = copy.deepcopy(original)
    result, _ = enrich_detail(original, end=date(2026, 10, 1), offline=True)
    assert original == before
    assert result is not original


def test_public_first_partial_financial_outage_recovers_from_supplemented_cache(tmp_path, monkeypatch):
    """A missing latest quarter stays unknown until real quarter-shaped rows arrive.

    All numbers are explicit test fixtures stored beneath pytest's temporary
    directory. The repository's published financial snapshot is never touched.
    """
    import json
    import scripts.refresh_snapshot as refresh
    from pipeline.health_inputs import merge_health_inputs

    data = tmp_path / "public" / "data"
    data.mkdir(parents=True)
    config = tmp_path / "config"
    config.mkdir()
    days = [f"2026-09-{day:02d}" for day in (18, 21, 22, 23, 24, 25, 28, 29, 30)] + ["2026-10-01"]
    config.joinpath("tracked_symbols.json").write_text(json.dumps({
        "symbols": ["2330"],
        "universe": {
            "sourceUrl": "https://example.test/official-universe",
            "label": "Official test universe",
            "rows": [{"code": "2330", "name": "Financial fixture", "rank": 7, "netShares": 1000}],
            "previousRows": [{"code": "2330", "rank": 11}],
            "marketDates": list(reversed(days)),
            "dailyRows": [{"date": day, "rows": [{"code": "2330", "netShares": 100}]} for day in days],
        },
    }))
    income = [{"year": year, "quarter": quarter, "eps": 1.2 ** (year - 2022),
               "grossProfit": 100 * 1.2 ** (year - 2022), "operatingProfit": 80 * 1.2 ** (year - 2022),
               "pretaxProfit": 70 * 1.2 ** (year - 2022), "netIncome": 60 * 1.2 ** (year - 2022),
               "periodType": "quarter", "source": "FinMind fixture", "amountUnit": "TWD"}
              for year in (2022, 2023, 2024, 2025) for quarter in (1, 2, 3, 4)]
    revenue = [{"month": f"{year}-{month:02d}", "revenue": 100 if year == 2025 else 101}
               for year in (2025, 2026) for month in (6, 7, 8)]
    detail = {"code": "2330", "name": "Financial fixture", "market": "TWSE", "asOf": "2026-09-30",
              "healthInputs": {"incomeQuarterly": income, "monthlyRevenueOfficial": revenue,
                               "balanceQuarterly": [{"year": 2025, "quarter": 4, "equity": 500}]}}
    data.joinpath("latest.json").write_text(json.dumps({
        "runId": "fixture-before-public-refresh", "marketDate": "2026-09-30", "stocks": [detail],
    }))
    data.joinpath("institutional_universe.json").write_text(json.dumps({"stale": False}))
    calls = []

    def public(codes):
        calls.append("official_bulk")
        assert codes == ["2330"]
        return {"2330": {
            "source": "TWSE OpenAPI", "errors": {"balance": "TimeoutError"}, "balanceQuarterly": [],
            "incomeQuarterly": [{"year": 115, "quarter": 2, "periodType": "ytd", "eps": 5,
                                 "grossProfit": 500, "source": "TWSE fixture", "amountUnit": "TWD_thousands"}],
            "valuationCurrent": {"date": "2026-10-01", "pe": 80 / (4 * 1.2 ** 3), "source": "TWSE fixture"},
            "dividends": [{"year": 2025, "period": "annual", "cashPerShare": 0, "confirmed": True,
                           "availableAt": "2026-06-01", "source": "TWSE fixture"}],
        }}

    def prices(*args):
        calls.append("adjusted_prices")
        return ([{"date": day, "close": 80, "adjustedClose": 80, "volume": 1000,
                  "source": refresh.YFINANCE_PRICE_SOURCE} for day in days], refresh.YFINANCE_PRICE_SOURCE, None)

    def fundamentals(*args):
        calls.append("fundamentals")
        return ({"latestNetIncome": 100, "latestOperatingCashFlow": 110, "latestOperatingMargin": .2},
                refresh.YFINANCE_FUNDAMENTAL_SOURCE, None)

    def volume(day):
        calls.append("market_volume")
        assert day == "2026-10-01"
        return {"status": "unavailable", "reason": "test fixture"}

    monkeypatch.delenv("FAST_REFRESH", raising=False)
    for key, value in {"build_health_inputs": public, "fetch_adjusted_history": prices,
                       "fetch_fundamental_proxies": fundamentals, "build_00631l_volume_indicator": volume}.items():
        monkeypatch.setattr(refresh, key, value)
    first = refresh.build_release(data, [], as_of="2026-10-02", offline=False)
    release = json.loads(data.joinpath("latest.json").read_text())
    published = data / "releases" / first["run_id"] / "stocks" / "2330.json"
    stock = json.loads(published.read_text())

    assert calls == ["official_bulk", "adjusted_prices", "fundamentals", "market_volume"]
    assert release["marketDate"] == "2026-10-01"
    assert release["freshness"] == "degraded"
    assert len(stock["healthInputs"]["incomeQuarterly"]) == 17
    assert stock["healthInputs"]["balanceQuarterly"][0]["equity"] == 500
    assert stock["growthValuation"]["ttm_eps"] is None
    assert "ttmEps" in stock["growthValuation"]["missingReasons"]
    assert release["rankings"]["growth"] == []
    assert release["rankings"]["trust"][0]["sourceRank"] == 7
    assert release["rankings"]["trust"][0]["previousRank"] == 11
    assert stock["institutionNetShares10"] == 1000
    assert stock["participation10"] == .1

    supplement = {"incomeQuarterly": [
        {"year": 2026, "quarter": quarter, "eps": eps, "grossProfit": 200,
         "operatingProfit": 200, "pretaxProfit": 200, "netIncome": 200,
         "periodType": "quarter", "source": "FinMind fixture", "amountUnit": "TWD"}
        for quarter, eps in ((1, 1.5), (2, 2))
    ]}
    stock = {**stock, "healthInputs": merge_health_inputs(stock["healthInputs"], supplement)}
    published.write_text(json.dumps(stock))
    second = refresh.build_release(data, [], as_of="2026-10-02", offline=False, recompute_existing=True)
    recovered = json.loads(data.joinpath("latest.json").read_text())
    recovered_stock = json.loads((data / "releases" / second["run_id"] / "stocks" / "2330.json").read_text())
    assert calls == ["official_bulk", "adjusted_prices", "fundamentals", "market_volume"]
    assert recovered["marketDate"] == "2026-10-01"
    assert recovered_stock["growthValuation"]["status"] == "available"
    assert recovered_stock["growthValuation"]["inputAudit"]["ttmEps"]["origin"] == "derived"
    assert recovered["rankings"]["growth"][0]["code"] == "2330"
    assert recovered["funnel"]["growthHealthCandidates"] == 1
    assert len(recovered_stock["healthInputs"]["incomeQuarterly"]) == 18
    assert recovered["freshness"] == "degraded"


def test_refresh_cli_missing_baseline_fails_without_writing_release(tmp_path, monkeypatch, capsys):
    import sys
    import scripts.refresh_snapshot as refresh
    monkeypatch.setattr(sys, "argv", ["refresh_snapshot.py", "--recompute-existing", "--output", str(tmp_path)])
    assert refresh.main() == 1
    assert "snapshot_refresh_failed=FileNotFoundError" in capsys.readouterr().err
    assert not tmp_path.joinpath("latest.json").exists()


@pytest.mark.parametrize("derived", [True, False])
def test_partial_reported_quarter_does_not_relabel_retained_amounts_with_new_units(derived):
    from pipeline.health_inputs import merge_health_inputs
    from pipeline.growth_health import evaluate_growth_health
    amounts = ("grossProfit", "operatingProfit", "pretaxProfit", "netIncome")
    base = {"incomeQuarterly": [{"year": 2025, "quarter": 2, "periodType": "quarter",
                                 **dict.fromkeys(amounts, 50), "amountUnit": "TWD"},
                                {"year": 2026, "quarter": 2, "periodType": "quarter", **dict.fromkeys(amounts, 100),
                                 "source": "TWSE fixture", "amountUnit": "TWD_thousands",
                                 **({"inputOrigin": "derived", "derivationMethod": "compatible_ytd_difference"}
                                    if derived else {"inputOrigin": "reported"})}]}
    direct = {"incomeQuarterly": [{"year": 2026, "quarter": 2, "periodType": "quarter", "eps": 2,
                                   "source": "FinMind fixture", "amountUnit": "TWD", "inputOrigin": "reported"}]}
    income = merge_health_inputs(base, direct)["incomeQuarterly"]
    row = income[-1]
    assert row["eps"] == 2
    assert row["source"] == "FinMind fixture"
    assert row["amountUnit"] == "TWD"
    assert all(row.get(field) is None for field in amounts)
    assert "derivationMethod" not in row
    health = evaluate_growth_health([], income)
    assert health["passCount"] == 0
    assert all(check["status"] == "unknown" for check in health["checks"][1:])


def test_metadata_only_quarter_overlay_preserves_derived_values_and_provenance():
    from pipeline.health_inputs import merge_health_inputs
    original = {"year": 2026, "quarter": 2, "periodType": "quarter", "grossProfit": 100,
                "source": "TWSE fixture", "amountUnit": "TWD_thousands", "inputOrigin": "derived",
                "derivationMethod": "compatible_ytd_difference"}
    row = merge_health_inputs({"incomeQuarterly": [original]}, {"incomeQuarterly": [
        {"year": 2026, "quarter": 2, "periodType": "quarter", "eps": None,
         "grossProfit": None, "source": "FinMind fixture", "amountUnit": "TWD"},
    ]})["incomeQuarterly"][0]
    assert row == original
