from scripts.refresh_snapshot import _attach_valuation
from scripts.refresh_snapshot import apply_official_institutional_metrics
from scripts.refresh_snapshot import growth_health_qualifies
from scripts.refresh_snapshot import new_entry_rows
from scripts.refresh_snapshot import next_expected_update_for_market_date
import pytest


@pytest.mark.parametrize("monthly_ratio,missing_amount,passes,eligible", [
    (1.01, False, 5, True), (.99, False, 4, True),
    (None, False, 4, True), (None, True, 3, False),
])
def test_growth_health_counts_real_checks_without_aggregate_status_gate(monthly_ratio, missing_amount, passes, eligible):
    from pipeline.growth_health import evaluate_growth_health
    income = [{"year": year, "quarter": 2, "grossProfit": 100 * factor,
               "operatingProfit": 80 * factor, "pretaxProfit": 70 * factor, "netIncome": 60 * factor}
              for year, factor in ((2025, 1), (2026, 1.2))]
    if missing_amount:
        income[-1].pop("grossProfit")
    monthly = [{"month": f"{year}-{month:02d}", "revenue": 100 * factor}
               for year, factor in ((2025, 1), (2026, monthly_ratio or 1)) for month in (6, 7, 8)] if monthly_ratio else []
    evidence = evaluate_growth_health(monthly, income)
    assert evidence["passCount"] == passes
    assert growth_health_qualifies(evidence) is eligible


def test_growth_health_does_not_trust_aggregate_pass_count_without_real_checks():
    assert growth_health_qualifies({"status": "pass", "passCount": 5, "total": 5}) is False


@pytest.mark.parametrize("malformation", ["duplicate", "missing_label", "invalid_status", "unhashable_label", "unhashable_status"])
def test_growth_health_rejects_malformed_five_check_evidence(malformation):
    from pipeline.growth_health import evaluate_growth_health
    income = [{"year": year, "quarter": 2, "grossProfit": 100 * factor,
               "operatingProfit": 80 * factor, "pretaxProfit": 70 * factor, "netIncome": 60 * factor}
              for year, factor in ((2025, 1), (2026, 1.2))]
    evidence = evaluate_growth_health([], income)
    if malformation == "duplicate":
        evidence["checks"][-1] = dict(evidence["checks"][-2])
    elif malformation == "missing_label":
        evidence["checks"][-1].pop("label")
    elif malformation == "unhashable_label":
        evidence["checks"][-1]["label"] = []
    elif malformation == "unhashable_status":
        evidence["checks"][0]["status"] = []
    else:
        evidence["checks"][0]["status"] = "complete"
    assert growth_health_qualifies(evidence) is False


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
    from pipeline.growth_health import CHECK_LABELS
    valuations = [
        {"status": "unavailable", "inputsComplete": False, "missingReasons": ["pe", "ttmEps"]},
        {"status": "extreme", "inputsComplete": True, "total_return_pe": 3},
        {"status": "available", "inputsComplete": True, "total_return_pe": 1},
        {"status": "available", "inputsComplete": True, "total_return_pe": 1.3},
        {"status": "available", "inputsComplete": True, "total_return_pe": 1.4},
    ]
    details = [{"code": str(2000+i), "growthValuation": value, "growthHealthEligible": i == 4} for i,value in enumerate(valuations)]
    details[-1]["healthCategories"] = [{"key": "growth", "checks": [
        {"label": label, "status": "pass" if i < 4 else "unknown"}
        for i, label in enumerate(CHECK_LABELS)]}]
    result = growth_funnel(details)
    assert result["growthInputComplete"] == 4
    assert result["growthValuationComplete"] == 3
    assert result["growthThresholdCandidates"] == 2
    assert result["growthHealthCandidates"] == 1
    reasons = {row["reason"]: row["count"] for row in result["growthMissingReasons"]}
    assert reasons["pe"] == 1 and reasons["ttmEps"] == 1
    assert result["growthTerminalOutcomes"] == {"universe": 5, "missing": 1, "knownInvalid": 0,
        "extreme": 1, "belowThreshold": 1, "healthBlocked": 1, "selected": 1}


@pytest.mark.parametrize("available", ["2026-01", "2026-01-invalid"])
def test_dividend_confirmation_requires_a_complete_real_day(available):
    from scripts.refresh_snapshot import _dividend_evidence
    detail = {"asOf": "2026-10-01", "healthInputs": {"dividends": [
        {"year": 2025, "period": "annual", "confirmed": True, "cashPerShare": 4,
         "availableAt": available}]}}
    assert _dividend_evidence(detail, 100)["value"] is None


def test_known_stock_dividend_blocks_unadjusted_quarter_eps():
    from scripts.refresh_snapshot import _growth_valuation_from_detail
    detail = {"asOf": "2026-10-01", "lastPrice": 100, "healthInputs": {
        "incomeQuarterly": [{"year": y, "quarter": q, "eps": 2} for y in (2022, 2023, 2024, 2025) for q in (1,2,3,4)],
        "dividends": [{"year": 2025, "period": "2025", "cashPerShare": 1, "stockPerShare": 1, "confirmed": True, "availableAt": "2026-01-01"}],
    }}
    result = _growth_valuation_from_detail(detail)
    assert result["ttm_eps"] is None
    assert result["earnings_growth"] is None


@pytest.mark.parametrize("case,reason", [("gap", "nonconsecutive_quarters"), ("incomparable", "incomparable_quarters")])
def test_growth_audit_explains_unavailable_quarter_eps(case, reason):
    from scripts.refresh_snapshot import _growth_valuation_from_detail
    income = [{"year": y, "quarter": q, "eps": 1.2 ** (y-2022)}
              for y in (2022, 2023, 2024, 2025) for q in (1, 2, 3, 4)]
    if case == "gap":
        income.pop(-2)
    else:
        income[-1]["epsComparable"] = False
    result = _growth_valuation_from_detail({"asOf": "2026-10-01", "lastPrice": 100,
        "healthInputs": {"incomeQuarterly": income}})
    assert result["ttm_eps"] is None
    assert result["inputAudit"]["ttmEps"]["origin"] == "unavailable"
    assert result["inputAudit"]["ttmEps"]["reason"] == reason
    assert result["inputAudit"]["earningsGrowth"]["reason"] == "完整年度 EPS 資料不足"


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


@pytest.mark.parametrize("label,expected", [("上半年", "H1"), ("下半年", "H2")])
def test_dividend_period_accepts_separate_roc_year_and_observed_half_label(label, expected):
    from pipeline.financial_periods import dividend_period
    assert dividend_period(label, "114") == (2025, expected)


@pytest.mark.parametrize("price_case,selected", [("adjusted", True), ("short", False), ("raw", False)])
def test_low_position_keeps_eligible_price_observation_with_unknown_financials(tmp_path, monkeypatch, price_case, selected):
    import json
    from datetime import date, timedelta
    import scripts.refresh_snapshot as refresh
    data = tmp_path / "public" / "data"
    data.mkdir(parents=True)
    start, end = date(2023, 4, 3), date(2026, 10, 1)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() < 5]
    prices = []
    for i, day in enumerate(days):
        close = 100 + i * .05 - (3 if i >= len(days) - 50 else 0) - (2 if i == len(days) - 1 else 0)
        prices.append({"date": day.isoformat(), "close": close, "volume": 1000,
                       **({"adjustedClose": close, "source": refresh.YFINANCE_PRICE_SOURCE} if price_case != "raw" else {})})
    detail = {"code": "2330", "name": "Price fixture", "asOf": end.isoformat(),
              "priceSeries": prices[-120:] if price_case == "short" else prices}
    (data / "latest.json").write_text(json.dumps({"runId": "fixture", "marketDate": end.isoformat(),
        "stocks": [detail], "freshness": "current"}))
    def no_network(*args, **kwargs):
        raise AssertionError("price observation recompute fetched network")
    for key in ("build_health_inputs", "fetch_adjusted_history", "fetch_fundamental_proxies", "build_00631l_volume_indicator"):
        monkeypatch.setattr(refresh, key, no_network)
    result = refresh.build_release(data, [], as_of=end.isoformat(), offline=False, recompute_existing=True)
    release = json.loads((data / "latest.json").read_text())
    stock = json.loads((data / "releases" / result["run_id"] / "stocks" / "2330.json").read_text())
    assert stock["growthValuation"]["ttm_eps"] is None
    assert stock["growthHealthEligible"] is False
    assert (stock["regression"]["signalEligible"] is True) is selected
    assert stock["zScore"] <= 0 and stock["slope"] > 0
    assert bool(release["rankings"]["lowPosition"]) is selected
    assert release["funnel"]["strategyCandidates"]["lowPosition"] == int(selected)


@pytest.mark.parametrize("health_case,expected_passes,selected", [
    ("5P", 5, True), ("4P1F", 4, True), ("4P1U", 4, True), ("3P2U", 3, False),
])
def test_real_shaped_financial_inputs_positive_half_dividends_reach_release_and_export(tmp_path, monkeypatch, health_case, expected_passes, selected):
    import json
    from calendar import monthrange
    import scripts.refresh_snapshot as refresh
    from pipeline.health_inputs import normalize_finmind_health_inputs
    from pipeline.twse_public import _dividend
    from pipeline.screening_export import build_export, validate_export
    raw_income = []
    for year in range(2022, 2027):
        for quarter in range(1, 5 if year < 2026 else 3):
            day = f"{year}-{quarter * 3:02d}-{monthrange(year, quarter * 3)[1]}"
            for field, base in (("EPS", 1), ("GrossProfit", 100), ("OperatingIncome", 80),
                                ("PreTaxIncome", 70), ("IncomeAfterTaxes", 60)):
                if health_case == "3P2U" and (year, quarter, field) == (2026, 2, "GrossProfit"):
                    continue
                raw_income.append({"date": day, "stock_id": "2330", "type": field,
                                   "value": base * 1.2 ** (year - 2022)})
    raw_revenue = [] if health_case in {"4P1U", "3P2U"} else [
        {"revenue_year": year, "revenue_month": month, "revenue": 100 if year == 2025 else 99 if health_case == "4P1F" else 101}
        for year in (2025, 2026) for month in (6, 7, 8)]
    financial = {"incomeStatement": raw_income}
    health = normalize_finmind_health_inputs(financial, raw_revenue)
    health["dividends"] = [_dividend({
        "股利年度": "114", "股利所屬年(季)度": period,
        "股東配發-盈餘分配之現金股利(元/股)": cash,
        "股東配發-法定盈餘公積、資本公積之現金(元/股)": surplus,
        "股東會日期": approved, "出表日期": published,
    }) for period, cash, surplus, approved, published in (
        ("上半年", "1.5", ".5", "115/03/18", "115/03/20"),
        ("下半年", "2", "0", "115/04/18", "115/04/20"),
    )]
    health["valuationCurrent"] = {"date": "2026-10-01", "pe": 13, "source": "TWSE fixture"}
    detail = {"code": "2330", "name": "Financial fixture", "asOf": "2026-10-01", "lastPrice": 80,
              "financialInputs": financial, "healthInputs": health,
              "priceSeries": [{"date": "2026-10-01", "close": 80, "adjustedClose": 80, "volume": 100}]}
    data = tmp_path / "public" / "data"
    data.mkdir(parents=True)
    (data / "latest.json").write_text(json.dumps({"runId": "fixture", "marketDate": "2026-10-01",
        "freshness": "current", "stocks": [detail]}))
    def no_network(*args, **kwargs):
        raise AssertionError("financial fixture recompute fetched network")
    for key in ("build_health_inputs", "fetch_adjusted_history", "fetch_fundamental_proxies", "build_00631l_volume_indicator"):
        monkeypatch.setattr(refresh, key, no_network)
    result = refresh.build_release(data, [], as_of="2026-10-01", offline=False, recompute_existing=True)
    release = json.loads((data / "latest.json").read_text())
    stock = json.loads((data / "releases" / result["run_id"] / "stocks" / "2330.json").read_text())
    assert stock["growthHealthPassCount"] == expected_passes
    assert stock["growthHealthEligible"] is selected
    assert stock["growthValuation"]["status"] == "available"
    assert stock["growthValuation"]["dividend_yield"] == .05
    assert stock["growthValuation"]["inputAudit"]["dividendYield"]["sourcePeriod"] == "2025"
    assert stock["growthValuation"]["total_return_pe"] == pytest.approx(21 / 13)
    assert bool(release["rankings"]["growth"]) is selected
    assert release["funnel"]["growthCoverageVersion"] == "growth-coverage-v1"
    assert release["funnel"]["growthTerminalOutcomes"]["selected"] == int(selected)
    export = build_export(release, request_id="fixture", source_git_commit="a" * 40, actions_run_id="1", details={"2330": stock})
    assert validate_export(export) == []
    assert {item["code"] for item in export["selectedStocks"]} == ({"2330"} if selected else set())
    if selected:
        assert export["selectedStocks"][0]["metrics"]["dividendYield"] == .05
        assert export["selectedStocks"][0]["provenance"]["inputOrigins"]["ttmEps"]["origin"] == "derived"


@pytest.mark.parametrize('field', ['publishedAt', 'availableAt', 'exDate', 'exDividendDate'])
@pytest.mark.parametrize('later_date', ['2026-10-03', '2026-10-invalid', '2026-10'])
def test_dividend_prior_approval_cannot_mask_future_or_invalid_known_dates(field, later_date):
    from scripts.refresh_snapshot import _dividend_evidence
    dividend = {'year': 2025, 'period': 'annual', 'cashPerShare': 2, 'confirmed': True,
                'approvedAt': '2026-06-01', field: later_date}
    detail = {'asOf': '2026-10-02', 'healthInputs': {'dividends': [dividend]}}
    result = _dividend_evidence(detail, 100)
    assert result['value'] is None
    assert result['audit']['origin'] == 'unavailable'


@pytest.mark.parametrize('cash', [0, 2])
def test_dividend_all_known_dates_before_cutoff_retains_confirmed_cash(cash):
    from scripts.refresh_snapshot import _dividend_evidence
    dividend = {'year': 2025, 'period': 'annual', 'cashPerShare': cash, 'confirmed': True,
                'approvedAt': '2026-06-01', 'publishedAt': '2026-06-02',
                'availableAt': '2026-06-03', 'exDividendDate': '2026-07-01'}
    result = _dividend_evidence({'asOf': '2026-10-02', 'healthInputs': {'dividends': [dividend]}}, 100)
    assert result['value'] == cash / 100
    assert result['audit']['origin'] == 'derived'
