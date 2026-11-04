from datetime import datetime

import pytest

from scripts.run_peg_repair import dated_evidence, validate_inputs


def release():
    stocks = [{"code": f"{i:04d}"} for i in range(100)]
    return {"marketDate": "2026-11-03", "stocks": stocks,
            "rankings": {"selected": [{"code": f"{i:04d}"} for i in range(21)]}}


def test_validate_inputs_requires_current_date_and_full_universe():
    manifest = {"marketDate": "2026-11-03", "stocks": []}
    assert len(validate_inputs("2026-11-03", "req-1", manifest, release())) == 100
    with pytest.raises(ValueError, match="current latest"):
        validate_inputs("2026-11-02", "req-1", manifest, release())


def test_validate_inputs_rejects_ranked_code_outside_full_stock_universe():
    baseline = release()
    baseline["rankings"]["selected"].append({"code": "9999"})
    with pytest.raises(ValueError, match="rankings contain"):
        validate_inputs("2026-11-03", "req-1", {"marketDate": "2026-11-03", "stocks": []}, baseline)


def test_dated_evidence_stamps_unpublished_rows_and_keeps_published_date():
    manifest = {"marketDate": "2026-11-03", "stocks": [{"code": "0001"}, {"code": "0002"}]}
    parsed = [{"code": "0001", "records": [{"period": "2026-Q2", "publishedDate": None}], "sources": []},
              {"code": "0002", "records": [{"period": "2026-Q2", "publishedDate": None, "observedAt": "2026-11-03T01:02:03Z"}], "sources": []}]
    payload = dated_evidence(manifest, parsed, "2026-11-03")
    stamped = payload["stocks"][0]["records"][0]["observedAt"]
    assert datetime.fromisoformat(stamped.replace("Z", "+00:00")).utcoffset() is not None
    assert payload["stocks"][1]["records"][0]["observedAt"] == "2026-11-03T01:02:03Z"
    assert payload["marketDate"] == "2026-11-03"


def test_empty_manifest_yields_empty_evidence_and_no_parse_failure():
    assert dated_evidence({"stocks": []}, [], "2026-11-03") == {"marketDate": "2026-11-03", "stocks": []}


def test_review_proof_keeps_candidate_lineage():
    from scripts.run_peg_repair import review_lineage
    manifest = {'prepareRunId': '123', 'prepareRunAttempt': 2, 'candidateSha256': 'a' * 64}
    assert review_lineage(manifest) == manifest
    assert review_lineage({'marketDate': '2026-11-03'}) == {}
