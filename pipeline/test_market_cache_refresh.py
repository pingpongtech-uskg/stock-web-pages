"""Exercise live volume receipt wiring and network-free recomputation."""
import json

import pytest

import scripts.refresh_snapshot as refresh


def test_live_volume_receipts_receive_validated_calendar(tmp_path, monkeypatch):
    calendar = {"schemaVersion": "trading-calendar-v1", "timezone": "Asia/Taipei", "year": 2026,
                "closedDates": ["2026-09-28"], "openExceptions": []}
    (tmp_path / "trading-calendar.json").write_text(json.dumps(calendar))
    calls = []
    monkeypatch.setattr(refresh, "build_00631l_volume_indicator", lambda day, **kwargs: calls.append((day, kwargs)) or {"status": "available"})
    cache = tmp_path / "receipts"
    result = refresh.release_volume_indicator(tmp_path, {}, "2026-10-02", offline=False,
                                             recompute_existing=False, source_cache_dir=cache)
    assert result["status"] == "available"
    assert calls == [("2026-10-02", {"source_cache_dir": cache, "calendar": calendar})]


@pytest.mark.parametrize("offline,recompute", [(True, False), (False, True)])
def test_cached_volume_never_fetches_or_creates_receipts(tmp_path, monkeypatch, offline, recompute):
    def unexpected(*args, **kwargs):
        raise AssertionError("cached recomputation fetched volume")
    monkeypatch.setattr(refresh, "build_00631l_volume_indicator", unexpected)
    indicator = {"marketDate": "2026-10-01", "status": "available", "currentVolume": 0}
    result = refresh.release_volume_indicator(tmp_path, {"marketIndicators": {"volumeMultiple00631L": indicator}},
                                             "2026-10-02", offline=offline, recompute_existing=recompute,
                                             source_cache_dir=tmp_path / "receipts")
    assert result == indicator
    assert not (tmp_path / "receipts").exists()


def test_receipt_capture_rejects_closed_calendar_before_network(tmp_path, monkeypatch):
    calendar = {"schemaVersion": "trading-calendar-v1", "timezone": "Asia/Taipei", "year": 2026,
                "closedDates": ["2026-10-02"], "openExceptions": []}
    (tmp_path / "trading-calendar.json").write_text(json.dumps(calendar))
    monkeypatch.setattr(refresh, "build_00631l_volume_indicator", lambda *args, **kwargs: pytest.fail("network before calendar validation"))
    with pytest.raises(ValueError, match="market cache calendar"):
        refresh.release_volume_indicator(tmp_path, {}, "2026-10-02", offline=False,
                                         recompute_existing=False, source_cache_dir=tmp_path / "receipts")
