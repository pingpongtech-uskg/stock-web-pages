import base64
import hashlib
import io
import importlib
import json
import tempfile
import sys
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from pipeline.official_market_closures import (
    apply_verified_closures, build_closure_evidence, merge_closure_evidence,
    validate_closure_evidence_size,
    verify_closure_evidence,
)

DAY = date(2026, 10, 23)
TITLE = '臺灣證券交易所集中交易市場115年10月23日休市一天'
DETAIL_PATH = '/rwd/zh/news/newsDetail/8a8216d6a0fa351b01a1638507a10203'
PDF_PATH = '/news/news/tsecnews/8a8216d6a0fa351b01a1638507940202.pdf'
BODY = '臺灣證券交易所表示，由於颱風來襲，臺北市政府宣布全體公教機關停止上班，115年10月23日集中交易市場全日休市，當日應屆交割款券順延辦理。'
RETRIEVED = '2026-10-27T12:00:00+00:00'


def fixture(title=TITLE, body=BODY, link=DETAIL_PATH, *, detail_date='202610222010', pub_date='Thu, 22 Oct 2026 12:10:00 GMT'):
    rss = f'''<?xml version="1.0"?><rss><channel><item><title>{title}</title><link>{link}</link><guid>{link}</guid><description/><content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">{body}</content:encoded><pubDate>{pub_date}</pubDate></item></channel></rss>'''.encode()
    detail = json.dumps({'stat': 'ok', 'date': detail_date, 'tables': [{'title': title,
        'fields': ['text', 'html', 'pdf', 'lang'], 'data': ['', '', PDF_PATH, '8a8216d6a0fa351b01a1638557450205']}]}, ensure_ascii=False).encode()
    return rss, detail


def base_calendar():
    return {'schemaVersion': 'trading-calendar-v1', 'timezone': 'Asia/Taipei', 'year': 2026,
            'closedDates': ['2026-01-01'], 'openExceptions': [],
            'sourceUrl': 'https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule',
            'fetchedAt': '2026-01-01T00:00:00+00:00'}


def _import_test_module_isolated(module_name, dependencies):
    sentinel = object()
    importlib.import_module('pipeline')
    importlib.import_module('scripts')
    prior_packages = {
        name: sys.modules.get(name)
        for name in ('pipeline', 'scripts')
        if sys.modules.get(name) is not None
    }
    prior_attributes = {
        name: dict(vars(package)) for name, package in prior_packages.items()
    }
    prior_children = {
        name: module for name, module in sys.modules.items()
        if name.startswith(('pipeline.', 'scripts.'))
    }
    try:
        with patch.dict(sys.modules, dependencies):
            sys.modules.pop(module_name, None)
            return importlib.import_module(module_name)
    finally:
        changed_children = {
            name for name in (*prior_children, *sys.modules)
            if name.startswith(('pipeline.', 'scripts.'))
            and sys.modules.get(name, sentinel) is not prior_children.get(name, sentinel)
        }
        for name in changed_children:
            prior_module = prior_children.get(name, sentinel)
            if prior_module is sentinel:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = prior_module
        for package_name, package in prior_packages.items():
            previous = prior_attributes[package_name]
            for attribute in set(previous) | set(vars(package)):
                prior_attribute = previous.get(attribute, sentinel)
                current_attribute = vars(package).get(attribute, sentinel)
                is_child_module = any(
                    isinstance(value, types.ModuleType)
                    and value.__name__.startswith(package_name + '.')
                    for value in (prior_attribute, current_attribute)
                )
                if is_child_module and current_attribute is not prior_attribute:
                    if prior_attribute is sentinel:
                        vars(package).pop(attribute, None)
                    else:
                        setattr(package, attribute, prior_attribute)


def _load_market_cache_restore_with_test_dependencies():
    release = types.ModuleType('pipeline.release_contract')
    release.is_common_stock_code = lambda value: True
    indicators = types.ModuleType('pipeline.market_indicators')
    indicators.TWSE_STOCK_DAY = 'https://www.twse.com.tw/exchangeReport/STOCK_DAY'
    indicators.SYMBOL = '2330'
    indicators._date = lambda value: date.fromisoformat(value.replace('/', '-'))
    indicators._volume = lambda value: float(value) if value else None
    cache_index = types.ModuleType('scripts.build_market_cache_index')
    cache_index._verify_institutional_groups = lambda *args, **kwargs: None
    cache_index.stock_metrics = lambda *args, **kwargs: {}
    export = types.ModuleType('scripts.export_market_cache')
    export._json = lambda raw: json.loads(raw)
    export._read = lambda *args, **kwargs: b''
    export.load_inputs = lambda *args, **kwargs: {}
    return _import_test_module_isolated('pipeline.market_cache_restore', {
        'pipeline.release_contract': release,
        'pipeline.market_indicators': indicators,
        'scripts.build_market_cache_index': cache_index,
        'scripts.export_market_cache': export,
    })


def _load_official_institutional_with_test_dependencies():
    release = types.ModuleType('pipeline.release_contract')
    release.is_common_stock_code = lambda value: True
    return _import_test_module_isolated('pipeline.official_institutional', {
        'pipeline.release_contract': release,
    })


class OfficialClosureTests(unittest.TestCase):
    def evidence(self, rss=None, detail=None):
        rss, detail = fixture() if rss is None else (rss, detail)
        return build_closure_evidence(rss, lambda url: detail, target=DAY, retrieved_at=RETRIEVED)

    def test_official_full_day_evidence_replays_and_closes_calendar_date(self):
        evidence = self.evidence()
        self.assertEqual([item['date'] for item in verify_closure_evidence(evidence)], ['2026-10-23'])
        merged = apply_verified_closures(base_calendar(), json.loads(json.dumps(evidence)))
        self.assertIn('2026-10-23', merged['closedDates'])
        self.assertNotIn('2026-10-23', merged['openExceptions'])

    def test_current_feed_does_not_discard_prior_verified_closure(self):
        prior = self.evidence()
        rss, detail = fixture(TITLE.replace('10月23日', '10月26日'),
            BODY.replace('10月23日', '10月26日'))
        current = build_closure_evidence(rss, lambda url: detail, target=date(2026, 10, 27), retrieved_at=RETRIEVED)
        merged = merge_closure_evidence([prior], [current])
        dates = {item['date'] for evidence in merged for item in verify_closure_evidence(evidence)}
        self.assertEqual(dates, {'2026-10-23', '2026-10-26'})

    def test_wrong_roc_year_half_day_and_nonofficial_link_are_rejected(self):
        for title in ['臺灣證券交易所集中交易市場114年10月23日休市一天',
                      '臺灣證券交易所集中交易市場115年10月23日上午休市']:
            rss, detail = fixture(title)
            self.assertEqual(self.evidence(rss, detail)['notices'], [])
        for rss, detail in [
            fixture(TITLE, link='https://evil.example/rwd/zh/news/newsDetail/8a8216d6a0fa351b01a1638507a10203'),
            fixture(TITLE, body=BODY.replace('全日休市', '上午休市')),
        ]:
            with self.assertRaises(ValueError):
                self.evidence(rss, detail)

    def test_tampered_nested_source_bytes_are_rejected(self):
        evidence = self.evidence()
        evidence['feed']['rawBase64'] = base64.b64encode(b'<rss/>').decode()
        with self.assertRaisesRegex(ValueError, 'hash'):
            verify_closure_evidence(evidence)

    def test_nested_closure_receipts_are_bounded_before_cache_write(self):
        evidence = self.evidence()
        with self.assertRaisesRegex(ValueError, 'size limit'):
            validate_closure_evidence_size([{'closureEvidence': [evidence] * 1000}])

    def test_detail_publication_date_must_match_rss_metadata(self):
        rss, detail = fixture()
        with self.assertRaisesRegex(ValueError, 'publication date'):
            build_closure_evidence(rss, lambda url: fixture(detail_date='202610212010')[1],
                target=DAY, retrieved_at=RETRIEVED)

    def test_official_feed_redirect_is_ignored_as_unverified_evidence(self):
        from scripts.build_trading_calendar import main
        class Redirected(io.BytesIO):
            def geturl(self):
                return 'https://untrusted.example/rss'
        rows = [
            {'Name': '國曆新年開始交易日', 'Date': '1150102', 'Weekday': '五', 'Description': '交易'},
            {'Name': '市場無交易，僅辦理結算交割作業', 'Date': '1150212', 'Weekday': '四', 'Description': ''},
        ]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'calendar.json'
            def respond(request, **kwargs):
                if request.full_url.endswith('/holidaySchedule'):
                    return io.BytesIO(json.dumps(rows, ensure_ascii=False).encode())
                return Redirected(b'<rss><channel/></rss>')
            with patch('scripts.build_trading_calendar.urlopen', respond):
                self.assertEqual(main(['--market-date', '2026-10-27', '--output', str(output)]), 0)
            self.assertNotIn('2026-10-23', json.loads(output.read_bytes())['closedDates'])

    def test_calendar_receipt_round_trip_revalidates_nested_closure_proof(self):
        from scripts.build_trading_calendar import main, _verified_restored_calendar
        rows = [
            {'Name': '國曆新年開始交易日', 'Date': '1150102', 'Weekday': '五', 'Description': '交易'},
            {'Name': '市場無交易，僅辦理結算交割作業', 'Date': '1150212', 'Weekday': '四', 'Description': ''},
        ]
        rss, detail = fixture()
        def response(request, **kwargs):
            if request.full_url.endswith('/holidaySchedule'):
                return io.BytesIO(json.dumps(rows, ensure_ascii=False).encode())
            if request.full_url.endswith('/feed?type=rss'):
                return io.BytesIO(rss)
            if request.full_url == 'https://www.twse.com.tw' + DETAIL_PATH:
                return io.BytesIO(detail)
            raise AssertionError('unexpected source URL')
        with tempfile.TemporaryDirectory() as temp, patch('scripts.build_trading_calendar.urlopen', response):
            root = Path(temp)
            cache, output = root / 'cache', root / 'calendar.json'
            self.assertEqual(main(['--market-date', '2026-10-27', '--output', str(output),
                                   '--source-cache-dir', str(cache)]), 0)
            restored, receipts = _verified_restored_calendar(cache)
            self.assertIn('2026-10-23', restored['closedDates'])
            self.assertEqual(len(receipts[2026][0]['closureEvidence']), 1)
            bundle_path = cache / 'calendar.raw.bundle.json'
            bundle = json.loads(bundle_path.read_bytes())
            bundle['receipts'][0]['closureEvidence'][0]['feed']['rawBase64'] = base64.b64encode(b'<rss/>').decode()
            bundle_bytes = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            bundle_path.write_bytes(bundle_bytes)
            index_path = cache / 'calendar-receipt-index.json'
            index = json.loads(index_path.read_bytes())
            digest = hashlib.sha256(bundle_bytes).hexdigest()
            for group in index['groups']:
                group['sourceSha256'] = digest
                group['normalizedFromSha256'] = digest if group['kind'] == 'calendar_normalized' else None
            index_path.write_text(json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
            with self.assertRaisesRegex(ValueError, 'hash'):
                _verified_restored_calendar(cache)
            def no_closure_sources(request, **kwargs):
                if request.full_url.endswith('/holidaySchedule'):
                    return io.BytesIO(json.dumps(rows, ensure_ascii=False).encode())
                return io.BytesIO(b'<rss><channel/></rss>')
            with patch('scripts.build_trading_calendar.urlopen', no_closure_sources):
                self.assertEqual(main(['--market-date', '2026-10-27', '--output', str(root / 'after-tamper.json'),
                    '--source-cache-dir', str(cache)]), 0)
            self.assertNotIn('2026-10-23', json.loads((root / 'after-tamper.json').read_bytes())['closedDates'])
            bundle_path = cache / 'calendar.raw.bundle.json'
            legacy_bundle = json.loads(bundle_path.read_bytes())
            legacy_bundle['receipts'][0].pop('closureEvidence')
            legacy_raw = json.dumps(legacy_bundle, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            bundle_path.write_bytes(legacy_raw)
            index = json.loads((cache / 'calendar-receipt-index.json').read_bytes())
            digest = hashlib.sha256(legacy_raw).hexdigest()
            for group in index['groups']:
                group['sourceSha256'] = digest
                group['normalizedFromSha256'] = digest if group['kind'] == 'calendar_normalized' else None
            (cache / 'calendar-receipt-index.json').write_text(json.dumps(index, ensure_ascii=False,
                sort_keys=True, separators=(',', ':')))
            legacy_calendar, legacy_receipts = _verified_restored_calendar(cache)
            self.assertNotIn('2026-10-23', legacy_calendar['closedDates'])
            self.assertNotIn('closureEvidence', legacy_receipts[2026][0])

    def test_rss_outage_reuses_only_verified_closure_receipt_from_source_cache(self):
        from scripts.build_trading_calendar import main
        rows = [
            {'Name': '國曆新年開始交易日', 'Date': '1150102', 'Weekday': '五', 'Description': '交易'},
            {'Name': '市場無交易，僅辦理結算交割作業', 'Date': '1150212', 'Weekday': '四', 'Description': ''},
        ]
        rss, detail = fixture()
        with tempfile.TemporaryDirectory() as temp:
            root, cache = Path(temp), Path(temp) / 'cache'
            output = root / 'first.json'
            def first(request, **kwargs):
                if request.full_url.endswith('/holidaySchedule'):
                    return io.BytesIO(json.dumps(rows, ensure_ascii=False).encode())
                if request.full_url.endswith('/feed?type=rss'):
                    return io.BytesIO(rss)
                return io.BytesIO(detail)
            with patch('scripts.build_trading_calendar.urlopen', first):
                self.assertEqual(main(['--market-date', '2026-10-27', '--output', str(output),
                                       '--source-cache-dir', str(cache)]), 0)
            def feed_outage(request, **kwargs):
                if request.full_url.endswith('/holidaySchedule'):
                    return io.BytesIO(json.dumps(rows, ensure_ascii=False).encode())
                raise OSError('RSS unavailable')
            output2 = root / 'second.json'
            with patch('scripts.build_trading_calendar.urlopen', feed_outage):
                self.assertEqual(main(['--market-date', '2026-10-27', '--output', str(output2),
                                       '--source-cache-dir', str(cache)]), 0)
            self.assertIn('2026-10-23', json.loads(output2.read_bytes())['closedDates'])

    def test_january_composite_calendar_preserves_verified_prior_year_closure_receipt(self):
        from scripts.build_trading_calendar import main, _verified_restored_calendar
        prior_rows = [
            {'Name': '國曆新年開始交易日', 'Date': '1150102', 'Weekday': '五', 'Description': '交易'},
            {'Name': '市場無交易，僅辦理結算交割作業', 'Date': '1150212', 'Weekday': '四', 'Description': ''},
        ]
        current_rows = [
            {'Name': '國曆新年開始交易日', 'Date': '1160104', 'Weekday': '一', 'Description': '交易'},
            {'Name': '市場無交易，僅辦理結算交割作業', 'Date': '1160101', 'Weekday': '五', 'Description': ''},
        ]
        title = TITLE.replace('10月23日', '12月30日')
        body = BODY.replace('10月23日', '12月30日')
        closure_rss, detail = fixture(title, body, detail_date='202612292010',
            pub_date='Tue, 29 Dec 2026 12:10:00 GMT')
        no_notices = b'<rss><channel/></rss>'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prior_cache, current_cache = root / 'prior', root / 'current'
            def prior_source(request, **kwargs):
                if request.full_url.endswith('/holidaySchedule'):
                    return io.BytesIO(json.dumps(prior_rows, ensure_ascii=False).encode())
                if request.full_url.endswith('/feed?type=rss'):
                    return io.BytesIO(no_notices)
                return io.BytesIO(detail)
            with patch('scripts.build_trading_calendar.urlopen', prior_source):
                self.assertEqual(main(['--market-date', '2026-12-31', '--output', str(root / 'prior.json'),
                    '--source-cache-dir', str(prior_cache)]), 0)
            def current_source(request, **kwargs):
                if request.full_url.endswith('/holidaySchedule'):
                    return io.BytesIO(json.dumps(current_rows, ensure_ascii=False).encode())
                if request.full_url.endswith('/feed?type=rss'):
                    return io.BytesIO(closure_rss)
                return io.BytesIO(detail)
            with patch('scripts.build_trading_calendar.urlopen', current_source):
                self.assertEqual(main(['--market-date', '2027-01-04', '--output', str(root / 'current.json'),
                    '--source-cache-dir', str(current_cache), '--prior-calendar-cache-dir', str(prior_cache)]), 0)
            merged, receipts = _verified_restored_calendar(current_cache)
            self.assertIn('2026-12-30', merged['calendars'][0]['closedDates'])
            self.assertEqual(len(receipts[2026][0]['closureEvidence']), 1)

    def test_market_cache_semantics_replay_closure_and_reject_tampered_evidence(self):
        restore = _load_market_cache_restore_with_test_dependencies()
        from pipeline.trading_calendar import build_calendar, recent_sessions
        from pipeline.official_market_closures import apply_verified_closures
        rows = [
            {'Name': '國曆新年開始交易日', 'Date': '1150102', 'Weekday': '五', 'Description': '交易'},
            {'Name': '市場無交易，僅辦理結算交割作業', 'Date': '1150212', 'Weekday': '四', 'Description': ''},
        ]
        rss, detail = fixture()
        evidence = build_closure_evidence(rss, lambda url: detail, target=date(2026, 10, 27), retrieved_at=RETRIEVED)
        raw_calendar = json.dumps(rows, ensure_ascii=False).encode()
        receipt = {'sourceUrl': 'https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule',
            'unit': 'calendar', 'requestYear': 2026, 'retrievedAt': '2026-10-27T12:00:00+00:00',
            'closureEvidence': [evidence]}
        expected_calendar = apply_verified_closures(build_calendar(rows, year=2026, fetched_at=receipt['retrievedAt']), evidence)
        dates = list(reversed(recent_sessions(expected_calendar, '2026-10-27', count=11)))
        expected = {'marketDate': '2026-10-27', 'calendarYear': 2026, 'sessionDates': dates,
            'previousTradingDate': dates[-2], 'volumeDates': dates[-7:], 'metricKeys': []}
        raw_groups = {'calendar_normalized': {'key': 'calendar_normalized', 'body': expected_calendar},
            'calendar_raw': {'key': 'calendar_raw', 'body': b'{}'},
            'volume_raw': {'key': 'volume_raw', 'body': b'{}'},
            'volume_normalized': {'key': 'volume_normalized', 'body': {'rows': []}},
            'published_stock_inputs': {'key': 'published_stock_inputs', 'body': {'rows': []}}}
        def receipts(group):
            if group['key'] == 'calendar_raw':
                return [(receipt, raw_calendar)]
            if group['key'] == 'volume_raw':
                result = []
                for month in ['2026-09', '2026-10']:
                    payload = {'stat': 'OK', 'date': month.replace('-', '/') + '/01',
                        'fields': ['日期', '成交股數'], 'data': []}
                    url = 'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=' + month.replace('-', '') + '01&stockNo=2330'
                    result.append(({'requestMonth': month, 'sourceUrl': url, 'unit': 'shares'},
                                   json.dumps(payload).encode()))
                return result
            return []
        with patch.object(restore, '_receipts', side_effect=receipts):
            self.assertNotIn('2026-10-23', dates)
            self.assertEqual(restore._official_semantics(list(raw_groups.values()), expected)['calendar_normalized']['body'], expected_calendar)
            tampered = json.loads(json.dumps(evidence))
            tampered['feed']['rawBase64'] = base64.b64encode(b'<rss/>').decode()
            receipt['closureEvidence'] = [tampered]
            with self.assertRaisesRegex(restore.MarketCacheError, 'cache_restore_calendar'):
                restore._official_semantics(list(raw_groups.values()), expected)
            legacy_receipt = {key: value for key, value in receipt.items() if key != 'closureEvidence'}
            raw_groups['calendar_normalized']['body'] = build_calendar(rows, year=2026, fetched_at=legacy_receipt['retrievedAt'])
            legacy_dates = list(reversed(recent_sessions(raw_groups['calendar_normalized']['body'], '2026-10-27', count=11)))
            legacy_expected = {**expected, 'sessionDates': legacy_dates,
                'previousTradingDate': legacy_dates[-2], 'volumeDates': legacy_dates[-7:]}
            receipt.clear(); receipt.update(legacy_receipt)
            self.assertEqual(restore._official_semantics(list(raw_groups.values()), legacy_expected)['calendar_normalized']['body'],
                raw_groups['calendar_normalized']['body'])

    def test_market_cache_test_import_restores_module_state(self):
        package = importlib.import_module('pipeline')
        sentinel = object()
        prior_module = sys.modules.get('pipeline.market_cache_restore', sentinel)
        prior_attribute = vars(package).get('market_cache_restore', sentinel)

        _load_market_cache_restore_with_test_dependencies()

        self.assertIs(sys.modules.get('pipeline.market_cache_restore', sentinel), prior_module)
        self.assertIs(vars(package).get('market_cache_restore', sentinel), prior_attribute)

    def test_open_session_with_empty_official_data_still_fails(self):
        official = _load_official_institutional_with_test_dependencies()
        merged = apply_verified_closures(base_calendar(), self.evidence())
        self.assertEqual(merged['closedDates'], ['2026-01-01', '2026-10-23'])
        with patch.object(official, 'fetch_complete_day', return_value=[]):
            with self.assertRaisesRegex(official.OfficialInstitutionalError, 'open session 2026-10-27'):
                official.fetch_recent_complete_days(as_of=date(2026, 10, 27), sessions=1,
                    lookback_days=1, calendar=merged)

    def test_verified_closure_is_skipped_while_adjacent_open_sessions_remain_required(self):
        official = _load_official_institutional_with_test_dependencies()
        merged = apply_verified_closures(base_calendar(), self.evidence())
        calls = []
        def complete(day, **kwargs):
            calls.append(day.isoformat())
            if day.isoformat() == '2026-10-23':
                raise AssertionError('verified full-day closure must not be fetched')
            return [{'date': day.isoformat(), 'code': '2330', 'netShares': 1}]
        with patch.object(official, 'fetch_complete_day', side_effect=complete):
            days = official.fetch_recent_complete_days(as_of=date(2026, 10, 27), sessions=3,
                lookback_days=10, calendar=merged)
        self.assertEqual([item['date'] for item in days], ['2026-10-27', '2026-10-26', '2026-10-22'])
        self.assertNotIn('2026-10-23', calls)


if __name__ == '__main__':
    unittest.main()
