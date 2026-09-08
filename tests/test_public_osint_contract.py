from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import probe_public_sources as probe
from scripts.validate_public_contract import validate_files


ROOT = Path(__file__).resolve().parents[1]
CRITERIA = ROOT / "calibration" / "criteria_registry.json"
SOURCES = ROOT / "calibration" / "source_registry.json"


def test_registries_are_valid_and_exactly_7x33():
    result = validate_files(CRITERIA, SOURCES)
    assert result["ok"] is True
    assert result["criteria"]["group_counts"] == {
        "safety": 6,
        "dividend": 5,
        "growth": 5,
        "value": 6,
        "turnaround": 3,
        "continuity": 5,
        "chip": 3,
    }
    assert result["criteria"]["total_criteria"] == 33


def test_sources_allow_free_fallbacks_but_not_paid_apis():
    source_registry = json.loads(SOURCES.read_text(encoding="utf-8"))
    policy = source_registry["policy"]
    assert policy["paid_api"] is False
    assert policy["free_fallbacks"] == ["FinMind", "yfinance"]
    assert policy["free_quota_budget_required"] is True
    assert "FinMind" not in policy["rejected_providers"]
    assert "yfinance" not in policy["rejected_providers"]
    for source in source_registry["sources"]:
        assert "password" not in source["url"].lower()
        assert "token=" not in source["url"].lower()


def test_json_rows_supports_twse_object_with_fields():
    payload = {
        "fields": ["證券代號", "本益比"],
        "data": [["2330", "28.52"]],
    }
    rows = probe._rows(payload)
    assert rows == [{"證券代號": "2330", "本益比": "28.52"}]


def test_json_rows_normalizes_real_tdcc_bom_key():
    rows = probe._rows([{chr(0xFEFF) + "資料年月": "11507", "股票代號": "2330"}])
    assert rows == [{"資料年月": "11507", "股票代號": "2330"}]


def test_probe_json_rejects_missing_target_and_required_field(monkeypatch):
    payload = [{"公司代號": "1101", "資料年月": "11507"}]
    monkeypatch.setattr(
        probe,
        "request_text",
        lambda *args, **kwargs: probe.Response(
            "https://example.invalid", "GET", 200, "application/json", json.dumps(payload), 50
        ),
    )
    result = probe.probe_json(
        "fixture",
        "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
        allowed_hosts={"openapi.twse.com.tw"},
        required_fields=["公司代號", "資料年月", "營業收入-去年同月增減(%)"],
        target_code="2330",
    )
    assert result["status"] == "FAIL"
    assert "營業收入-去年同月增減(%)" in result["missing_required_fields"]
    assert result["target_present"] is False


def test_mops_probe_uses_isnew_false_and_validates_period(monkeypatch):
    calls = []
    body = "<h2>民國114年第4季</h2><td>合併現金流量表</td><td>營業活動之淨現金流入（流出）</td><td>投資活動之淨現金流入（流出）</td>"

    def fake_request(url, **kwargs):
        calls.append((url, kwargs))
        return probe.Response(url, "POST", 200, "text/html", body, len(body.encode()))

    monkeypatch.setattr(probe, "request_text", fake_request)
    result = probe._mops_form(
        "mops.cashflow_history",
        "https://mopsov.twse.com.tw/mops/web/ajax_t164sb05",
        allowed_hosts={"mopsov.twse.com.tw"},
        market="sii",
        code="2330",
        year="114",
        season="04",
        markers=["合併現金流量表", "營業活動之淨現金流入（流出）", "投資活動之淨現金流入（流出）"],
        timeout=5,
    )
    assert result["status"] == "PASS"
    assert result["period_match"] is True
    assert calls[0][1]["form"]["isnew"] == "false"
    assert calls[0][1]["form"]["year"] == "114"
    assert calls[0][1]["form"]["season"] == "04"


def test_tdcc_query_does_not_expose_synchronizer_token(monkeypatch):
    initial = (
        '<input name="SYNCHRONIZER_TOKEN" value="secret-token">'
        '<option value="20260904">最新</option><option value="20250912">舊</option>'
    )
    queried = "<div>2330 台積電</div><div>持股/單位數分級</div>"
    responses = iter(
        [
            probe.Response("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", "GET", 200, "text/html", initial, len(initial)),
            probe.Response("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", "POST", 200, "text/html", queried, len(queried)),
        ]
    )
    seen_forms = []

    def fake_request(url, **kwargs):
        if kwargs.get("form"):
            seen_forms.append(kwargs["form"])
        return next(responses)

    monkeypatch.setattr(probe, "request_text", fake_request)
    result = probe.probe_tdcc_query({"www.tdcc.com.tw"}, timeout=5)
    assert result["status"] == "PASS"
    assert "token_present" not in result
    assert "secret-token" not in json.dumps(result, ensure_ascii=False)
    assert seen_forms[0]["SYNCHRONIZER_TOKEN"] == "secret-token"


def test_free_fallback_smoke_is_blocked_without_budget(monkeypatch):
    registry = json.loads(SOURCES.read_text(encoding="utf-8"))
    # Avoid network: replace every probe function with a deterministic result.
    monkeypatch.setattr(probe, "probe_oas", lambda *args, **kwargs: {"status": "PASS", "source_id": args[0]})
    monkeypatch.setattr(probe, "probe_json", lambda *args, **kwargs: {"status": "PASS", "source_id": args[0]})
    monkeypatch.setattr(probe, "probe_dataset", lambda *args, **kwargs: {"status": "PASS", "source_id": args[0]})
    monkeypatch.setattr(probe, "probe_csv", lambda *args, **kwargs: {"status": "PASS", "source_id": args[0]})
    monkeypatch.setattr(probe, "probe_tdcc_query", lambda *args, **kwargs: {"status": "PASS", "source_id": "tdcc.historical_query"})
    monkeypatch.setattr(probe, "probe_mops_sources", lambda *args, **kwargs: [])
    report = probe.run_probe(registry, timeout=1, enable_free_fallback_smoke=True, free_fallback_budget=0)
    assert report["free_fallback"]["status"] == "BLOCKED"
    assert report["free_fallback"]["transport_calls"] == 0
