from scripts import prepare_peg_evidence
import pytest


@pytest.mark.parametrize('expiry_point,expected_calls', [('candidate', 1), ('retry', 2)])
def test_runtime_budget_keeps_partial_evidence_and_emits_one_result_per_stock(tmp_path, monkeypatch, expiry_point, expected_calls):
    clock = [0.0]
    calls = []
    stocks = [
        {'code': '1001', 'legalName': 'Alpha', 'officialDomains': ['alpha.example']},
        {'code': '1002', 'legalName': 'Beta', 'officialDomains': ['beta.example']},
    ]

    def discover(stock):
        count = 2 if stock['code'] == '1001' else 1
        return {'candidates': [
            {'url': f"https://{stock['officialDomains'][0]}/report-{index}.pdf", 'title': 'Annual report'}
            for index in range(count)
        ]}

    def fetch(url, domains):
        calls.append(url)
        if url.endswith('report-0.pdf'):
            clock[0] = 6.0 if expiry_point == 'candidate' else 1.0
            return b'first', 'sha-first'
        clock[0] = 6.0
        raise TimeoutError('read timed out')

    monkeypatch.setattr(prepare_peg_evidence, 'discover', discover)
    monkeypatch.setattr(prepare_peg_evidence, 'fetch_document', fetch)
    monkeypatch.setattr(prepare_peg_evidence, 'parse_document', lambda *args, **kwargs: [
        {'period': '2025-Q4', 'eps': 3.2, 'epsKind': 'basic', 'scope': 'consolidated', 'sourceUrl': args[1]},
    ])
    monkeypatch.setattr(prepare_peg_evidence.time, 'monotonic', lambda: clock[0])

    result = prepare_peg_evidence.run(
        {'stocks': stocks}, output_dir=tmp_path, max_runtime_seconds=5,
    )

    assert [item['code'] for item in result] == ['1001', '1002']
    assert len({item['code'] for item in result}) == len(stocks)
    assert result[0]['records'][0]['eps'] == 3.2
    assert [source['status'] for source in result[0]['sources']] == ['parsed', 'budget_exhausted']
    assert result[0]['reason'] == 'evidence_budget_exhausted'
    assert result[1]['reason'] == 'evidence_budget_exhausted'
    assert result[1]['records'] == [] and result[1]['sources'] == []
    assert len(calls) == expected_calls  # expired candidate/retry and remaining stock never fetch
