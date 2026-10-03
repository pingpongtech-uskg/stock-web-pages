import json
from datetime import date
import pytest

from scripts.fetch_research_universe import stale_previous_config


def test_stale_previous_config_marks_copy_without_mutating_source(tmp_path):
    path = tmp_path / "tracked_symbols.json"
    original = {"symbols": ["2330"], "universe": {"rows": [{"code": "2330"}]}}
    path.write_text(json.dumps(original), encoding="utf-8")

    stale = stale_previous_config(path, "OfficialInstitutionalError: timeout")

    assert stale["stale"] is True
    assert stale["staleReason"].startswith("OfficialInstitutionalError")
    assert json.loads(path.read_text(encoding="utf-8")) == original


@pytest.mark.parametrize("as_of", ["2026-10-02", None])
def test_official_cli_forwards_target_date_and_preserves_default(tmp_path, monkeypatch, as_of):
    import scripts.fetch_research_universe as fetch
    calls = []
    snapshots = [{"date": "2026-10-02", "rows": [{"code": "2330", "netShares": 1}]}]
    monkeypatch.setattr(fetch, "fetch_recent_complete_days", lambda **kwargs: calls.append(kwargs) or snapshots)
    monkeypatch.setattr(fetch, "update_official_tracked_config", lambda received, path: {
        "symbols": ["2330"], "requestedDate": received[0]["date"]})
    output = tmp_path / "universe.json"
    argv = ["fetch_research_universe.py", "--source", "official", "--output", str(output), "--print-codes"]
    if as_of:
        argv += ["--as-of", as_of]
    monkeypatch.setattr("sys.argv", argv)
    assert fetch.main() == 0
    assert calls == [{"as_of": date(2026, 10, 2) if as_of else None, "sessions": 11, "lookback_days": 35}]
    assert json.loads(output.read_text())["requestedDate"] == "2026-10-02"


@pytest.mark.parametrize("as_of", ["2026-02-30", "20261002", "2026-10", "2026-10-02junk"])
def test_invalid_target_date_exits_before_source_requests_or_writes(tmp_path, monkeypatch, as_of):
    import scripts.fetch_research_universe as fetch
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid date must not access source or write output")
    monkeypatch.setattr(fetch, "fetch_recent_complete_days", forbidden)
    monkeypatch.setattr(fetch, "update_official_tracked_config", forbidden)
    monkeypatch.setattr(fetch, "atomic_json", forbidden)
    config = tmp_path / "tracked.json"
    config.write_text('{"symbols":["2330"]}')
    before = config.read_bytes()
    monkeypatch.setattr("sys.argv", ["fetch_research_universe.py", "--as-of", as_of,
        "--config", str(config), "--output", str(tmp_path / "universe.json")])
    with pytest.raises(SystemExit) as failure:
        fetch.main()
    assert failure.value.code == 2
    assert config.read_bytes() == before
    assert not (tmp_path / "universe.json").exists()


def test_official_api_forwards_historical_target_date(monkeypatch):
    import scripts.fetch_research_universe as fetch
    calls = []
    snapshots = [{"date": f"2026-09-{day:02d}", "rows": [{"code": "2330", "netShares": 1}]}
                 for day in range(30, 19, -1)]
    monkeypatch.setattr(fetch, "fetch_recent_complete_days", lambda **kwargs: calls.append(kwargs) or snapshots)
    result = fetch.fetch_official_universe(limit=1, as_of=date(2026, 10, 2))
    assert calls == [{"as_of": date(2026, 10, 2), "sessions": 11, "lookback_days": 35}]
    assert result["current"][0]["netShares"] == result["previous"][0]["netShares"] == 10


def test_official_api_collects_only_sessions_at_or_before_historical_target(monkeypatch):
    import scripts.fetch_research_universe as fetch
    import pipeline.official_institutional as official
    requested = []
    target = date(2026, 10, 2)
    def complete_day(day, **kwargs):
        assert kwargs.get('source_cache_dir') is None
        requested.append(day)
        return [{"code": "2330", "netShares": 1}] if day.weekday() < 5 else []
    monkeypatch.setattr(official, "fetch_complete_day", complete_day)
    result = fetch.fetch_official_universe(as_of=target)
    assert requested[0] == target
    assert all(day <= target for day in requested)
    assert len(result["snapshots"]) == 11
    assert result["snapshots"][0]["date"] == target.isoformat()
    assert all(date.fromisoformat(row["date"]).weekday() < 5 for row in result["snapshots"])


def test_official_cli_request_failure_does_not_publish_stale_output(tmp_path, monkeypatch):
    import scripts.fetch_research_universe as fetch
    config = tmp_path / "tracked.json"
    config.write_text('{"symbols":["2330"]}')
    output = tmp_path / "universe.json"
    output.write_text('{"marketDate":"2026-10-01"}')
    before = (config.read_bytes(), output.read_bytes())
    def unavailable(**kwargs):
        assert kwargs["as_of"] == date(2026, 10, 2)
        raise fetch.OfficialInstitutionalError("official endpoint unavailable")
    monkeypatch.setattr(fetch, "fetch_recent_complete_days", unavailable)
    monkeypatch.setattr("sys.argv", ["fetch_research_universe.py", "--source", "official", "--as-of", "2026-10-02",
        "--config", str(config), "--output", str(output)])
    assert fetch.main() == 1
    assert (config.read_bytes(), output.read_bytes()) == before


def test_legacy_cli_remains_compatible_and_preserves_existing_metadata(tmp_path, monkeypatch):
    import scripts.fetch_research_universe as fetch
    document = '<h2>投信買超前 200 名</h2><table>' + ''.join(
        f'<tr><td>{i+1}</td><td>{1000+i}</td><td>公司{i}</td><td>10</td><td>0</td><td>10</td></tr>'
        for i in range(100)) + '</table>'
    config = tmp_path / "tracked.json"
    config.write_text('{"metadata":{"1000":{"market":"TWSE","name":"old"}}}')
    monkeypatch.setattr(fetch, "fetch_document", lambda url: document)
    def forbidden(**kwargs):
        raise AssertionError("legacy source must not invoke official collector")
    monkeypatch.setattr(fetch, "fetch_recent_complete_days", forbidden)
    monkeypatch.setattr("sys.argv", ["fetch_research_universe.py", "--source", "legacy", "--config", str(config)])
    assert fetch.main() == 0
    payload = json.loads(config.read_text())
    assert len(payload["symbols"]) == 100
    assert payload["symbols"][:2] == ["1000", "1001"]
    assert payload["metadata"]["1000"] == {"market": "TWSE", "name": "公司0"}
    assert payload["stale"] is False


def test_full_source_capture_occurs_before_top100_subset_update(tmp_path, monkeypatch):
    import scripts.fetch_research_universe as fetch
    from scripts.test_build_market_cache_index import setup_inputs
    snapshots, kwargs = setup_inputs(tmp_path)
    calls = []
    monkeypatch.setattr(fetch, 'fetch_recent_complete_days', lambda **kw: calls.append(kw) or snapshots)
    def subset(received, path):
        assert (kwargs['source_cache_dir'] / 'institutional-TWSE-receipt-index.json').exists()
        assert len(received) == 11
        return {'symbols': ['1101']}
    monkeypatch.setattr(fetch, 'update_official_tracked_config', subset)
    monkeypatch.setattr('sys.argv', ['fetch.py', '--source', 'official', '--as-of', '2026-10-02', '--print-codes', '--source-cache-dir', str(kwargs['source_cache_dir'])])
    assert fetch.main() == 0
    assert calls[0]['source_cache_dir'] == kwargs['source_cache_dir']
