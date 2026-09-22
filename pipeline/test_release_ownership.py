from pipeline.release_contract import chip_reference_error
from scripts.refresh_snapshot import attach_chip_references


def chip(status="unknown"):
    indicator = {"status": "unknown", "value": "—", "period": "—", "sourceRefs": []}
    return {
        "schemaVersion": "chip-reference-v1",
        "displayOnly": True,
        "formulaVersion": "chip-reference-v1",
        "dataFreshness": "unavailable",
        "status": status,
        "sourceRefs": [],
        "largeHolderTrend": dict(indicator),
        "directorSupervisor12m": dict(indicator),
        "shareholderCountTrend": dict(indicator),
    }


def test_chip_reference_contract_accepts_unavailable_without_rejecting_strategy_rows():
    assert chip_reference_error(chip(), "2330") is None


def test_chip_reference_contract_rejects_non_display_only_or_wrong_formula():
    value = chip()
    value["displayOnly"] = False
    assert chip_reference_error(value, "2330") == "chip_reference_display_only:2330"
    value["displayOnly"] = True
    value["formulaVersion"] = "wrong"
    assert chip_reference_error(value, "2330") == "chip_reference_formula_version:2330"


def test_chip_reference_contract_rejects_non_renderable_indicator_fields():
    value = chip()
    del value["largeHolderTrend"]["value"]
    assert chip_reference_error(value, "2330") == "chip_reference_indicator_value:largeHolderTrend:2330"


def test_attach_chip_references_covers_summary_and_every_strategy_row():
    details = [{"code": "2330"}]
    rankings = {"trust": [{"code": "2330"}], "growth": [], "lowPosition": [], "lowBase": [], "lowBaseGrowth": [], "lowBaseQuality": []}
    details_result, rankings_result = attach_chip_references(details, rankings, {"2330": chip()})
    assert details_result[0]["chipReference"]["displayOnly"] is True
    assert details_result[0]["chipReference"]["formulaVersion"] == "chip-reference-v1"
    assert rankings_result["trust"][0]["chipReference"]["status"] == "unknown"
