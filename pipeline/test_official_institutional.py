import json
import csv
import io
import urllib.parse
from datetime import date

import pytest

from pipeline.official_institutional import (
    OfficialInstitutionalError,
    aggregate_window,
    parse_tpex_payload,
    parse_twse_payload,
)


def test_tpex_request_matches_official_json_post_contract(monkeypatch):
    from pipeline.official_institutional import fetch_tpex_day, TPEX_ENDPOINT
    requests = []
    payload = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload
    def respond(request, **kwargs):
        requests.append(request)
        return Response()
    monkeypatch.setattr("urllib.request.urlopen", respond)
    rows = fetch_tpex_day(date(2026, 10, 2))
    assert len(requests) == 1
    request = requests[0]
    assert request.full_url.startswith(TPEX_ENDPOINT + "?")
    assert request.get_method() == "GET"
    assert urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query) == {
        "type": ["Daily"], "sect": ["AL"], "date": ["2026/10/02"], "response": ["csv"]}
    assert rows[0]["netShares"] == 97941


def test_tpex_fetch_persists_raw_receipt_before_writing_validated_metadata(monkeypatch, tmp_path):
    from pipeline.official_institutional import fetch_tpex_day
    payload = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    rows = fetch_tpex_day(date(2026, 10, 2), source_cache_dir=tmp_path)
    assert rows[0]["sellShares"] == 59
    raw_files = list(tmp_path.glob("inst-tpex-2026-10-02-*.raw.json"))
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == payload
    validated = json.loads((tmp_path / "institutional-TPEx-2026-10-02-validated.json").read_text())
    assert validated["rawSha256"]
    assert validated["reportedDate"] == "2026-10-02"
    assert validated["validated"] is True
    assert validated["codes"] == ["3081"]
    assert validated["unit"] == "shares"
    assert validated["encoding"] == "MS950"


def test_twse_fetch_persists_exact_raw_json_and_validated_code_roster(monkeypatch, tmp_path):
    from pipeline.official_institutional import fetch_twse_day
    payload = json.dumps({
        "date": "20261002", "fields": ["證券代號", "證券名稱", "買進股數", "賣出股數", "買賣超股數"],
        "data": [["2330", "台積電", "10", "3", "7"], ["0050", "ETF", "5", "2", "3"]],
    }, ensure_ascii=False).encode("utf-8")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    rows = fetch_twse_day(date(2026, 10, 2), source_cache_dir=tmp_path)
    assert len(rows) == 2
    raw_files = list(tmp_path.glob("inst-twse-2026-10-02-*.raw.json"))
    assert len(raw_files) == 1 and raw_files[0].read_bytes() == payload
    validated = json.loads((tmp_path / "institutional-TWSE-2026-10-02-validated.json").read_text())
    assert validated["codes"] == ["2330"]
    assert validated["reportedDate"] == "2026-10-02"
    assert validated["validated"] is True
    assert validated["encoding"] == "utf-8"


def test_twse_exact_official_no_data_response_is_cached_as_no_data_not_zero(monkeypatch, tmp_path):
    from pipeline.official_institutional import fetch_twse_day
    payload = json.dumps({"stat": "很抱歉，沒有符合條件的資料!"}, ensure_ascii=False).encode("utf-8")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    day = date(2026, 10, 3)
    assert fetch_twse_day(day, source_cache_dir=tmp_path) == []
    validated = json.loads((tmp_path / "institutional-TWSE-2026-10-03-validated.json").read_text())
    assert validated["status"] == "no_data"
    assert validated["codes"] == []
    assert validated["reportedDate"] == "2026-10-03"

    def unexpected_http(*args, **kwargs):
        raise AssertionError("validated no-data history should be replayed from cache")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_http)
    assert fetch_twse_day(day, source_cache_dir=tmp_path, refresh=False) == []


def test_twse_orphaned_exact_raw_capture_is_reparsed_and_validated_without_http(monkeypatch, tmp_path):
    from pipeline.official_institutional import fetch_twse_day
    payload = json.dumps({"stat": "很抱歉，沒有符合條件的資料!"}, ensure_ascii=False).encode("utf-8")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    day = date(2026, 10, 3)
    assert fetch_twse_day(day, source_cache_dir=tmp_path) == []
    (tmp_path / "institutional-TWSE-2026-10-03-validated.json").unlink()

    def unexpected_http(*args, **kwargs):
        raise AssertionError("a source-authenticated orphaned receipt should be reparsed locally")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_http)
    assert fetch_twse_day(day, source_cache_dir=tmp_path, refresh=False) == []
    validated = json.loads((tmp_path / "institutional-TWSE-2026-10-03-validated.json").read_text())
    assert validated["status"] == "no_data"
    assert validated["codes"] == []


def test_twse_byte_parser_validates_report_date_and_accepts_exact_no_data_sentinel():
    from pipeline.official_institutional import parse_twse_json_response
    day = date(2026, 10, 3)
    sentinel = json.dumps({"stat": "很抱歉，沒有符合條件的資料!"}, ensure_ascii=False).encode("utf-8")
    assert parse_twse_json_response(sentinel, expected_date=day) == []
    dated = json.dumps({
        "date": "20261002",
        "fields": ["證券代號", "證券名稱", "買進股數", "賣出股數", "買賣超股數"],
        "data": [["2330", "台積電", "10", "3", "7"]],
    }, ensure_ascii=False).encode("utf-8")
    assert parse_twse_json_response(dated, expected_date=date(2026, 10, 2))[0]["netShares"] == 7
    with pytest.raises(OfficialInstitutionalError, match="date"):
        parse_twse_json_response(dated, expected_date=day)


def test_twse_byte_parser_accepts_exact_historical_no_data_variant():
    from pipeline.official_institutional import parse_twse_json_response
    raw = json.dumps({
        "stat": "很抱歉，沒有符合條件的資料!", "hints": "單位：股", "total": 0,
    }, ensure_ascii=False).encode("utf-8")
    assert parse_twse_json_response(raw, expected_date=date(2026, 9, 28)) == []


def test_recent_snapshot_fetch_forwards_source_cache_directory(monkeypatch, tmp_path):
    import pipeline.official_institutional as official
    calls = []
    monkeypatch.setattr(official, "fetch_complete_day", lambda day, **kwargs: calls.append(kwargs) or [{"code": "2330"}])
    result = official.fetch_recent_complete_days(
        as_of=date(2026, 10, 2), sessions=1, lookback_days=1, source_cache_dir=tmp_path)
    assert result == [{"date": "2026-10-02", "rows": [{"code": "2330"}]}]
    assert calls == [{"source_cache_dir": tmp_path, "refresh": True, "include_evidence": True}]


def test_tpex_replays_verified_prior_day_without_http_and_refreshes_target(monkeypatch, tmp_path):
    from pipeline.official_institutional import fetch_tpex_day
    payload = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")
    calls = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload

    def respond(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", respond)
    day = date(2026, 10, 2)
    initial = fetch_tpex_day(day, source_cache_dir=tmp_path)
    assert len(calls) == 1

    def unexpected_http(*args, **kwargs):
        raise AssertionError("verified history cache should not call HTTP")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_http)
    assert fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=False) == initial

    monkeypatch.setattr("urllib.request.urlopen", respond)
    assert fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=True) == initial
    assert len(calls) == 2


def test_tpex_invalid_prior_cache_fails_closed_without_http(monkeypatch, tmp_path):
    from pipeline.official_institutional import fetch_tpex_day
    payload = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    day = date(2026, 10, 2)
    fetch_tpex_day(day, source_cache_dir=tmp_path)
    raw_file = next(tmp_path.glob("inst-tpex-2026-10-02-*.raw.json"))
    raw_file.write_bytes(raw_file.read_bytes() + b"tampered")

    def unexpected_http(*args, **kwargs):
        raise AssertionError("corrupt cache must fail closed rather than refetch")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_http)
    with pytest.raises(OfficialInstitutionalError, match="hash"):
        fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=False)


def test_tpex_wrong_day_cache_metadata_fails_closed_without_http(monkeypatch, tmp_path):
    from pipeline.official_institutional import fetch_tpex_day
    payload = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    day = date(2026, 10, 2)
    fetch_tpex_day(day, source_cache_dir=tmp_path)
    metadata_path = tmp_path / "institutional-TPEx-2026-10-02-validated.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["reportedDate"] = "2026-10-01"
    metadata_path.write_text(json.dumps(metadata))

    def unexpected_http(*args, **kwargs):
        raise AssertionError("wrong-date cache must fail closed rather than refetch")

    monkeypatch.setattr("urllib.request.urlopen", unexpected_http)
    with pytest.raises(OfficialInstitutionalError, match="market date"):
        fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=False)


@pytest.mark.parametrize(("field", "value", "message"), [
    ("unit", "lots", "market date"),
    ("rawSha256", "0" * 64, "raw reference"),
    ("codes", [], "projection"),
])
def test_tpex_cache_projection_and_source_contract_are_rechecked(monkeypatch, tmp_path, field, value, message):
    from pipeline.official_institutional import fetch_tpex_day
    payload = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    day = date(2026, 10, 2)
    fetch_tpex_day(day, source_cache_dir=tmp_path)
    metadata_path = tmp_path / "institutional-TPEx-2026-10-02-validated.json"
    metadata = json.loads(metadata_path.read_text())
    metadata[field] = value
    metadata_path.write_text(json.dumps(metadata))

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("invalid cache triggered HTTP"))
    with pytest.raises(OfficialInstitutionalError, match=message):
        fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=False)


def test_tpex_orphaned_receipt_with_wrong_request_date_fails_before_http(monkeypatch, tmp_path):
    from pipeline.official_institutional import fetch_tpex_day
    payload = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    day = date(2026, 10, 2)
    fetch_tpex_day(day, source_cache_dir=tmp_path)
    (tmp_path / "institutional-TPEx-2026-10-02-validated.json").unlink()
    receipt_path = next(tmp_path.glob("inst-tpex-2026-10-02-*.receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    receipt["requestDate"] = "2026-10-01"
    receipt_path.write_text(json.dumps(receipt))

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("invalid orphan triggered HTTP"))
    with pytest.raises(OfficialInstitutionalError, match="hash or lineage"):
        fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=False)


def test_tpex_partial_orphan_capture_without_receipt_fails_before_http(monkeypatch, tmp_path):
    from pipeline.official_institutional import fetch_tpex_day
    payload = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return payload[:size] if size >= 0 else payload

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    day = date(2026, 10, 2)
    fetch_tpex_day(day, source_cache_dir=tmp_path)
    (tmp_path / "institutional-TPEx-2026-10-02-validated.json").unlink()
    next(tmp_path.glob("inst-tpex-2026-10-02-*.receipt.json")).unlink()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("partial receipt triggered HTTP"))
    with pytest.raises(OfficialInstitutionalError, match="bytes are missing"):
        fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=False)


def test_tpex_parser_rejects_wrong_unit_header_and_extra_no_data_fields():
    from pipeline.official_institutional import parse_tpex_csv, parse_tpex_daily_response
    payload = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")
    malformed_header = payload.replace("投信-買進股數".encode("cp950"), "投信-買進張數".encode("cp950"))
    with pytest.raises(OfficialInstitutionalError, match="missing official field"):
        parse_tpex_csv(malformed_header, expected_date=date(2026, 10, 2))
    sentinel = {
        "stat": "無資料可供下載", "date": "20261003", "tables": [{
            "date": "115/10/03", "fields": ["欄位"] * 24, "data": [], "totalCount": 0,
        }],
    }
    with pytest.raises(OfficialInstitutionalError, match="unexpected JSON"):
        parse_tpex_daily_response(json.dumps({**sentinel, "unexpected": True}).encode(), expected_date=date(2026, 10, 3))
    with pytest.raises(OfficialInstitutionalError, match="date mismatch"):
        parse_tpex_daily_response(json.dumps({**sentinel, "date": "20261002"}).encode(), expected_date=date(2026, 10, 3))


def test_tpex_http_source_size_limit_fails_before_capturing_receipt(monkeypatch, tmp_path):
    from pipeline.official_institutional import MAX_TPEX_REPORT_BYTES, fetch_tpex_day

    class OversizeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return b"x" * size

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: OversizeResponse())
    with pytest.raises(OfficialInstitutionalError, match="response exceeds"):
        fetch_tpex_day(date(2026, 10, 2), source_cache_dir=tmp_path)
    assert not list(tmp_path.glob("*.raw.json"))


def test_tpex_http_error_is_wrapped_with_source_context(monkeypatch):
    from urllib.error import URLError
    from pipeline.official_institutional import fetch_tpex_day
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(URLError("offline")))
    with pytest.raises(OfficialInstitutionalError, match=r"refresh unavailable \(transport_error\)"):
        fetch_tpex_day(date(2026, 10, 2))


@pytest.mark.parametrize("market", ["TWSE", "TPEx"])
def test_same_day_verified_receipt_is_used_only_after_http_5xx_and_never_rewritten(monkeypatch, tmp_path, market):
    import hashlib
    import urllib.error
    import pipeline.official_institutional as official

    day = date(2026, 10, 2)
    twse_raw = json.dumps({"date":"20261002","fields":["證券代號","證券名稱","買進股數","賣出股數","買賣超股數"],
        "data":[["2330","台積電","10","3","7"]]}, ensure_ascii=False).encode()
    tpex_raw = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")
    raw = twse_raw if market == "TWSE" else tpex_raw
    fetch = official.fetch_twse_day if market == "TWSE" else official.fetch_tpex_day

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return raw[:size] if size >= 0 else raw

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    fetch(day, source_cache_dir=tmp_path)
    pointer = tmp_path / f"institutional-{market}-{day.isoformat()}-validated.json"
    before = pointer.read_bytes()
    metadata = json.loads(before)
    raw_path = tmp_path / metadata["rawFile"]
    original_raw = raw_path.read_bytes()
    original_sha = hashlib.sha256(original_raw).hexdigest()

    def upstream_520(*args, **kwargs):
        raise urllib.error.HTTPError("https://official.invalid", 520, "origin unavailable", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", upstream_520)
    rows, evidence = fetch(day, source_cache_dir=tmp_path, refresh=True, include_evidence=True)
    assert rows
    assert evidence == {
        "market": market, "requestDate": day.isoformat(), "reportedDate": day.isoformat(), "unit": "shares",
        "evidenceLevel": "verified_cached_after_refresh_failure", "rawSha256": original_sha,
        "retrievedAt": metadata["retrievedAt"], "refreshFailure": {"category": "http_5xx", "status": 520},
    }
    assert pointer.read_bytes() == before
    assert raw_path.read_bytes() == original_raw


@pytest.mark.parametrize("status", [403, 429])
def test_same_day_refresh_does_not_fallback_for_4xx_or_semantically_invalid_2xx(monkeypatch, tmp_path, status):
    import urllib.error
    import pipeline.official_institutional as official

    day = date(2026, 10, 2)
    raw = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return raw[:size] if size >= 0 else raw

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    official.fetch_tpex_day(day, source_cache_dir=tmp_path)

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(
        urllib.error.HTTPError("https://official.invalid", status, "denied", {}, None)))
    with pytest.raises(OfficialInstitutionalError):
        official.fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=True)

    monkeypatch.setattr(official, "_get_bytes", lambda *args, **kwargs: (b"not-a-report", None))
    with pytest.raises(OfficialInstitutionalError):
        official.fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=True)


@pytest.mark.parametrize("cache_state", ["missing", "corrupt"])
def test_http_5xx_requires_an_eligible_exact_date_cache(monkeypatch, tmp_path, cache_state):
    import urllib.error
    import pipeline.official_institutional as official

    day = date(2026, 10, 2)
    raw = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return raw[:size] if size >= 0 else raw

    if cache_state == "corrupt":
        monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
        official.fetch_tpex_day(day, source_cache_dir=tmp_path)
        metadata = json.loads((tmp_path / f"institutional-TPEx-{day.isoformat()}-validated.json").read_text())
        (tmp_path / metadata["rawFile"]).write_bytes(b"tampered")

    def upstream_520(*args, **kwargs):
        raise urllib.error.HTTPError("https://official.invalid", 520, "origin unavailable", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", upstream_520)
    with pytest.raises(official.OfficialInstitutionalRefreshError):
        official.fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=True, include_evidence=True)


def test_successful_same_day_refresh_supersedes_cached_receipt_and_reports_fresh_evidence(monkeypatch, tmp_path):
    import hashlib
    import pipeline.official_institutional as official

    day = date(2026, 10, 2)
    old_raw = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")
    new_raw = _tpex_csv("3081", "聯亞", "99,000", "59", "98,941")

    class Response:
        def __init__(self, payload): self.payload = payload
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return self.payload[:size] if size >= 0 else self.payload

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response(old_raw))
    official.fetch_tpex_day(day, source_cache_dir=tmp_path)
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response(new_raw))
    rows, evidence = official.fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=True, include_evidence=True)
    metadata = json.loads((tmp_path / f"institutional-TPEx-{day.isoformat()}-validated.json").read_text())
    assert rows[0]["netShares"] == 98941
    assert evidence["evidenceLevel"] == "fresh_response"
    assert evidence["rawSha256"] == hashlib.sha256(new_raw).hexdigest() == metadata["rawSha256"]


def test_raw_only_orphan_receipt_is_not_same_day_refresh_fallback(monkeypatch, tmp_path):
    import urllib.error
    import pipeline.official_institutional as official

    day = date(2026, 10, 2)
    raw = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return raw[:size] if size >= 0 else raw

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    official.fetch_tpex_day(day, source_cache_dir=tmp_path)
    (tmp_path / f"institutional-TPEx-{day.isoformat()}-validated.json").unlink()
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(
        urllib.error.HTTPError("https://official.invalid", 520, "origin unavailable", {}, None)))
    with pytest.raises(official.OfficialInstitutionalRefreshError):
        official.fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=True, include_evidence=True)


@pytest.mark.parametrize("failure", ["incomplete_read", "enter_error", "exit_error"])
def test_http_stream_transport_failures_can_use_exact_verified_same_day_receipt(monkeypatch, tmp_path, failure):
    import http.client
    import pipeline.official_institutional as official

    day = date(2026, 10, 2)
    raw = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")

    class GoodResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size=-1): return raw[:size] if size >= 0 else raw

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: GoodResponse())
    official.fetch_tpex_day(day, source_cache_dir=tmp_path)

    class BrokenResponse:
        def __enter__(self):
            if failure == "enter_error": raise OSError("connection dropped")
            return self
        def __exit__(self, *args):
            if failure == "exit_error": raise OSError("connection dropped")
            return False
        def read(self, size=-1):
            if failure == "incomplete_read": raise http.client.IncompleteRead(b"partial", 10)
            return raw[:size] if size >= 0 else raw

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: BrokenResponse())
    rows, evidence = official.fetch_tpex_day(day, source_cache_dir=tmp_path, refresh=True, include_evidence=True)
    assert rows[0]["netShares"] == 97941
    assert evidence["evidenceLevel"] == "verified_cached_after_refresh_failure"
    assert evidence["refreshFailure"] == {"category":"transport_error"}


def test_tpex_csv_contract_rejects_a_different_report_date(monkeypatch):
    import pipeline.official_institutional as official
    monkeypatch.setattr(official, "_get_bytes", lambda *args, **kwargs: (
        _tpex_csv("3081", "聯亞", "98,000", "59", "97,941", report_date="115年10月01日"), None))
    with pytest.raises(OfficialInstitutionalError, match="date"):
        official.fetch_tpex_day(date(2026, 10, 2))


def _tpex_csv(code, name, buy, sell, net, *, report_date="115年10月02日"):
    header = [
        "代號", "名稱", "外資及陸資(不含外資自營商)-買進股數", "外資及陸資(不含外資自營商)-賣出股數",
        "外資及陸資(不含外資自營商)-買賣超股數", "外資自營商-買進股數", "外資自營商-賣出股數",
        "外資自營商-買賣超股數", "外資及陸資-買進股數", "外資及陸資-賣出股數", "外資及陸資-買賣超股數",
        "投信-買進股數", "投信-賣出股數", "投信-買賣超股數", "自營商(自行買賣)-買進股數",
        "自營商(自行買賣)-賣出股數", "自營商(自行買賣)-買賣超股數", "自營商(避險)-買進股數",
        "自營商(避險)-賣出股數", "自營商(避險)-買賣超股數", "自營商-買進股數", "自營商-賣出股數",
        "自營商-買賣超股數", "三大法人買賣超股數合計",
    ]
    values = [code, name, "0", "0", "0", "0", "0", "0", "0", "0", "0", buy, sell, net,
              "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"]
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([report_date + " 三大法人日交易資訊"])
    writer.writerow(header)
    writer.writerow(values)
    writer.writerow(["共1筆"])
    return output.getvalue().encode("cp950")


def test_tpex_csv_preserves_exact_shares_and_explicit_zero_rows():
    from pipeline.official_institutional import parse_tpex_csv
    raw = _tpex_csv("3081", "聯亞", "98,000", "59", "97,941")
    result = parse_tpex_csv(raw, expected_date=date(2026, 10, 2))
    assert result == [{
        "code": "3081", "name": "聯亞", "market": "TPEx",
        "buyShares": 98000, "sellShares": 59, "netShares": 97941,
    }]

    zero = _tpex_csv("3131", "弘塑", "0", "0", "0")
    assert parse_tpex_csv(zero, expected_date=date(2026, 10, 2))[0]["netShares"] == 0
    assert parse_tpex_csv(
        _tpex_csv("3131", "弘塑", "36", "0", "36"), expected_date=date(2026, 10, 2)
    )[0]["buyShares"] == 36
    assert parse_tpex_csv(
        _tpex_csv("3163", "波若威", "0", "158,675", "-158,675"), expected_date=date(2026, 10, 2)
    )[0]["netShares"] == -158675


def test_tpex_official_no_data_sentinel_is_empty_only_for_the_requested_date():
    from pipeline.official_institutional import parse_tpex_daily_response
    fields = list(csv.reader(io.StringIO(_tpex_csv("3081", "聯亞", "0", "0", "0").decode("cp950"))))[1]
    payload = json.dumps({
        "date": "20261003", "stat": "無資料可供下載", "tables": [{
            "date": "115/10/03", "data": [], "totalCount": 0, "fields": fields,
        }],
    }, ensure_ascii=False).encode("utf-8")
    assert parse_tpex_daily_response(payload, expected_date=date(2026, 10, 3)) == []
    with pytest.raises(OfficialInstitutionalError, match="date"):
        parse_tpex_daily_response(payload, expected_date=date(2026, 10, 2))


def test_tpex_holiday_no_data_response_allows_official_presentation_metadata():
    from pipeline.official_institutional import parse_tpex_daily_response
    fields = list(csv.reader(io.StringIO(_tpex_csv("3081", "聯亞", "0", "0", "0").decode("cp950"))))[1]
    payload = json.dumps({
        "columnNum": 25, "csvName": "sitcStat", "date": "20260928",
        "stat": "無資料可供下載", "template": "daily",
        "tables": [{
            "columnNum": 25, "date": "115/09/28", "data": [], "fields": fields,
            "notes": ["official presentation note"], "subtitle": "", "summary": ["共0筆"], "title": "",
            "totalCount": 0,
        }],
    }, ensure_ascii=False).encode("utf-8")
    assert parse_tpex_daily_response(payload, expected_date=date(2026, 9, 28)) == []


@pytest.mark.parametrize("change", [
    {"date": "20260929"},
    {"stat": "成功"},
    {"table_data": [["3081"]]},
    {"total_count": 1},
    {"field_count": 23},
])
def test_tpex_holiday_no_data_response_rejects_non_sentinel_payloads(change):
    from pipeline.official_institutional import parse_tpex_daily_response
    fields = list(csv.reader(io.StringIO(_tpex_csv("3081", "聯亞", "0", "0", "0").decode("cp950"))))[1]
    table = {"date": "115/09/28", "data": [], "fields": fields, "totalCount": 0,
             "columnNum": 25, "notes": [], "subtitle": "", "summary": [], "title": ""}
    payload = {"date": "20260928", "stat": "無資料可供下載", "tables": [table],
               "columnNum": 25, "csvName": "sitcStat", "template": "daily"}
    if "date" in change: payload["date"] = change["date"]
    if "stat" in change: payload["stat"] = change["stat"]
    if "table_data" in change: payload["tables"][0]["data"] = change["table_data"]
    if "total_count" in change: payload["tables"][0]["totalCount"] = change["total_count"]
    if "field_count" in change: payload["tables"][0]["fields"] = fields[:change["field_count"]]
    with pytest.raises(OfficialInstitutionalError):
        parse_tpex_daily_response(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                  expected_date=date(2026, 9, 28))


def test_recent_complete_days_uses_authoritative_calendar_before_request(monkeypatch):
    import pipeline.official_institutional as official
    from pipeline.trading_calendar import SOURCE_URL
    calendar = {"schemaVersion": "trading-calendar-v1", "timezone": "Asia/Taipei", "year": 2026,
                "sourceUrl": SOURCE_URL, "closedDates": ["2026-09-28"], "openExceptions": []}
    calls = []
    def fetch(day, **kwargs):
        calls.append(day)
        return [{"code": "2330"}]
    monkeypatch.setattr(official, "fetch_complete_day", fetch)
    result = official.fetch_recent_complete_days(as_of=date(2026, 9, 29), sessions=2,
        lookback_days=5, calendar=calendar)
    assert [item["date"] for item in result] == ["2026-09-29", "2026-09-25"]
    assert calls == [date(2026, 9, 29), date(2026, 9, 25)]


def test_recent_complete_days_calendar_requires_valid_coverage_before_http(monkeypatch):
    import pipeline.official_institutional as official
    calendar = {"schemaVersion": "trading-calendar-v1", "timezone": "Asia/Taipei", "year": 2026,
                "sourceUrl": "https://example.invalid", "closedDates": [], "openExceptions": []}
    monkeypatch.setattr(official, "fetch_complete_day", lambda *args, **kwargs:
                        pytest.fail("invalid calendar must fail before source request"))
    with pytest.raises(ValueError, match="calendar"):
        official.fetch_recent_complete_days(as_of=date(2026, 1, 2), sessions=1, lookback_days=1,
                                            calendar=calendar)


def test_recent_complete_days_requires_official_source_url_before_http(monkeypatch):
    import pipeline.official_institutional as official
    calendar = {"schemaVersion": "trading-calendar-v1", "timezone": "Asia/Taipei", "year": 2026,
                "closedDates": [], "openExceptions": []}
    monkeypatch.setattr(official, "fetch_complete_day", lambda *args, **kwargs:
                        pytest.fail("calendar without source provenance must fail before request"))
    with pytest.raises(ValueError, match="calendar"):
        official.fetch_recent_complete_days(as_of=date(2026, 10, 2), sessions=1, lookback_days=1,
                                            calendar=calendar)


def test_recent_complete_days_does_not_treat_missing_open_session_as_closed(monkeypatch):
    import pipeline.official_institutional as official
    from pipeline.trading_calendar import SOURCE_URL
    calendar = {"schemaVersion": "trading-calendar-v1", "timezone": "Asia/Taipei", "year": 2026,
                "sourceUrl": SOURCE_URL, "closedDates": [], "openExceptions": []}
    calls = []
    monkeypatch.setattr(official, "fetch_complete_day", lambda day: calls.append(day) or [])
    with pytest.raises(OfficialInstitutionalError, match="open session 2026-10-02"):
        official.fetch_recent_complete_days(as_of=date(2026, 10, 2), sessions=1, lookback_days=1,
                                            calendar=calendar)
    assert calls == [date(2026, 10, 2)]


def test_recent_complete_days_requires_explicit_calendar_coverage_across_year_boundary(monkeypatch):
    import pipeline.official_institutional as official
    from pipeline.trading_calendar import SOURCE_URL
    calendar = {"schemaVersion": "trading-calendar-v1", "timezone": "Asia/Taipei", "year": 2027,
                "sourceUrl": SOURCE_URL, "closedDates": [], "openExceptions": []}
    calls = []
    monkeypatch.setattr(official, "fetch_complete_day", lambda day: calls.append(day) or [{"code": "2330"}])
    with pytest.raises(ValueError, match="does not cover requested year"):
        official.fetch_recent_complete_days(as_of=date(2027, 1, 4), sessions=3, lookback_days=5,
                                            calendar=calendar)
    assert calls == [date(2027, 1, 4), date(2027, 1, 1)]


def test_recent_complete_days_uses_two_year_calendar_and_skips_official_closure(monkeypatch):
    import pipeline.official_institutional as official
    from pipeline.trading_calendar import compose_calendar_set
    source = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
    prior = {"schemaVersion":"trading-calendar-v1","timezone":"Asia/Taipei","year":2026,
             "closedDates":["2026-12-25"],"openExceptions":[],"sourceUrl":source}
    current = {"schemaVersion":"trading-calendar-v1","timezone":"Asia/Taipei","year":2027,
               "closedDates":["2027-01-01"],"openExceptions":[],"sourceUrl":source}
    calendar = compose_calendar_set([current, prior])
    calls = []
    monkeypatch.setattr(official, "fetch_complete_day", lambda day: calls.append(day) or [{"code":"2330"}])
    result = official.fetch_recent_complete_days(as_of=date(2027, 1, 4), sessions=2,
        lookback_days=10, calendar=calendar)
    assert [row["date"] for row in result] == ["2027-01-04", "2026-12-31"]
    assert calls == [date(2027, 1, 4), date(2026, 12, 31)]
    calendar["sourceUrl"] = "https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule"
    calendar["year"] = 2025
    with pytest.raises(ValueError, match="calendar"):
        official.fetch_recent_complete_days(as_of=date(2026, 1, 2), sessions=1, lookback_days=1,
                                            calendar=calendar)


def test_tpex_csv_rejects_duplicate_codes_and_malformed_common_rows():
    from pipeline.official_institutional import parse_tpex_csv
    raw = _tpex_csv("3081", "聯亞", "10", "2", "8")
    lines = raw.decode("cp950").splitlines()
    duplicate = "\r\n".join([*lines[:3], lines[2], "共2筆", ""])
    with pytest.raises(OfficialInstitutionalError, match="duplicate"):
        parse_tpex_csv(duplicate.encode("cp950"), expected_date=date(2026, 10, 2))
    malformed = _tpex_csv("3081", "聯亞", "10", "2", "9")
    with pytest.raises(OfficialInstitutionalError, match="inconsistent"):
        parse_tpex_csv(malformed, expected_date=date(2026, 10, 2))


def test_tpex_csv_requires_a_matching_terminal_row_count():
    from pipeline.official_institutional import parse_tpex_csv
    raw = _tpex_csv("3081", "聯亞", "10", "2", "8").decode("cp950")
    with pytest.raises(OfficialInstitutionalError, match="row-count"):
        parse_tpex_csv(raw.replace("共1筆", "共2筆").encode("cp950"), expected_date=date(2026, 10, 2))
    with pytest.raises(OfficialInstitutionalError, match="row-count footer"):
        parse_tpex_csv(raw.replace("共1筆\r\n", "").encode("cp950"), expected_date=date(2026, 10, 2))


def test_parse_twse_report_keeps_share_units():
    payload = {
        "stat": "OK",
        "date": "20260918",
        "fields": ["", "證券代號", "證券名稱", "買進股數", "賣出股數", "買賣超股數"],
        "data": [[" ", "2303  ", "聯電 ", "19,720,456", "6,090,268", "13,630,188"]],
    }

    assert parse_twse_payload(payload) == [
        {
            "code": "2303",
            "name": "聯電",
            "market": "TWSE",
            "buyShares": 19720456,
            "sellShares": 6090268,
            "netShares": 13630188,
        }
    ]


def test_parse_tpex_report_converts_lots_to_shares():
    payload = {
        "date": "20260918",
        "tables": [{
            "fields": ["排行", "代號", "名稱", "買進", "賣出", "買賣超(張數)"],
            "data": [["1", "6147", "頎邦", "2,565", "0", "2,565"]],
        }],
    }

    assert parse_tpex_payload(payload) == [
        {
            "code": "6147",
            "name": "頎邦",
            "market": "TPEx",
            "buyShares": 2565000,
            "sellShares": 0,
            "netShares": 2565000,
        }
    ]


def test_parse_tpex_numeric_zero_values_are_not_treated_as_missing():
    payload = {"tables": [{
        "fields": ["代號", "名稱", "買進", "賣出", "買賣超"],
        "data": [["3081", "聯亞", 0, 0, 0]],
    }]}

    assert parse_tpex_payload(payload)[0]["netShares"] == 0


@pytest.mark.parametrize(
    ("buy", "sell", "net", "expected"),
    [
        ("0.036", "0", "0.036", (36, 0, 36)),
        ("98", "0.059", "97.941", (98000, 59, 97941)),
        ("0", "158.675", "(158.675)", (0, 158675, -158675)),
        ("1,234.5", "1,234.464", "0.036", (1234500, 1234464, 36)),
    ],
)
def test_parse_tpex_fractional_lots_exactly_to_whole_shares(buy, sell, net, expected):
    payload = {"tables": [{
        "fields": ["代號", "名稱", "買進", "賣出", "買賣超"],
        "data": [["3081", "聯亞", buy, sell, net]],
    }]}

    row = parse_tpex_payload(payload)[0]

    assert (row["buyShares"], row["sellShares"], row["netShares"]) == expected


@pytest.mark.parametrize(
    ("buy", "sell", "net"),
    [
        ("0.0001", "0", "0.0001"),  # One tenth of a share.
        ("-1", "0", "-1"),
        ("10", "1", "8"),  # Buy/sell/net mismatch.
        ("NaN", "0", "NaN"),
        (True, 0, 1),
    ],
)
def test_tpex_invalid_common_stock_rows_fail_instead_of_disappearing(buy, sell, net):
    payload = {"tables": [{
        "fields": ["代號", "名稱", "買進", "賣出", "買賣超"],
        "data": [["3081", "聯亞", buy, sell, net]],
    }]}

    with pytest.raises(OfficialInstitutionalError):
        parse_tpex_payload(payload)


def test_tpex_decimal_precision_never_rounds_fractional_shares_or_large_values():
    fields = ["代號", "名稱", "買進", "賣出", "買賣超"]
    fractional = {"tables": [{"fields": fields, "data": [[
        "3081", "聯亞", "1.000000000000000000000000000001", "0",
        "1.000000000000000000000000000001",
    ]]}]}
    with pytest.raises(OfficialInstitutionalError):
        parse_tpex_payload(fractional)

    lots = "12345678901234567890123456789"
    large = {"tables": [{"fields": fields, "data": [["3081", "聯亞", lots, "0", lots]]}]}
    assert parse_tpex_payload(large)[0]["buyShares"] == int(lots) * 1000


@pytest.mark.parametrize("value", ["(-1)", "1" * 65])
def test_tpex_rejects_signed_accounting_negative_and_oversized_numeric_text(value):
    payload = {"tables": [{
        "fields": ["代號", "名稱", "買進", "賣出", "買賣超"],
        "data": [["3081", "聯亞", "1", "0", value]],
    }]}

    with pytest.raises(OfficialInstitutionalError):
        parse_tpex_payload(payload)


def test_tpex_missing_common_stock_quantity_and_unidentified_row_fail_closed():
    fields = ["代號", "名稱", "買進", "賣出", "買賣超"]
    for row in (["3081", "聯亞", None, 0, 0], ["", "未知", 1, 0, 1], ["", "", 0, 0, 0]):
        with pytest.raises(OfficialInstitutionalError):
            parse_tpex_payload({"tables": [{"fields": fields, "data": [row]}]})


def test_tpex_valid_noncommon_rows_keep_parser_output_and_invalid_ones_are_ignored():
    fields = ["代號", "名稱", "買進", "賣出", "買賣超"]
    payload = {"tables": [{"fields": fields, "data": [
        ["0050", "元大台灣50", "10", "2", "8"],
        ["0051", "元大中型100", "bad", "0", "bad"],
    ]}]}

    assert parse_tpex_payload(payload) == [{
        "code": "0050", "name": "元大台灣50", "market": "TPEx",
        "buyShares": 10000, "sellShares": 2000, "netShares": 8000,
    }]


@pytest.mark.parametrize("value", ["1.5", "NaN", "Infinity", True])
def test_twse_share_values_must_be_finite_whole_shares(value):
    payload = {
        "fields": ["證券代號", "證券名稱", "買進股數", "賣出股數", "買賣超股數"],
        "data": [["2303", "聯電", value, 0, value]],
    }

    with pytest.raises(OfficialInstitutionalError):
        parse_twse_payload(payload)


def test_twse_rows_validate_nonnegative_buys_and_net_identity():
    payload = {
        "fields": ["證券代號", "證券名稱", "買進股數", "賣出股數", "買賣超股數"],
        "data": [["2303", "聯電", 1, 0, 0]],
    }

    with pytest.raises(OfficialInstitutionalError):
        parse_twse_payload(payload)


def test_aggregate_window_sums_both_markets_in_shares():
    days = [
        [
            {"code": "2303", "name": "聯電", "market": "TWSE", "netShares": 1000},
            {"code": "6147", "name": "頎邦", "market": "TPEx", "netShares": 2},
        ],
        [
            {"code": "2303", "name": "聯電", "market": "TWSE", "netShares": 3000},
            {"code": "6147", "name": "頎邦", "market": "TPEx", "netShares": 4},
        ],
    ]

    assert aggregate_window(days) == [
        {"rank": 1, "code": "2303", "name": "聯電", "market": "TWSE", "netShares": 4000},
        {"rank": 2, "code": "6147", "name": "頎邦", "market": "TPEx", "netShares": 6},
    ]


def test_aggregate_window_excludes_etf_and_warrant_codes():
    days = [[
        {"code": "0050", "name": "元大台灣50", "market": "TWSE", "netShares": 99999999},
        {"code": "00980A", "name": "主動野村臺灣優選", "market": "TWSE", "netShares": 88888888},
        {"code": "2330", "name": "台積電", "market": "TWSE", "netShares": 100},
    ]]

    assert [row["code"] for row in aggregate_window(days)] == ["2330"]
