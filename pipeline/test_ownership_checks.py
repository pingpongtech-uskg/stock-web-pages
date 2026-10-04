from pipeline.ownership_checks import evaluate_chip_reference


def rows():
    return [
        {"code": "2330", "period": "2025-08", "largeHolderPct": 40.0, "shareholderCount": 13000, "directorSupervisorPct": 10.0, "directorDenominator": 1000, "sourceRefs": ["old"]},
        {"code": "2330", "period": "2026-06", "largeHolderPct": 41.0, "shareholderCount": 12900},
        {"code": "2330", "period": "2026-07", "largeHolderPct": 41.5, "shareholderCount": 12670},
        {"code": "2330", "period": "2026-08", "largeHolderPct": 42.0, "shareholderCount": 12540, "directorSupervisorPct": 10.5, "directorDenominator": 1000, "sourceRefs": ["new"]},
    ]


def test_chip_reference_evaluates_three_strict_trends_and_12_month_director_comparison():
    result = evaluate_chip_reference(rows())

    assert result["status"] == "pass"
    assert result["displayOnly"] is True
    assert result["formulaVersion"] == "chip-reference-v1"
    assert result["largeHolderTrend"]["status"] == "pass"
    assert result["shareholderCountTrend"]["status"] == "pass"
    assert result["directorSupervisor12m"]["status"] == "pass"
    assert result["largeHolderTrend"]["rawValues"] == [41.0, 41.5, 42.0]
    assert result["directorSupervisor12m"]["period"] == "2026-08 vs 2025-08"
    assert result["sourceRefs"] == ["old", "new"]


def test_chip_reference_unknowns_missing_nonconsecutive_and_denominator_mismatch():
    data = [row for row in rows() if row["period"] != "2026-07"]
    data[-1]["directorDenominator"] = 1100

    result = evaluate_chip_reference(data)

    assert result["status"] == "unknown"
    assert result["largeHolderTrend"]["status"] == "unknown"
    assert result["shareholderCountTrend"]["status"] == "unknown"
    assert result["directorSupervisor12m"]["status"] == "unknown"


def test_chip_reference_never_uses_institutional_daily_proxy():
    result = evaluate_chip_reference([], institutional_daily=[{"netShares": 100}, {"netShares": 200}, {"netShares": 300}])

    assert result["status"] == "unknown"
    assert result["largeHolderTrend"]["status"] == "unknown"
    assert result["shareholderCountTrend"]["status"] == "unknown"


def test_unknown_indicators_keep_renderable_value_and_period_strings():
    result = evaluate_chip_reference([])

    for key in ("largeHolderTrend", "directorSupervisor12m", "shareholderCountTrend"):
        assert result[key]["value"] == "—"
        assert result[key]["period"] == "—"
        assert "rawValues" not in result[key]


def test_completed_calendar_months_ignore_current_month_and_other_field_periods():
    data = [
        {"period": "2026-07", "largeHolderPct": 40, "shareholderCount": 300, "sourceRefs": ["jul"]},
        {"period": "2026-08", "largeHolderPct": 41, "shareholderCount": 200, "sourceRefs": ["aug"]},
        {"period": "2026-09", "largeHolderPct": 42, "shareholderCount": 100, "sourceRefs": ["sep"]},
        {"period": "2026-10", "largeHolderPct": 1, "shareholderCount": 900, "sourceRefs": ["partial"]},
        {"period": "2026-09", "directorSupervisorPct": 0, "directorDenominator": 1000, "sourceRefs": ["director"]},
        {"period": "2025-09", "directorSupervisorPct": 0, "directorDenominator": 1000, "sourceRefs": ["prior"]},
    ]
    result = evaluate_chip_reference(data, evaluation_date="2026-10-02")
    assert result["status"] == "pass"
    assert result["largeHolderTrend"]["period"] == "2026-07..2026-09"
    assert result["largeHolderTrend"]["sourceRefs"] == ["jul", "aug", "sep"]
    assert result["directorSupervisor12m"]["sourceRefs"] == ["director", "prior"]
    assert "partial" not in result["sourceRefs"]
    assert result["availableAt"] is None


def test_missing_required_completed_month_never_falls_back_and_keeps_partial_values():
    data = [{"period": f"2026-{month:02d}", "largeHolderPct": month, "sourceRefs": [str(month)]} for month in (6, 7, 8)]
    result = evaluate_chip_reference(data, evaluation_date="2026-10-02")
    check = result["largeHolderTrend"]
    assert check["status"] == "unknown"
    assert check["period"] == "2026-07..2026-09"
    assert check["value"] == "7 → 8 → ?"
    assert "rawValues" not in check
    assert check["sourceRefs"] == ["7", "8"]


def test_independent_fields_without_evaluation_date_and_invalid_latest_director():
    data = rows() + [{"period": "2026-09", "directorSupervisorPct": None, "directorDenominator": 1000}]
    result = evaluate_chip_reference(data)
    assert result["largeHolderTrend"]["status"] == "pass"
    assert result["shareholderCountTrend"]["status"] == "pass"
    assert result["directorSupervisor12m"]["status"] == "unknown"
    assert result["directorSupervisor12m"]["period"] == "2026-09 vs 2025-09"


def test_explicit_invalid_latest_field_stays_unknown_without_older_fallback():
    data = rows() + [{"period": "2026-09", "largeHolderPct": None}]
    result = evaluate_chip_reference(data)
    assert result["largeHolderTrend"]["status"] == "unknown"
    assert result["largeHolderTrend"]["period"] == "2026-07..2026-09"
    assert result["shareholderCountTrend"]["status"] == "pass"


def test_future_publications_excluded_and_real_available_timestamp_only():
    data = [{"period": f"2026-{month:02d}", "largeHolderPct": month, "asOf": "2026-10-02", "publishedAt": published, "sourceRefs": [str(month)]} for month, published in ((7, "2026-08-01"), (8, "2026-09-01"), (9, "2026-10-03"))]
    result = evaluate_chip_reference(data, evaluation_date="2026-10-02")
    assert result["largeHolderTrend"]["status"] == "unknown"
    assert result["availableAt"] == "2026-09-01"
    assert result["largeHolderTrend"]["sourceRefs"] == ["7", "8"]
    assert evaluate_chip_reference([{"period": "2026-09", "asOf": "2026-10-02"}])["availableAt"] is None


def test_equal_trend_fails_and_director_missing_exact_prior_is_unknown():
    data = rows()
    data[2] = {**data[2], "largeHolderPct": 41.0, "shareholderCount": 12900}
    data[0] = {**data[0], "period": "2025-07"}
    result = evaluate_chip_reference(data)
    assert result["largeHolderTrend"]["status"] == "fail"
    assert result["shareholderCountTrend"]["status"] == "fail"
    assert result["directorSupervisor12m"]["status"] == "unknown"
    assert result["directorSupervisor12m"]["value"] == "10.5% vs ?%"


def test_observed_fields_ignore_unrelated_null_defaults_and_date_crosses_year():
    data = [{"period": period, "largeHolderPct": value, "shareholderCount": 400 - value, "directorSupervisorPct": None, "observedFields": ["largeHolderPct", "shareholderCount"]} for period, value in (("2025-10", 10), ("2025-11", 11), ("2025-12", 12))]
    data += [{"period": "2026-01", "largeHolderPct": None, "shareholderCount": None, "directorSupervisorPct": 5, "directorDenominator": 1000, "observedFields": ["directorSupervisorPct"]}]
    dated = evaluate_chip_reference(data, evaluation_date="2026-01-15")
    assert dated["largeHolderTrend"]["status"] == "pass"
    assert dated["largeHolderTrend"]["period"] == "2025-10..2025-12"
    assert dated["directorSupervisor12m"]["status"] == "unknown"
    assert evaluate_chip_reference(data)["largeHolderTrend"]["status"] == "pass"


def test_availability_uses_latest_true_metadata_and_ignores_unused_same_source_rows():
    data = [{"period": f"2026-{month:02d}", "largeHolderPct": month, "sourceRefs": ["shared"], "publishedAt": f"2026-{month:02d}-28"} for month in (6, 7, 8, 9)]
    data[-1] = {**data[-1], "availableAt": "2026-09-29", "publishedAt": "2026-10-03"}
    check = evaluate_chip_reference(data, evaluation_date="2026-10-02")
    assert check["largeHolderTrend"]["status"] == "unknown"
    assert check["availableAt"] == "2026-08-28"


def test_decreasing_director_fails_with_valid_zero_and_exact_prior():
    result = evaluate_chip_reference([
        {"period": "2026-09", "directorSupervisorPct": 0, "directorDenominator": 1000},
        {"period": "2025-09", "directorSupervisorPct": 1, "directorDenominator": 1000},
    ])
    assert result["directorSupervisor12m"]["status"] == "fail"
    assert result["directorSupervisor12m"]["value"] == "0% vs 1%"


def test_director_rejects_explicit_identity_total_or_scope_incomparability():
    baseline = [
        {"period": "2026-09", "directorSupervisorPct": 20, "directorDenominator": 1000, "directorScope": ["董事本人"]},
        {"period": "2025-09", "directorSupervisorPct": 10, "directorDenominator": 1000, "directorScope": ["董事本人"]},
    ]
    for fields in ({"directorIdentityConsistent": False}, {"directorTotalMatches": False}, {"directorTotalConsistent": False}, {"comparabilityStatus": "unsafe"}, {"directorScope": ["董事本人", "董事長本人"]}):
        result = evaluate_chip_reference([{**baseline[0], **fields}, baseline[1]])
        assert result["directorSupervisor12m"]["status"] == "unknown"


def test_unknown_director_percentage_preserves_verified_official_shares_and_backfill():
    result = evaluate_chip_reference([{
        "period": "2026-09", "directorSupervisorPct": None, "officialDirectorSupervisorShares": 123456,
        "directorDenominator": None, "sourceDate": "2026-09", "retrievedAt": "2026-10-04T11:00:00Z",
        "historicalBackfill": True, "sourceRefs": ["mops-sep"],
    }], evaluation_date="2026-10-02")
    check = result["directorSupervisor12m"]
    assert check["status"] == "unknown"
    assert check["value"] == "官方合計 123456股；比例待補"
    assert check["sourceDates"] == ["2026-09"]
    assert check["historicalBackfill"] is True
    assert check["retrievedAt"] == "2026-10-04T11:00:00Z"
    assert "rawValues" not in check
    assert result["availableAt"] is None


def test_merged_source_observations_keep_field_specific_refs_and_dates():
    data = []
    for month in (7, 8, 9):
        observation = {"period": f"2026-{month:02d}", "sourceDate": f"2026-{month:02d}-25", "largeHolderPct": month, "sourceRefs": [f"tdcc-{month}"], "observedFields": ["largeHolderPct"]}
        unrelated = {"period": f"2026-{month:02d}", "directorSupervisorPct": None, "sourceRefs": [f"director-{month}"], "observedFields": ["directorSupervisorPct"]}
        data.append({**observation, "sourceRefs": observation["sourceRefs"] + unrelated["sourceRefs"], "sourceObservations": [observation, unrelated]})
    check = evaluate_chip_reference(data, evaluation_date="2026-10-02")["largeHolderTrend"]
    assert check["status"] == "pass"
    assert check["sourceRefs"] == ["tdcc-7", "tdcc-8", "tdcc-9"]
    assert check["sourceDates"] == ["2026-07-25", "2026-08-25", "2026-09-25"]


def test_conflicting_same_date_observations_are_unknown_independent_of_input_order():
    prefix = [{"period": f"2026-{month:02d}", "sourceDate": f"2026-{month:02d}-25", "largeHolderPct": month + 3, "shareholderCount": 100 - month} for month in (7, 8)]
    latest = {"period": "2026-09", "sourceDate": "2026-09-25", "largeHolderPct": 12, "shareholderCount": 91, "sourceRefs": ["first"]}
    conflict = {**latest, "largeHolderPct": 9, "sourceRefs": ["second"]}
    for tail in ([latest, conflict], [conflict, latest]):
        result = evaluate_chip_reference(prefix + tail, evaluation_date="2026-10-02")
        assert result["largeHolderTrend"]["status"] == "unknown"
        assert result["largeHolderTrend"]["period"] == "2026-07..2026-09"
        assert "9／12（資料衝突）" in result["largeHolderTrend"]["value"]
        assert "rawValues" not in result["largeHolderTrend"]
        assert set(result["largeHolderTrend"]["sourceRefs"]) == {"first", "second"}
        assert result["shareholderCountTrend"]["status"] == "pass"


def test_latest_official_week_in_month_selected_independent_of_row_order():
    data = [{"period": f"2026-{month:02d}", "sourceDate": f"2026-{month:02d}-25", "largeHolderPct": month} for month in (7, 8, 9)]
    earlier = {"period": "2026-09", "sourceDate": "2026-09-18", "largeHolderPct": 1}
    assert evaluate_chip_reference(data + [earlier], evaluation_date="2026-10-02")["largeHolderTrend"]["rawValues"] == [7, 8, 9]


def test_director_same_period_conflicts_never_pass_in_either_order():
    prior = {"period": "2025-09", "directorSupervisorPct": 10, "directorDenominator": 1000}
    latest = {"period": "2026-09", "directorSupervisorPct": 20, "directorDenominator": 1000}
    conflict = {**latest, "directorSupervisorPct": 5}
    for data in ([prior, latest, conflict], [prior, conflict, latest]):
        check = evaluate_chip_reference(data)["directorSupervisor12m"]
        assert check["status"] == "unknown"
        assert "5／20%（資料衝突）" in check["value"]
        assert "rawValues" not in check
