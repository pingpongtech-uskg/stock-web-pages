from pipeline.peg_ttm import calculate_ttm_peg


def rows_through(year, quarter, *, published_at=None):
    rows = []
    value = 1.0
    for y in range(2024, year + 1):
        for q in range(1, 5):
            if (y, q) > (year, quarter):
                break
            rows.append({"year": y, "quarter": q, "eps": value,
                         **({"availableAt": published_at} if published_at else {})})
            value *= 1.1
    return rows


def test_verified_source_check_keeps_last_filed_quarter_even_before_calendar_deadline():
    valuation, review = calculate_ttm_peg(
        rows_through(2026, 2), as_of="2026-11-03", price=100,
        freshness_target="2026Q3",
        financial_check={"status": "verified", "checkedAt": "2026-11-03", "source": "TWSE OpenAPI", "latestPeriod": "2026Q2"},
    )

    assert valuation is not None
    assert review["status"] == "available"
    assert review["expectedLatestQuarter"] == "2026Q3"
    assert review["currentPeriod"] == "2025Q3–2026Q2"
    assert review["priorPeriod"] == "2024Q3–2025Q2"
    assert review["currentTtmEps"] is not None
    assert review["priorTtmEps"] is not None
    assert review["epsGrowthPct"] is not None


def test_missing_source_check_suppresses_cached_old_ttm_with_diagnostics():
    valuation, review = calculate_ttm_peg(
        rows_through(2026, 2),
        as_of="2026-11-03", price=100, freshness_target="2026Q3",
    )

    assert valuation is None
    assert review["status"] == "needs_review"
    assert review["reasonCodes"] == ["latest_statement_unverified"]
    assert review["currentPeriod"] == "2025Q3–2026Q2"
    assert review["currentTtmEps"] is not None
    assert review["priorTtmEps"] is not None
    assert review["epsGrowthPct"] is not None


def test_stale_source_check_downgrades_numeric_decline_verdict_to_review():
    rows = [
        {"year": year, "quarter": quarter, "eps": eps}
        for year, eps in ((2024, 2.0), (2025, 1.0))
        for quarter in range(1, 5)
    ]
    valuation, review = calculate_ttm_peg(
        rows, as_of="2026-03-01", price=100, freshness_target="2025Q4",
    )

    assert valuation is None
    assert review["status"] == "needs_review"
    assert review["reasonCodes"] == ["latest_statement_unverified"]
    assert review["currentTtmEps"] == 4.0
    assert review["priorTtmEps"] == 8.0
    assert review["epsGrowthPct"] == -50.0
    assert review["expectedLatestQuarter"] == "2025Q4"


def test_newer_disclosed_quarter_without_eps_is_never_hidden_by_old_window():
    rows = rows_through(2026, 2) + [{"year": 2026, "quarter": 3, "eps": None, "availableAt": "2026-10-30"}]
    valuation, review = calculate_ttm_peg(
        rows, as_of="2026-11-03", price=100, freshness_target="2026Q3",
        financial_check={"status": "verified", "checkedAt": "2026-11-03", "source": "TWSE", "latestPeriod": "2026Q3"},
    )

    assert valuation is None
    assert review["reasonCodes"] == ["missing_latest_quarter_eps"]


def test_verified_source_period_newer_than_eps_rows_suppresses_old_ttm():
    valuation, review = calculate_ttm_peg(
        rows_through(2026, 2), as_of="2026-11-03", price=100, freshness_target="2026Q3",
        financial_check={"status": "verified", "checkedAt": "2026-11-03", "source": "FinMind:TaiwanStockFinancialStatements", "latestPeriod": "2026Q3"},
    )

    assert valuation is None
    assert review["reasonCodes"] == ["latest_statement_unverified"]
    assert review["latestSourcePeriod"] == "2026Q3"
    assert review["currentPeriod"] == "2025Q3–2026Q2"


def test_future_target_quarter_does_not_count_as_fresh_evidence():
    rows = rows_through(2026, 2) + [{"year": 2026, "quarter": 3, "eps": 2.0, "publishedAt": "2026-11-04"}]
    valuation, review = calculate_ttm_peg(
        rows, as_of="2026-11-03", price=100, freshness_target="2026Q3",
        financial_check={"status": "verified", "checkedAt": "2026-11-03", "source": "TWSE OpenAPI", "latestPeriod": "2026Q2"},
    )

    assert valuation is not None
    assert review["status"] == "available"
    assert review["currentPeriod"].endswith("2026Q2")


def test_insufficient_quarters_remains_the_primary_diagnostic():
    valuation, review = calculate_ttm_peg(
        rows_through(2025, 2), as_of="2026-11-03", price=100,
        freshness_target="2026Q3",
    )

    assert valuation is None
    assert review["reasonCodes"] == ["insufficient_quarters"]
    assert review["availableQuarterCount"] == 6


def test_generic_calculator_remains_opt_out_of_freshness_policy():
    valuation, review = calculate_ttm_peg(
        rows_through(2026, 2), as_of="2026-11-03", price=100,
    )

    assert valuation is not None
    assert review["status"] == "available"
