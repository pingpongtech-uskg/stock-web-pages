import json

from scripts.fetch_research_universe import stale_previous_config


def test_stale_previous_config_marks_copy_without_mutating_source(tmp_path):
    path = tmp_path / "tracked_symbols.json"
    original = {"symbols": ["2330"], "universe": {"rows": [{"code": "2330"}]}}
    path.write_text(json.dumps(original), encoding="utf-8")

    stale = stale_previous_config(path, "OfficialInstitutionalError: timeout")

    assert stale["stale"] is True
    assert stale["staleReason"].startswith("OfficialInstitutionalError")
    assert json.loads(path.read_text(encoding="utf-8")) == original
