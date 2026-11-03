import pytest

from pipeline.financial_discovery import discover, extract_explicit_eps, merge_eps, plan_missing_peg, safe_public_url
import pipeline.financial_discovery as financial_discovery


def test_discovery_pins_exact_issuer_domain_and_rejects_unrelated_hosts():
    stock = {"code": "2330", "officialDomains": ["tsmc.com"], "results": [
        {"url": "https://investor.tsmc.com/english/quarterly-results", "title": "Quarterly financial report"},
        {"url": "https://tsmc.com.attacker.example/report.pdf", "title": "Annual financial report"},
        {"url": "http://investor.tsmc.com/report.pdf", "title": "Quarterly financial report"},
    ]}
    result = discover(stock)
    assert [x["url"] for x in result["candidates"]] == ["https://investor.tsmc.com/english/quarterly-results"]


def test_safe_url_rejects_private_ip_and_accepts_approved_domain():
    assert not safe_public_url("https://127.0.0.1/report.pdf")
    assert not safe_public_url("https://example.com/report.pdf", ["tsmc.com"])
    assert safe_public_url("https://tsmc.com/report.pdf", ["tsmc.com"])


def test_extract_only_explicit_basic_eps_value_and_retain_evidence():
    html = """<div>股票代號：2330</div><table><tr><th colspan='2'>2025年第2季 合併財務報告 TWD</th></tr>
      <tr><td>基本每股盈餘</td><td>3.25</td></tr><tr><td>稀釋每股盈餘</td><td>3.10</td></tr></table>"""
    rows = extract_explicit_eps(html, source_url="https://issuer.example/q2.html", sha256="abc", published_date="2025-08-10", code="2330", legal_name="Example Inc")
    assert len(rows) == 2
    assert rows[0]["period"] == "2025-Q2"
    assert rows[0]["eps"] == 3.25
    assert rows[0]["epsKind"] == "basic"
    assert rows[0]["currency"] == "TWD"
    assert rows[0]["quotedRow"] == "基本每股盈餘 | 3.25"
    assert rows[0]["sha256"] == "abc"
    assert rows[0]["publishedDate"] == "2025-08-10"


def test_cumulative_rows_and_nonfinite_or_ambiguous_rows_are_not_guessed():
    html = """<div>2330</div><table><tr><th>2025年上半年 累計</th></tr><tr><td>基本每股盈餘</td><td>6.0</td></tr></table>
      <table><tr><th>2025年第1季</th></tr><tr><td>基本每股盈餘</td><td>1.2</td><td>1.3</td></tr></table>
      <table><tr><th>2025年第1季</th></tr><tr><td>每股盈餘</td><td>NaN</td></tr></table>"""
    assert extract_explicit_eps(html, source_url="https://issuer.example/a", sha256="a", code="2330") == []


def test_identity_requires_exact_code_or_full_legal_name():
    html = """<div>Company 12330 / first holding bank</div><table><tr><th>2025年第1季</th></tr>
      <tr><td>基本每股盈餘</td><td>1.2</td></tr></table>"""
    assert extract_explicit_eps(html, source_url="https://issuer.example/a", sha256="a", code="2330", legal_name="第一金融控股股份有限公司") == []
    html += "<div>第一金融控股股份有限公司</div>"
    assert len(extract_explicit_eps(html, source_url="https://issuer.example/a", sha256="a", code="2330", legal_name="第一金融控股股份有限公司")) == 1


def test_currency_requires_unambiguous_label_in_eps_table_and_identity_code_context():
    prefix = "<div>股票代號 2330</div>"
    table = "<table><tr><th>2025年第1季</th></tr><tr><td>基本每股盈餘</td><td>1.2</td></tr></table>"
    kwargs = {"source_url": "https://issuer.example/a", "sha256": "a", "code": "2330"}
    assert extract_explicit_eps(prefix + table, **kwargs)[0]["currency"] == "unknown"
    assert extract_explicit_eps(prefix + table.replace("2025年第1季", "2025年第1季 TWD USD"), **kwargs)[0]["currency"] == "unknown"
    assert extract_explicit_eps(prefix + table.replace("2025年第1季", "2025年第1季 新台幣"), **kwargs)[0]["currency"] == "TWD"
    bare_code = "<div>Report 2330</div>" + table.replace("2025年第1季", "2025年第1季 新台幣")
    assert extract_explicit_eps(bare_code, **kwargs) == []


def test_planner_uses_health_inputs_and_includes_latest_missing_declared_quarter():
    detail = {"healthInputs": {"incomeQuarterly": [
        {"year": 2026, "quarter": 2, "periodType": "quarter", "eps": 1.1},
        {"year": 2026, "quarter": 3, "periodType": "quarter", "eps": None},
    ]}}
    result = plan_missing_peg(detail)
    assert result["requests"][0]["period"] == "2026-Q4"
    assert result["requests"][1]["period"] == "2026-Q3"
    assert result["requests"][1]["declaredInDetail"] is True


def test_merge_only_fills_missing_quarter_and_preserves_verified_value():
    detail = {"healthInputs": {"incomeQuarterly": [
        {"year": 2025, "quarter": 1, "periodType": "quarter", "eps": 1.1, "source": "verified", "revenue": 50},
        {"year": 2025, "quarter": 2, "periodType": "quarter", "eps": None, "revenue": 75, "amountUnit": "TWD"},
    ]}}
    recs = [
        {"period": "2025-Q1", "eps": 9.9},
        {"period": "2025-Q2", "eps": 2.2, "currency": "TWD", "scope": "consolidated", "epsKind": "basic", "sourceUrl": "https://issuer.example/q2", "quotedRow": "basic EPS | 2.2", "sha256": "b"},
    ]
    result = merge_eps(detail, recs)
    rows = result["healthInputs"]["incomeQuarterly"]
    assert rows[0]["eps"] == 1.1
    assert rows[1]["eps"] == 2.2
    assert rows[1]["revenue"] == 75


def test_merge_rejects_unknown_metadata_conflicts_and_duplicate_periods():
    detail = {"healthInputs": {"incomeQuarterly": []}}
    records = [
        {"period": "2025-Q1", "eps": 1.0, "currency": "unknown", "scope": "consolidated", "epsKind": "basic"},
        {"period": "2025-Q2", "eps": 1.0, "currency": "TWD", "scope": "consolidated", "epsKind": "basic"},
        {"period": "2025-Q2", "eps": 2.0, "currency": "TWD", "scope": "consolidated", "epsKind": "basic"},
    ]
    result = merge_eps(detail, records)
    assert result["healthInputs"]["incomeQuarterly"] == []


def test_fetch_uses_validated_ip_for_connection_and_keeps_hostname_tls_verification(monkeypatch):
    calls = []
    dns_calls = []

    def getaddrinfo(host, port, *, type):
        dns_calls.append((host, port))
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    class Response:
        status = 200
        headers = {}

        def stream(self, amount, decode_content):
            assert amount == 65536 and decode_content is True
            yield b"report"

        def close(self):
            pass

    class Pool:
        def __init__(self, host, **kwargs):
            calls.append((host, kwargs))

        def request(self, method, path, **kwargs):
            calls.append((method, path, kwargs))
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(financial_discovery.socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(financial_discovery, "HTTPSConnectionPool", Pool)
    body, _ = financial_discovery.fetch_document("https://reports.tsmc.com/annual.pdf?year=2025", ["tsmc.com"])
    assert body == b"report"
    assert dns_calls == [("reports.tsmc.com", 443)]
    pool_host, tls = calls[0]
    assert pool_host == "93.184.216.34"
    assert tls["server_hostname"] == tls["assert_hostname"] == "reports.tsmc.com"
    assert tls["cert_reqs"] == "CERT_REQUIRED"
    _, path, request = calls[1]
    assert path == "/annual.pdf?year=2025"
    assert request["headers"]["Host"] == "reports.tsmc.com"
    assert request["assert_same_host"] is False and request["redirect"] is False


def test_fetch_rejects_private_dns_and_private_redirect(monkeypatch):
    monkeypatch.setattr(financial_discovery.socket, "getaddrinfo", lambda *a, **k: [
        (2, 1, 6, "", ("127.0.0.1", 443)),
    ])
    monkeypatch.setattr(financial_discovery, "HTTPSConnectionPool", lambda *a, **k: pytest.fail("private host connected"))
    with pytest.raises(ValueError, match="unsafe_or_unapproved_url"):
        financial_discovery.fetch_document("https://reports.tsmc.com/report.pdf", ["tsmc.com"])

    dns_calls = []

    def public_then_private(host, port, *, type):
        dns_calls.append(host)
        ip = "93.184.216.34" if host == "reports.tsmc.com" else "10.0.0.1"
        return [(2, 1, 6, "", (ip, port))]

    class Redirect:
        status = 302
        headers = {"Location": "https://cdn.tsmc.com/report.pdf"}

        def close(self):
            pass

    class Pool:
        def __init__(self, *a, **k): pass
        def request(self, *a, **k): return Redirect()
        def close(self): pass

    monkeypatch.setattr(financial_discovery.socket, "getaddrinfo", public_then_private)
    monkeypatch.setattr(financial_discovery, "HTTPSConnectionPool", Pool)
    with pytest.raises(ValueError, match="unsafe_redirect"):
        financial_discovery.fetch_document("https://reports.tsmc.com/report.pdf", ["tsmc.com"])
    assert dns_calls == ["reports.tsmc.com", "cdn.tsmc.com"]


def test_fetch_caps_redirect_hops_and_decompressed_size(monkeypatch):
    monkeypatch.setattr(financial_discovery.socket, "getaddrinfo", lambda host, port, **k: [
        (2, 1, 6, "", ("93.184.216.34", port)),
    ])

    class Redirect:
        status = 302
        headers = {"Location": "/again"}
        def close(self): pass

    class Pool:
        count = 0
        def __init__(self, *a, **k): pass
        def request(self, *a, **k):
            Pool.count += 1
            return Redirect()
        def close(self): pass

    monkeypatch.setattr(financial_discovery, "HTTPSConnectionPool", Pool)
    with pytest.raises(ValueError, match="redirect_limit_exceeded"):
        financial_discovery.fetch_document("https://reports.tsmc.com/report.pdf", ["tsmc.com"])
    assert Pool.count == 3

    class Large:
        status = 200
        headers = {}
        def stream(self, amount, decode_content):
            yield b"x" * (financial_discovery.MAX_DOCUMENT + 1)
        def close(self): pass

    class LargePool:
        def __init__(self, *a, **k): pass
        def request(self, *a, **k): return Large()
        def close(self): pass

    monkeypatch.setattr(financial_discovery, "HTTPSConnectionPool", LargePool)
    with pytest.raises(ValueError, match="document_too_large"):
        financial_discovery.fetch_document("https://reports.tsmc.com/report.pdf", ["tsmc.com"])
