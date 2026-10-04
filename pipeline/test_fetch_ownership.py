import json

from scripts.fetch_ownership import (
    OWNERSHIP_SNAPSHOT_VERSION,
    build_snapshot,
    parse_mops_payload,
    parse_tdcc_csv,
    parse_tdcc_history_html,
)


def test_parse_tdcc_history_table_maps_actual_headers_and_injects_code_date():
    html = "<table><tr><th>序</th><th>持股/單位數分級</th><th>人數</th><th>股數/單位數</th><th>占集保庫存數比例 (%)</th></tr><tr><td>15</td><td>1,000,001以上</td><td>1,000</td><td>10,000</td><td>4.1</td></tr><tr><td>17</td><td>合 計</td><td>12,500</td><td>20,000</td><td>100.00</td></tr></table>"
    rows = parse_tdcc_history_html(html, code="2330", as_of="2026-08-28")
    assert rows[0]["證券代號"] == "2330"
    assert rows[0]["資料日期"] == "2026-08-28"
    assert rows[0]["持股分級"] == "15"
    assert parse_tdcc_csv("資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n2026-08-28,2330,15,1,10,4.1\n2026-08-28,2330,17,12500,0,0\n")[0]["largeHolderPct"] == 4.1

def test_parse_tdcc_csv_uses_class_15_and_ignores_adjustment_class_16():
    csv = "資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n2026-08-28,2330,15,1,11,4.1\n2026-08-28,2330,16,2,21,99.9\n2026-08-28,2330,17,12500,0,0\n"
    rows = parse_tdcc_csv(csv)
    assert rows[0]["largeHolderPct"] == 4.1
    assert rows[0]["shareholderCount"] == 12500
    assert rows[0]["asOf"] == "2026-08-28"


def test_parse_tdcc_history_maps_class_16_total_to_official_class_17():
    html = "<table><tr><th>序</th><th>持股/單位數分級</th><th>人數</th><th>股數/單位數</th><th>占集保庫存數比例 (%)</th></tr><tr><td>15</td><td>1,000,001以上</td><td>405</td><td>3,941,992,568</td><td>52.39</td></tr><tr><td>16</td><td>合 計</td><td>508,051</td><td>7,523,181,742</td><td>100.00</td></tr></table>"
    rows = parse_tdcc_history_html(html, code="1101", as_of="2026-08-28")
    assert rows[-1]["持股分級"] == "17"
    normalized = parse_tdcc_csv("資料日期,證券代號,持股分級,人數,股數,占集保庫存數比例%\n2026-08-28,1101,15,405,3941992568,52.39\n2026-08-28,1101,17,508051,7523181742,100.00\n")
    assert normalized[0]["shareholderCount"] == 508051


def test_parse_mops_payload_keeps_only_approved_titles_and_refuses_aggregate_as_denominator():
    payload = {"parentCompany": {"data": [
        ["董事長本人", "甲", "120", "100", "x"],
        ["董事本人", "乙", "60", "50", "x"],
        ["法人代表人", "丙", "999", "999", "x"],
    ], "total": {"allDirectorSupervisor": "1000"}}}
    rows = parse_mops_payload(payload, code="2330", period="2026-08")
    assert rows[0]["directorSupervisorPct"] is None
    assert rows[0]["directorDenominator"] is None
    assert rows[0]["directorScope"] == ["董事長本人", "董事本人"]


def test_snapshot_marks_source_failure_stale_and_never_fakes_zeroes():
    old = {"schemaVersion": OWNERSHIP_SNAPSHOT_VERSION, "rows": [{"code": "2330", "period": "2026-08", "largeHolderPct": 4.1}]}
    snapshot = build_snapshot(old, [], requested_codes=["2330"], retrieved_at="2026-09-01T00:00:00+08:00")
    assert snapshot["status"] == "stale"
    assert snapshot["rows"][0]["largeHolderPct"] == old["rows"][0]["largeHolderPct"]
    assert snapshot["rows"][0]["shareholderCount"] if "shareholderCount" in snapshot["rows"][0] else True
    assert snapshot["rows"][0].get("largeHolderPct") == 4.1
    assert snapshot["rows"][0].get("shareholderCount") != 0


def test_ownership_bulk_checkpoint_precedes_history_and_retains_prior_on_limit(tmp_path, monkeypatch):
    import scripts.fetch_ownership as ownership
    previous = {'schemaVersion': OWNERSHIP_SNAPSHOT_VERSION, 'rows': [{'code': '2330', 'period': '2026-08', 'asOf': '2026-08-28', 'largeHolderPct': 4, 'shareholderCount': 100}]}
    output = tmp_path / 'ownership.json'; output.write_text(json.dumps(previous))
    monkeypatch.setattr(ownership, 'fetch_tdcc', lambda **kwargs: [{'code': '2330', 'period': '2026-09', 'asOf': '2026-09-30', 'largeHolderPct': 5, 'shareholderCount': 90}])
    monkeypatch.setattr(ownership, 'fetch_twse_director_rows', lambda *args, **kwargs: [{'code': '2330', 'period': '2026-09', 'directorSupervisorPct': 7}])
    seen = []
    def historical(*args, **kwargs):
        checkpoint = json.loads(output.read_bytes())
        seen.append(checkpoint)
        assert any(row.get('directorSupervisorPct') == 7 for row in checkpoint['rows'])
        assert any(row['period'] == '2026-08' for row in checkpoint['rows'])
        raise ownership.OwnershipLimit('history_request_limit')
    monkeypatch.setattr(ownership, 'fetch_tdcc_historical', historical)
    snapshot = ownership.acquire_snapshot(output, ['2330'], as_of='2026-10-02', max_runtime_seconds=180, max_requests=40, max_history_requests=20)
    assert len(seen) == 1 and snapshot['status'] == 'stale'
    assert snapshot['acquisition']['errors'] == [{'source': 'TDCC:history:2330', 'category': 'history_request_limit'}]
    assert len(snapshot['rows']) == 2
    assert not any(row['period'] == '2026-10' for row in snapshot['rows'])


def test_ownership_global_deadline_bounds_transport_timeout_and_stops_without_retry(monkeypatch):
    import scripts.fetch_ownership as ownership
    clock = [0.0]
    monkeypatch.setattr(ownership.time, 'monotonic', lambda: clock[0])
    budget = ownership.OwnershipBudget(max_runtime_seconds=5, max_requests=40, max_history_requests=20)
    calls = []
    def unavailable(request, timeout):
        calls.append(timeout); clock[0] += timeout
        raise TimeoutError('private transport detail')
    monkeypatch.setattr(ownership, 'urlopen', unavailable)
    import pytest
    with pytest.raises(ownership.OwnershipLimit, match='runtime_limit'):
        ownership._request(ownership.TDCC_URL, budget=budget)
    assert calls == [5] and budget.requests == 1


def test_history_get_and_post_share_hard_request_cap(monkeypatch):
    import scripts.fetch_ownership as ownership
    import urllib.request
    import io
    import pytest
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request.get_method(), timeout))
            return io.BytesIO(b'<select name="scaDate"><option value="20260828">date</option><option value="20260924">date</option><option value="20261002">date</option></select><input name="SYNCHRONIZER_TOKEN" value="public-test"><span>\xe8\xb3\x87\xe6\x96\x99\xe6\x97\xa5\xe6\x9c\x9f\xef\xbc\x9a115\xe5\xb9\xb408\xe6\x9c\x8828\xe6\x97\xa5</span>')
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Opener())
    budget = ownership.OwnershipBudget(max_runtime_seconds=180, max_requests=3, max_history_requests=3)
    with pytest.raises(ownership.OwnershipLimit, match='request_limit'):
        ownership.fetch_tdcc_historical('2330', ['2026-08', '2026-09', '2026-10'], as_of='2026-10-02', budget=budget)
    assert [call[0] for call in calls] == ['GET', 'POST', 'GET']
    assert budget.requests == 3 and budget.history_requests == 3


def test_asof_invalid_fails_before_fetch_or_cache_write(tmp_path, monkeypatch):
    import scripts.fetch_ownership as ownership
    import pytest
    calls = []
    monkeypatch.setattr(ownership, 'fetch_tdcc', lambda **kwargs: calls.append(kwargs) or [])
    with pytest.raises(ValueError):
        ownership.acquire_snapshot(tmp_path / 'ownership.json', ['2330'], as_of='2026-10-99')
    assert calls == [] and not list(tmp_path.iterdir())


def test_tdcc_history_never_requests_after_exact_asof(monkeypatch):
    import scripts.fetch_ownership as ownership
    import urllib.request
    import io
    from urllib.parse import parse_qs
    dates = []
    class Opener:
        def open(self, request, timeout):
            if request.data:
                dates.append(parse_qs(request.data.decode())['firDate'][0])
                return io.BytesIO('<span>資料日期：115年10月02日</span>'.encode())
            return io.BytesIO(b'<select name="scaDate"><option value="20260828">date</option><option value="20260924">date</option><option value="20261002">date</option></select><input name="SYNCHRONIZER_TOKEN" value="public-test"><span>\xe8\xb3\x87\xe6\x96\x99\xe6\x97\xa5\xe6\x9c\x9f\xef\xbc\x9a115\xe5\xb9\xb408\xe6\x9c\x8828\xe6\x97\xa5</span>')
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Opener())
    assert ownership.fetch_tdcc_historical('2330', ['2026-10'], as_of='2026-10-02') == []
    assert dates == ['20261002']


def test_bulk_source_errors_are_sanitized_and_stale_cache_retained(tmp_path, monkeypatch):
    import scripts.fetch_ownership as ownership
    output = tmp_path / 'ownership.json'
    output.write_text(json.dumps({'schemaVersion': OWNERSHIP_SNAPSHOT_VERSION, 'rows': [{'code': '2330', 'period': '2026-09', 'asOf': '2026-09-25', 'largeHolderPct': 4}]}))
    def error(*args, **kwargs): raise TimeoutError('dummy private cookie header')
    monkeypatch.setattr(ownership, 'fetch_tdcc', error)
    monkeypatch.setattr(ownership, 'fetch_twse_director_rows', error)
    monkeypatch.setattr(ownership, 'fetch_tdcc_historical', error)
    result = ownership.acquire_snapshot(output, ['2330'], as_of='2026-10-02', max_history_requests=0)
    assert result['status'] == 'stale' and result['rows'][0]['largeHolderPct'] == 4
    assert result['acquisition']['errors']
    assert 'dummy' not in output.read_text() and 'cookie' not in output.read_text()


def test_fresh_valid_same_month_ownership_replaces_old_values_including_real_zero():
    previous = {'rows': [{'code': '2330', 'period': '2026-09', 'asOf': '2026-09-12', 'largeHolderPct': 5, 'shareholderCount': 100}]}
    fresh = [{'code': '2330', 'period': '2026-09', 'asOf': '2026-09-30', 'largeHolderPct': 0, 'shareholderCount': 90}]
    result = build_snapshot(previous, fresh, requested_codes=['2330'])
    assert result['rows'][0]['largeHolderPct'] == 0
    assert result['rows'][0]['shareholderCount'] == 90 and result['rows'][0]['asOf'] == '2026-09-30'


def test_partial_director_bulk_survives_later_endpoint_failure(monkeypatch):
    import scripts.fetch_ownership as ownership
    def respond(url, **kwargs):
        if url.endswith('t187ap03_L'):
            return json.dumps([{'公司代號': '2330', '已發行普通股數': 1000}]).encode()
        if url.endswith('t187ap03_P'):
            return b'[]'
        if url.endswith('t187ap11_L'):
            return json.dumps([{'公司代號': '2330', '資料年月': '11509', '職稱': '董事本人', '目前持股': 70}]).encode()
        raise TimeoutError('dummy private transport detail')
    monkeypatch.setattr(ownership, '_request', respond)
    errors = []
    rows = ownership.fetch_twse_director_rows(['2330'], on_error=lambda source, exc: errors.append((source, type(exc).__name__)))
    assert rows[0]['directorSupervisorPct'] is None
    assert errors == [('TWSE:t187ap11_P', 'TimeoutError')]


def test_previous_future_ownership_rows_cannot_enter_historical_cache(tmp_path, monkeypatch):
    import scripts.fetch_ownership as ownership
    output = tmp_path / 'snapshot.json'
    output.write_text(json.dumps({'schemaVersion': OWNERSHIP_SNAPSHOT_VERSION, 'rows': [
        {'code': '2330', 'period': '2026-09', 'asOf': '2026-09-25', 'largeHolderPct': 4},
        {'code': '2330', 'period': '2026-10', 'asOf': '2026-10-09', 'largeHolderPct': 99},
        {'code': '2330', 'period': '2026-08', 'asOf': '2026-08-28', 'publishedAt': '2026-10-03', 'largeHolderPct': 99}]}))
    result = ownership.acquire_snapshot(output, ['2330'], as_of='2026-10-02', fetcher=lambda: [])
    assert [(row['period'], row['largeHolderPct']) for row in result['rows']] == [('2026-09', 4)]


def test_history_success_is_checkpointed_before_later_request_cap(tmp_path, monkeypatch):
    import scripts.fetch_ownership as ownership
    import urllib.request
    import io
    html = b'<table><tr><th>\xe5\xba\x8f</th><th>\xe6\x8c\x81\xe8\x82\xa1/\xe5\x96\xae\xe4\xbd\x8d\xe6\x95\xb8\xe5\x88\x86\xe7\xb4\x9a</th><th>\xe4\xba\xba\xe6\x95\xb8</th><th>\xe8\x82\xa1\xe6\x95\xb8/\xe5\x96\xae\xe4\xbd\x8d\xe6\x95\xb8</th><th>\xe5\x8d\xa0\xe9\x9b\x86\xe4\xbf\x9d%</th></tr><tr><td>15</td><td>large</td><td>1</td><td>100</td><td>4</td></tr><tr><td>17</td><td>\xe5\x90\x88\xe8\xa8\x88</td><td>10</td><td>1000</td><td>100</td></tr></table>'
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(('<span>資料日期：115年07月31日</span>'.encode()+html) if request.data else b'<select name="scaDate"><option value="20260731">date</option></select><input name="SYNCHRONIZER_TOKEN" value="public-test">')
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: Opener())
    monkeypatch.setattr(ownership, 'fetch_tdcc', lambda **kwargs: [])
    monkeypatch.setattr(ownership, 'fetch_twse_director_rows', lambda *args, **kwargs: [])
    result = ownership.acquire_snapshot(tmp_path / 'snapshot.json', ['2330'], as_of='2026-10-02', max_requests=3, max_history_requests=3)
    assert result['rows'][0]['period'] == '2026-07'
    assert result['rows'][0]['largeHolderPct'] == 4 and result['status'] == 'stale'
    assert result['acquisition']['requests'] == 3
    assert result['acquisition']['errors'][-1]['category'] == 'request_limit'


def test_previous_verified_months_allow_history_budget_to_progress_on_retry(tmp_path, monkeypatch):
    import scripts.fetch_ownership as ownership
    output = tmp_path / 'snapshot.json'
    monkeypatch.setattr(ownership, 'fetch_tdcc', lambda **kwargs: [])
    monkeypatch.setattr(ownership, 'fetch_twse_director_rows', lambda *args, **kwargs: [])
    requested = []
    def historical(code, months, **kwargs):
        requested.append((code, list(months)))
        month = months[0]
        return [{'code': code, 'period': month, 'asOf': month + '-28', 'largeHolderPct': 4, 'shareholderCount': 10}]
    monkeypatch.setattr(ownership, 'fetch_tdcc_historical', historical)
    first = ownership.acquire_snapshot(output, ['2330'], as_of='2026-10-02')
    second = ownership.acquire_snapshot(output, ['2330'], as_of='2026-10-02')
    assert requested == [('2330', ['2026-07', '2026-08', '2026-09']), ('2330', ['2026-08', '2026-09'])]
    assert [row['period'] for row in second['rows']] == ['2026-07', '2026-08']
    assert first['status'] == second['status'] == 'stale'


def test_cli_partial_cache_returns_zero_with_sanitized_limits_and_counts(tmp_path, monkeypatch, capsys):
    import scripts.fetch_ownership as ownership
    monkeypatch.setattr(ownership, 'fetch_tdcc', lambda **kwargs: [])
    monkeypatch.setattr(ownership, 'fetch_twse_director_rows', lambda *args, **kwargs: [])
    assert ownership.main(['--codes', '2330', '--output', str(tmp_path / 'snapshot.json'), '--as-of', '2026-10-02',
                           '--max-runtime-seconds', '180', '--max-requests', '40', '--max-history-requests', '0']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'unavailable'
    assert result['acquisition']['asOf'] == '2026-10-02'
    assert result['acquisition']['requests'] == result['acquisition']['historyRequests'] == 0
    assert result['acquisition']['errors'][0]['category'] == 'history_request_limit'


def test_cli_invalid_limits_or_codes_fail_before_http_and_write(tmp_path, monkeypatch):
    import scripts.fetch_ownership as ownership
    calls = []
    monkeypatch.setattr(ownership, 'fetch_tdcc', lambda **kwargs: calls.append(kwargs) or [])
    args = ['--codes', '2330', '--output', str(tmp_path / 'snapshot.json')]
    assert ownership.main([*args, '--max-runtime-seconds', '0']) == 1
    assert ownership.main([*args, '--max-history-requests', '41']) == 1
    assert ownership.main([*args, '--codes', 'invalid']) == 1
    assert calls == [] and not list(tmp_path.iterdir())


def test_all_three_target_months_required_for_current_status_not_arbitrary_old_history():
    old = [{'code': '2330', 'period': month, 'asOf': month + '-28', 'largeHolderPct': 4, 'shareholderCount': 10}
           for month in ['2026-07', '2026-08', '2026-09']]
    assert build_snapshot(None, old, requested_codes=['2330'], as_of='2026-10-02')['status'] == 'current'
    valid = [{**row, 'period': month, 'asOf': month + '-01'} for row, month in zip(old, ['2026-08', '2026-09', '2026-10'])]
    assert build_snapshot(None, valid, requested_codes=['2330'], as_of='2026-10-02')['status'] == 'stale'


def test_streaming_body_deadline_is_checked_between_chunks_without_accepting_partial_data(monkeypatch):
    import scripts.fetch_ownership as ownership
    import pytest
    clock = [0.0]
    monkeypatch.setattr(ownership.time, 'monotonic', lambda: clock[0])
    budget = ownership.OwnershipBudget(max_runtime_seconds=5, max_requests=40, max_history_requests=20)
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read1(self, size): clock[0] += 3; return b'partial'
        def read(self): raise AssertionError('unbounded read')
    monkeypatch.setattr(ownership, 'urlopen', lambda *args, **kwargs: Stream())
    with pytest.raises(ownership.OwnershipLimit, match='runtime_limit'):
        ownership._request(ownership.TDCC_URL, budget=budget)
    assert budget.requests == 1 and clock[0] == 6


def test_month_cutoff_preserves_dated_rows_through_month_end(tmp_path):
    import scripts.fetch_ownership as ownership
    rows = [
        {'code': '2330', 'period': '2026-10', 'asOf': '2026-10-02', 'availableAt': '2026-10-31', 'largeHolderPct': 4},
        {'code': '2317', 'period': '2026-10', 'asOf': '2026-10-02', 'availableAt': '2026-11-01', 'largeHolderPct': 9},
        {'code': '2308', 'period': '2026-11', 'asOf': '2026-11-01', 'largeHolderPct': 9},
    ]
    result = ownership.acquire_snapshot(tmp_path / 'snapshot.json', ['2330', '2317', '2308'],
                                        as_of='2026-10', fetcher=lambda: rows)
    assert [(row['code'], row['asOf']) for row in result['rows']] == [('2330', '2026-10-02')]
    assert result['acquisition']['asOf'] == '2026-10'


def test_late_failure_keeps_latest_successful_checkpoint_and_sanitized_error(tmp_path, monkeypatch):
    import scripts.fetch_ownership as ownership
    row = {'code': '2330', 'period': '2026-09', 'asOf': '2026-09-25', 'largeHolderPct': 0, 'shareholderCount': 10}
    def acquire(*args, **kwargs):
        kwargs['on_checkpoint']([row])
        raise RuntimeError('dummy private transport detail')
    monkeypatch.setattr(ownership, 'fetch_ownership_rows', acquire)
    output = tmp_path / 'snapshot.json'
    result = ownership.acquire_snapshot(output, ['2330'], as_of='2026-10-02')
    assert result['status'] == 'stale' and result['rows'][0]['largeHolderPct'] == 0
    assert result['rows'][0]['shareholderCount'] == 10
    assert result['acquisition']['errors'] == [{'source': 'ownership', 'category': 'RuntimeError'}]
    assert 'dummy' not in output.read_text()


def test_redirects_cannot_issue_unbudgeted_bulk_or_history_http(monkeypatch):
    import scripts.fetch_ownership as ownership
    import urllib.request
    import urllib.response
    import email.message
    import io
    import pytest
    requests = []
    class RedirectResponse(urllib.response.addinfourl):
        msg = 'Found'
    class Transport(urllib.request.HTTPHandler):
        def http_open(self, request):
            requests.append(request.full_url)
            headers = email.message.Message()
            if request.full_url.endswith('/start'):
                headers['Location'] = 'http://public.example/end'
                return RedirectResponse(io.BytesIO(b''), headers, request.full_url, 302)
            return RedirectResponse(io.BytesIO(b'<html></html>'), headers, request.full_url, 200)
    original = urllib.request.build_opener
    def opener(*handlers): return original(Transport(), *handlers)
    monkeypatch.setattr(urllib.request, 'build_opener', opener)
    monkeypatch.setattr(urllib.request, '_opener', opener())
    budget = ownership.OwnershipBudget(max_requests=1, max_history_requests=1)
    with pytest.raises(Exception):
        ownership._request('http://public.example/start', budget=budget, retries=0)
    assert requests == ['http://public.example/start'] and budget.requests == 1
    requests.clear()
    monkeypatch.setattr(ownership, 'TDCC_HISTORY_URL', 'http://public.example/start')
    budget = ownership.OwnershipBudget(max_requests=1, max_history_requests=1)
    with pytest.raises(Exception):
        ownership.fetch_tdcc_historical('2330', ['2026-09'], budget=budget)
    assert requests == ['http://public.example/start'] and budget.history_requests == 1
