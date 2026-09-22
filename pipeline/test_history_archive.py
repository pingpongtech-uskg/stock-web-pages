from datetime import date
import json
from pipeline.history_archive import (
    canonical_json_bytes, month_filename, project_release_to_history,
    merge_month, prune_to_retention, revision_for_record,
)


def release(day="2026-09-18", run="r1", freshness="current"):
    return {"marketDate": day, "generatedAt":"2026-09-18T10:00:00Z", "runId":run,
            "freshness":freshness, "statusMessage":"ok", "formulaVersions":{},
            "funnel":{"universe":2,"priceComplete":2,"valuationComplete":2,"growthValuationComplete":1,"pegCandidates":1,"growthCandidates":1,"strategyCandidates":{"trust":1,"growth":1,"lowPosition":0},"formalValuations":1,"proxyValuations":1},
            "sourceRefs":["source"], "rankings":{"trust":[{"rank":1,"code":"2330","name":"台積電","sector":"半導體","status":"pass","reason":"可用"}],"growth":[],"lowPosition":[]},
            "stocks":[{"code":"SECRET","priceSeries":[1,2],"financialInputs":{"x":1}}]}


def test_projection_is_compact_and_revision_is_not_self_referential():
    record = project_release_to_history(release())
    assert "priceSeries" not in json.dumps(record, ensure_ascii=False)
    assert record["revision"] == revision_for_record(record)
    assert record["revision"] not in canonical_json_bytes({k:v for k,v in record.items() if k != "revision"}).decode()


def test_merge_replaces_duplicate_and_sorts_dates():
    merged = merge_month([], project_release_to_history(release("2026-09-18", "old")))
    merged = merge_month(merged, project_release_to_history(release("2026-09-17", "older")))
    merged = merge_month(merged, project_release_to_history(release("2026-09-18", "new")))
    assert [r["marketDate"] for r in merged] == ["2026-09-17", "2026-09-18"]
    assert merged[-1]["runId"] == "new"


def test_null_market_date_is_blocked_and_retention_is_calendar_days():
    import pytest
    with pytest.raises(ValueError):
        project_release_to_history({**release(), "marketDate": None})
    records = [project_release_to_history(release(f"2025-09-{day:02d}", str(day))) for day in (20,21)]
    kept = prune_to_retention({"2025-09": records}, date(2026,9,22), 366)
    assert kept == {}


def test_month_filename_uses_hash_prefix():
    payload = canonical_json_bytes({"month":"2026-09","records":[]})
    assert month_filename("2026-09", payload).startswith("2026-09.")
    assert month_filename("2026-09", payload).endswith(".json")
