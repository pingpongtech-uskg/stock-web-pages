from pipeline.health_checks import CATEGORY_DEFINITIONS, empty_health_categories, evaluate_category, evaluate_snapshot_health, health_totals


def test_thresholds_match_seven_category_contract():
    assert [(key, total, threshold) for key, _label, threshold, labels in CATEGORY_DEFINITIONS for total in [len(labels)]] == [
        ("quality", 5, 3), ("growth", 5, 4), ("chip", 3, 1), ("cheap", 6, 5),
        ("turnaround", 3, 1), ("antiPitfall", 6, 6), ("dividend", 5, 5),
    ]


def test_unknown_is_not_counted_as_pass():
    checks = [{"status": "pass"}, {"status": "unknown"}, {"status": "unknown"}, {"status": "unknown"}, {"status": "unknown"}]
    result = evaluate_category("growth", checks)
    assert result["passCount"] == 1
    assert result["status"] == "unknown"
    assert health_totals([result])["status"] == "unknown"


def test_known_failure_can_fail_without_all_fields():
    checks = [{"status": "fail"}, {"status": "fail"}, {"status": "unknown"}, {"status": "unknown"}, {"status": "unknown"}]
    assert evaluate_category("growth", checks)["status"] == "fail"


def test_monthly_revenue_rule_is_evaluated_from_snapshot():
    rows = []
    for year, values in [(2024, [10, 11, 12]), (2025, [12, 13, 14])]:
        for month, value in enumerate(values, 1):
            rows.append({"month": f"{year}-{month:02d}", "revenue": value})
    categories = evaluate_snapshot_health({"revenueMonthly": rows}, refs=["fixture"])
    growth = next(category for category in categories if category["key"] == "growth")
    assert growth["checks"][0]["status"] == "pass"
    assert growth["passCount"] == 1


def test_official_valuation_proxies_are_explicit():
    categories = evaluate_snapshot_health({
        "revenueMonthly": [],
        "healthInputs": {
            "valuationCurrent": {"pe": 10, "pb": 1.2, "dividendYield": 7.0},
            "valuationUniverse": [{"pe": 8, "pb": 1}, {"pe": 12, "pb": 2}],
        },
    })
    cheap = next(item for item in categories if item["key"] == "cheap")
    assert cheap["checks"][1]["status"] == "pass"
    assert "橫截面代理" in cheap["checks"][1]["explanation"]
    assert next(item for item in categories if item["key"] == "turnaround")["checks"][0]["status"] == "pass"
