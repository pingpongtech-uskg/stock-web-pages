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
