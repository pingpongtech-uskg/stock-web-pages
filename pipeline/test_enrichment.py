from pipeline.enrichment import low_base_growth_gates, low_base_quality_gates


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
