"""Raw quote dates and returns must never inherit adjusted research values."""
from datetime import date

import pytest

from scripts import refresh_snapshot as refresh


def enrich(monkeypatch, rows, *, offline=False, baseline=None):
    monkeypatch.setattr(refresh, 'fetch_adjusted_history', lambda *args: (rows, refresh.YFINANCE_PRICE_SOURCE, None))
    monkeypatch.setattr(refresh, 'fetch_fundamental_proxies', lambda *args: ({}, refresh.YFINANCE_FUNDAMENTAL_SOURCE, None))
    detail = {'code': '2330', 'priceSeries': rows if offline else [], **(baseline or {})}
    return refresh.enrich_detail(detail, end=date(2026, 10, 16), offline=offline)[0]


def test_latest_adjusted_day_does_not_redate_last_raw_quote(monkeypatch):
    result = enrich(monkeypatch, [
        {'date': '2026-10-14', 'close': 80, 'adjustedClose': 80},
        {'date': '2026-10-15', 'close': 100, 'adjustedClose': 90},
        {'date': '2026-10-16', 'close': None, 'adjustedClose': 95},
    ])
    assert result['asOf'] == result['quoteAsOf'] == '2026-10-15'
    assert result['lastPrice'] == 100
    assert result['changePct'] == .25
    assert result['adjustedLastPrice'] == 95
    assert result['regression']['historyEnd'] == '2026-10-16'
    assert result['quoteBasis'] == 'raw_close'


def test_adjusted_return_never_replaces_missing_raw_return(monkeypatch):
    result = enrich(monkeypatch, [
        {'date': '2026-10-15', 'close': 100, 'adjustedClose': 90},
        {'date': '2026-10-16', 'close': None, 'adjustedClose': 95},
    ])
    assert result['lastPrice'] == 100
    assert result['changePct'] is None
    assert result['adjustedChangePct'] == pytest.approx(95 / 90 - 1)


def test_adjusted_only_research_curve_has_no_raw_quote(monkeypatch):
    result = enrich(monkeypatch, [{'date': '2026-10-16', 'adjustedClose': 95}])
    assert result['lastPrice'] is None
    assert result['asOf'] is None
    assert result['changePct'] is None
    assert result['quoteBasis'] == 'unavailable'
    assert result['quoteStatus'] == 'unknown'
    assert result['dataStatus'] == 'unknown'
    assert result['adjustedLastPrice'] == 95
    assert refresh._valuation_from_detail(result) is None
    assert refresh._growth_valuation_from_detail(result)['status'] == 'unavailable'


@pytest.mark.parametrize('bad', [0, -1, True, float('nan'), float('inf')])
def test_invalid_raw_quotes_are_not_displayed(monkeypatch, bad):
    result = enrich(monkeypatch, [{'date': '2026-10-16', 'close': bad, 'adjustedClose': 95}])
    assert result['lastPrice'] is None
    assert result['asOf'] is None
    assert result['quoteStatus'] == 'unknown'


def test_offline_retains_dated_raw_evidence_without_baseline_redating(monkeypatch):
    result = enrich(monkeypatch, [{'date': '2026-10-15', 'close': 100, 'adjustedClose': 90}],
                    offline=True, baseline={'asOf': '2026-10-16', 'lastPrice': 999})
    assert result['asOf'] == '2026-10-15'
    assert result['lastPrice'] == 100


def test_offline_bare_baseline_price_is_not_raw_evidence(monkeypatch):
    result = enrich(monkeypatch, [], offline=True,
                    baseline={'asOf': '2026-10-16', 'lastPrice': 999, 'priceBasis': 'adjusted'})
    assert result['lastPrice'] is None
    assert result['asOf'] is None


def test_raw_return_does_not_bridge_a_missing_intermediate_quote(monkeypatch):
    result = enrich(monkeypatch, [
        {'date': '2026-10-14', 'close': 80, 'adjustedClose': 80},
        {'date': '2026-10-15', 'adjustedClose': 90},
        {'date': '2026-10-16', 'close': 100, 'adjustedClose': 95},
    ])
    assert result['lastPrice'] == 100
    assert result['changePct'] is None


def test_zulu_valuation_requires_pe_from_actual_raw_quote_date(monkeypatch):
    monkeypatch.setattr(refresh, '_earnings_proxy_from_detail', lambda detail: {'growth': .2})
    detail = {'asOf': '2026-10-15', 'lastPrice': 100, 'quoteBasis': 'raw_close',
              'healthInputs': {'valuationCurrent': {'date': '2026-10-16', 'pe': 10}}}
    assert refresh._valuation_from_detail(detail) is None
    same_day = {**detail, 'healthInputs': {'valuationCurrent': {'date': '2026-10-15', 'pe': 10}}}
    assert refresh._valuation_from_detail(same_day)['current_price'] == 100


@pytest.mark.parametrize('prices,quote_date', [
    ([{'date': '2026-10-15', 'close': 100, 'adjustedClose': 90}], '2026-10-15'),
    ([{'date': '2026-10-16', 'adjustedClose': 95}], None),
    ([], None),
])
def test_requested_release_day_is_independent_of_lagging_or_missing_quotes(tmp_path, monkeypatch, prices, quote_date):
    import json
    data = tmp_path / 'public' / 'data'
    data.mkdir(parents=True)
    baseline = {'runId': 'fixture', 'marketDate': '2026-10-15', 'freshness': 'current',
                'stocks': [{'code': '2330', 'asOf': '2026-10-15', 'lastPrice': 999, 'priceSeries': prices}]}
    (data / 'latest.json').write_text(json.dumps(baseline))
    result = refresh.build_release(data, [], as_of='2026-10-16', offline=False, recompute_existing=True)
    release = json.loads((data / 'latest.json').read_text())
    assert result['market_date'] == release['marketDate'] == '2026-10-16'
    assert release['stocks'][0]['asOf'] == quote_date
    assert release['stocks'][0]['lastPrice'] == (100 if quote_date else None)
    assert '行情日期仍為 2026-10-16' not in release['statusMessage']


@pytest.mark.parametrize('requested', ['bad', '20261016', '2026-10-16junk'])
def test_release_rejects_nonexact_requested_market_date(tmp_path, requested):
    import json
    data = tmp_path / 'public' / 'data'
    data.mkdir(parents=True)
    (data / 'latest.json').write_text(json.dumps({'runId': 'fixture', 'marketDate': '2026-10-15',
                                                'stocks': [{'code': '2330', 'priceSeries': []}]}))
    with pytest.raises(ValueError, match='exact requested market date'):
        refresh.build_release(data, [], as_of=requested, offline=False, recompute_existing=True)
