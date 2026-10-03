#!/usr/bin/env python3
"""Assemble source-validated full-market receipts and a bound published release.

Authenticating CLI identity belongs to Actions/its consumer. This assembler
never obtains that identity from a generated cache manifest or calls providers.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.market_cache import MarketCacheError, MAX_TOTAL_RAW, ROLES, build_market_cache, canonical, sha
from pipeline.financial_periods import dividend_period, normalized_date
from pipeline.growth_health import evaluate_growth_health
from pipeline.screening_export import validate_export
from pipeline.valuation import derive_growth_inputs
from pipeline.trading_calendar import calendar_years, recent_sessions
from pipeline.official_institutional import (TWSE_ENDPOINT, TPEX_ENDPOINT, parse_twse_json_response,
                                             parse_tpex_csv, OfficialInstitutionalError)
from pipeline.source_receipts import safe_directory
from scripts.export_market_cache import _json, _read, load_inputs

METRIC_KEYS = ('currentPrice', 'currentPe', 'ttmEps', 'growth4y', 'eps2022', 'eps2023', 'eps2024', 'eps2025',
               'cashDividend2025', 'revenueYoY1', 'revenueYoY2', 'revenueYoY3', 'grossProfitYoY',
               'operatingProfitYoY', 'pretaxProfitYoY', 'netIncomeYoY')


def _require(ok, category):
    if not ok: raise MarketCacheError(f'cache_{category}')


def _safe_file(directory: Path, name: str) -> Path:
    _require(isinstance(name, str) and name and not Path(name).is_absolute() and '..' not in Path(name).parts, 'path')
    path = (directory / name).resolve()
    _require(path.is_relative_to(directory.resolve()), 'path')
    current = directory
    for component in Path(name).parts:
        current /= component
        _require(not current.is_symlink(), 'path')
    return path


def _store(path: Path, raw: bytes) -> None:
    try:
        parent = safe_directory(path.parent)
    except (OSError, ValueError) as exc:
        raise MarketCacheError('cache_path') from exc
    path = parent / path.name
    _require(not path.is_symlink(), 'path')
    parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _require(path.read_bytes() == raw, 'immutable')
        return
    fd, temporary = tempfile.mkstemp(prefix='.market-cache-', suffix='.tmp', dir=parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        _require(not path.is_symlink(), 'path')
        if path.exists():
            _require(path.read_bytes() == raw, 'immutable')
            return
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _projection(rows, *, normalized=False):
    fields = ['buy', 'sell', 'net'] if normalized else ['buyShares', 'sellShares', 'netShares']
    eligible = [row for row in rows if re.fullmatch(r'[1-9]\d{3}', str(row.get('code') or ''))]
    _require(len({row['code'] for row in eligible}) == len(eligible), 'receipt_membership')
    return {row['code']: tuple(row.get(field) for field in fields) for row in eligible}


def _reparse_receipt(receipt, raw, market, day):
    target = date.fromisoformat(day)
    source_url = TWSE_ENDPOINT if market == 'TWSE' else TPEX_ENDPOINT + '?' + urlencode({
        'type': 'Daily', 'sect': 'AL', 'date': target.strftime('%Y/%m/%d'), 'response': 'csv'})
    _require(receipt.get('sourceUrl') == source_url and receipt.get('unit') == 'shares'
             and receipt.get('requestDate') == day and receipt.get('reportedDate') == day
             and receipt.get('market') == market and receipt.get('validated') is True, 'receipt_lineage')
    _require(0 < len(raw) <= 2 * 1024 * 1024 and sha(raw) == receipt.get('rawSha256')
             and len(raw) == receipt.get('rawBytes'), 'receipt_hash')
    try:
        if market == 'TWSE':
            rows = parse_twse_json_response(raw, expected_date=target)
        else:
            rows = parse_tpex_csv(raw, expected_date=target)
    except (OfficialInstitutionalError, ValueError, TypeError, AttributeError) as exc:
        raise MarketCacheError('cache_receipt_parse') from exc
    projection = _projection(rows)
    _require(projection and sorted(projection) == receipt.get('codes'), 'receipt_membership')
    return projection


def _verify_institutional_groups(groups):
    _require(all(isinstance(group, dict) and isinstance(group.get('key'), str) for group in groups)
             and sorted(group['key'] for group in groups) == sorted(ROLES), 'roles')
    for market in ['TWSE', 'TPEx']:
        raw_group = next(group for group in groups if group['key'] == f'institutional_raw:{market}')
        normalized = next(group for group in groups if group['key'] == f'institutional_normalized:{market}')
        _require(sha(raw_group['body']) == raw_group['sourceSha256'] == normalized['normalizedFromSha256'], 'receipt_hash')
        bundle = _json(raw_group['body'])
        _require(isinstance(bundle, dict), 'receipt_bundle')
        receipts = bundle.get('receipts')
        _require(isinstance(receipts, list) and len(receipts) == 11, 'receipt_window')
        reported = []
        for receipt in receipts:
            _require(isinstance(receipt, dict) and isinstance(receipt.get('rawBase64'), str)
                     and len(receipt['rawBase64']) <= (2 * 1024 * 1024 + 2) // 3 * 4, 'receipt_bytes')
            try:
                raw = base64.b64decode(receipt['rawBase64'], validate=True)
            except (ValueError, TypeError) as exc:
                raise MarketCacheError('cache_receipt_bytes') from exc
            day = receipt.get('reportedDate')
            _require(day in raw_group['dates'] and day not in reported, 'receipt_date')
            source = _reparse_receipt(receipt, raw, market, day)
            _require(sorted(source) == raw_group['codesByDate'].get(day) == normalized['codesByDate'].get(day), 'receipt_membership')
            rows = [row for row in normalized['body']['rows'] if row.get('marketDate') == day]
            _require(_projection(rows, normalized=True) == source, 'receipt_values')
            reported.append(day)
        _require(sorted(reported) == raw_group['dates'], 'receipt_window')


def write_institutional_cache(snapshots: list[dict], directory: Path) -> None:
    """Capture all eligible source rows before the published Top100 filter."""
    _require(isinstance(snapshots, list) and len(snapshots) == 11, 'window')
    ordered = sorted(snapshots, key=lambda snapshot: snapshot['date'])
    dates = [snapshot['date'] for snapshot in ordered]
    _require(len(set(dates)) == 11, 'window')
    for market in ['TWSE', 'TPEx']:
        receipts, rows, codes_by_date = [], [], {}
        for snapshot in ordered:
            day = snapshot['date']
            eligible = [row for row in snapshot['rows'] if row.get('market') == market and re.fullmatch(r'[1-9]\d{3}', str(row.get('code') or ''))]
            codes = sorted(row['code'] for row in eligible)
            _require(codes and len(set(codes)) == len(codes), 'membership')
            receipt = _json(_read(directory / f'institutional-{market}-{day}-validated.json', 4 * 1024 * 1024))
            _require(isinstance(receipt, dict) and receipt.get('validated') is True and receipt.get('market') == market and receipt.get('reportedDate') == day and receipt.get('codes') == codes, 'receipt_membership')
            raw = _read(_safe_file(directory, receipt.get('rawFile')), 2 * 1024 * 1024)
            parsed = _reparse_receipt(receipt, raw, market, day)
            _require(_projection(eligible) == parsed, 'receipt_values')
            receipts.append({**receipt, 'rawBase64': base64.b64encode(raw).decode('ascii')})
            codes_by_date[day] = codes
            rows.extend({'marketDate': day, 'code': row['code'], 'buy': row.get('buyShares'), 'sell': row.get('sellShares'),
                         'net': row.get('netShares'), 'unit': 'shares', 'name': row.get('name', '')} for row in eligible)
        raw_body = canonical({'receipts': receipts})
        normalized = canonical({'rows': rows})
        digest = sha(raw_body)
        raw_name = f'institutional-{market}.{digest}.raw.bundle.json'
        normalized_name = f'institutional-{market}.{sha(normalized)}.normalized.json'
        _store(directory / raw_name, raw_body); _store(directory / normalized_name, normalized)
        codes = sorted({code for daily in codes_by_date.values() for code in daily})
        units = {receipt.get('unit') for receipt in receipts}
        _require(units <= {'shares', 'lots'}, 'units')
        groups = []
        for form, name in [('raw', raw_name), ('normalized', normalized_name)]:
            groups.append({'key': f'institutional_{form}:{market}', 'kind': f'institutional_{form}', 'market': market,
                           'codes': codes, 'codesByDate': codes_by_date, 'dates': dates,
                           'unit': 'shares' if form == 'normalized' else next(iter(units)) if len(units) == 1 else 'mixed',
                           'sourceUrl': receipts[-1]['sourceUrl'], 'sourceSha256': digest,
                           'normalizedFromSha256': digest if form == 'normalized' else None, 'bodyFile': name})
        # This mutable pointer references immutable content-addressed receipts.
        try:
            parent = safe_directory(directory)
        except (OSError, ValueError) as exc:
            raise MarketCacheError('cache_path') from exc
        fragment = parent / f'institutional-{market}-receipt-index.json'
        _require(not fragment.is_symlink(), 'path')
        temporary_fd, temporary_name = tempfile.mkstemp(prefix='.institutional-index-', suffix='.tmp', dir=parent)
        try:
            with os.fdopen(temporary_fd, 'wb') as output:
                output.write(canonical({'groups': groups}))
                output.flush()
                os.fsync(output.fileno())
            _require(not fragment.is_symlink(), 'path')
            os.replace(temporary_name, fragment)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def _numeric(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _cash_dividend(health, as_of):
    rows = health.get('dividends') or []
    by_period = {}
    for row in sorted(rows, key=lambda row: str(row.get('availableAt') or row.get('publishedAt') or '')):
        period = dividend_period(row.get('period') or row.get('year'), row.get('year'))
        dates = [normalized_date(row[field]) for field in ['approvedAt', 'publishedAt', 'availableAt', 'exDate', 'exDividendDate'] if row.get(field) not in (None, '')]
        if period and period[0] == 2025 and row.get('confirmed') is True:
            if not dates or any(day is None or len(day) != 10 or day > as_of for day in dates): return None
            cash = _numeric(row.get('cashPerShare'))
            if cash is not None and cash >= 0: by_period[period[1]] = cash
    periods = ['annual'] if 'annual' in by_period else ['H1', 'H2'] if set(by_period) == {'H1', 'H2'} else ['Q1', 'Q2', 'Q3', 'Q4'] if set(by_period) == {'Q1', 'Q2', 'Q3', 'Q4'} else []
    return sum(by_period[period] for period in periods) if periods else None


def stock_metrics(detail: dict, as_of: str) -> dict:
    health = detail.get('healthInputs') or {}
    valuation = derive_growth_inputs(detail)
    annual = valuation['growth'].get('annual_eps') or {}
    checks = evaluate_growth_health(health.get('monthlyRevenueOfficial') or [],
                                    [*(health.get('incomeQuarterly') or []), *(health.get('incomeYtd') or [])], as_of=as_of)['checks']
    revenue = checks[0]['value'] if isinstance(checks[0].get('value'), list) else []
    return {'currentPrice': _numeric(valuation['current_price']), 'currentPe': _numeric(valuation['current_pe']),
            'ttmEps': _numeric(valuation['ttm_eps']), 'growth4y': _numeric(valuation['growth'].get('growth')),
            **{f'eps{year}': _numeric(annual.get(year)) for year in range(2022, 2026)},
            'cashDividend2025': _cash_dividend(health, as_of),
            **{f'revenueYoY{index + 1}': _numeric(revenue[index]) if index < len(revenue) else None for index in range(3)},
            **{key: _numeric(checks[index + 1].get('value')) for index, key in enumerate(['grossProfitYoY', 'operatingProfitYoY', 'pretaxProfitYoY', 'netIncomeYoY'])}}


def _published(data_dir, config, market_date, source, publication_sha256, config_sha256, export_payload_hash):
    raw = _read(_safe_file(data_dir, 'latest.json'), 32 * 1024 * 1024)
    _require(sha(raw) == publication_sha256, 'publication_hash')
    release = _json(raw)
    fingerprint = _json(_read(_safe_file(data_dir, 'publication.json'), 4 * 1024 * 1024))
    _require(fingerprint.get('contentHash') == publication_sha256 and fingerprint.get('marketDate') == market_date and fingerprint.get('runId') == release.get('runId'), 'publication_identity')
    config_raw = _read(config, 4 * 1024 * 1024)
    _require(sha(config_raw) == config_sha256, 'config_hash')
    codes = _json(config_raw).get('symbols')
    _require(isinstance(codes, list) and len(codes) == 100 and len(set(codes)) == 100 and all(isinstance(code, str) and re.fullmatch(r'[1-9]\d{3}', code) for code in codes), 'tracked_codes')
    _require(release.get('marketDate') == market_date and sorted(row['code'] for row in release.get('stocks', [])) == sorted(codes), 'publication_codes')
    run_id = release.get('runId')
    _require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9._-]+', run_id), 'run_id')
    exported = _json(_read(_safe_file(data_dir, 'screening-export.json'), 4 * 1024 * 1024))
    _require(not validate_export(exported) and exported.get('payloadHash') == export_payload_hash and exported.get('marketDate') == market_date and exported.get('runId') == run_id, 'export_identity')
    _require(all(exported.get(key) == source[key] for key in source), 'export_lineage')
    directory = _safe_file(data_dir, f'releases/{run_id}/stocks')
    _require(sorted(path.stem for path in directory.glob('*.json')) == sorted(codes), 'detail_codes')
    rows, total = [], 0
    for code in sorted(codes):
        detail_raw = _read(_safe_file(directory, f'{code}.json'), min(32 * 1024 * 1024, MAX_TOTAL_RAW - total))
        total += len(detail_raw)
        detail = _json(detail_raw)
        _require(detail.get('code') == code and detail.get('asOf') == market_date, 'detail_date')
        rows.append({'marketDate': market_date, 'code': code, 'metrics': stock_metrics(detail, market_date), 'evidence': detail})
    return {'key': 'published_stock_inputs', 'kind': 'published_stock_inputs', 'market': 'ALL', 'codes': sorted(codes),
            'dates': [market_date], 'unit': 'mixed', 'sourceUrl': 'https://raw.githubusercontent.com/pingpongtech-uskg/stock-web-pages/main/public/data/latest.json',
            'sourceSha256': publication_sha256, 'normalizedFromSha256': None, 'body': {'rows': rows}}, release


def assemble_index(*, data_dir: Path, config: Path, source_cache_dir: Path, market_date: str, request_id: str,
                   source_git_commit: str, actions_run_id: str, publication_sha256: str, config_sha256: str,
                   export_payload_hash: str) -> tuple[dict, dict]:
    source = {'requestId': request_id, 'sourceGitCommit': source_git_commit, 'actionsRunId': actions_run_id}
    stock, release = _published(data_dir, config, market_date, source, publication_sha256, config_sha256, export_payload_hash)
    groups = []
    fragment_paths = [source_cache_dir / f'{name}-receipt-index.json' for name in ['institutional-TWSE', 'institutional-TPEx', 'calendar', 'volume']]
    total = len(canonical(stock['body']))
    for path in fragment_paths:
        metadata = _json(_read(path, 4 * 1024 * 1024))
        _require(isinstance(metadata, dict) and isinstance(metadata.get('groups'), list), 'fragment')
        for group in metadata['groups']:
            _require(isinstance(group, dict), 'fragment')
            total += _safe_file(path.parent, group['bodyFile']).stat().st_size if 'bodyFile' in group else len(canonical(group.get('body')))
            _require(total <= MAX_TOTAL_RAW, 'input_size')
    for path in fragment_paths:
        fragment = load_inputs(path)
        groups.extend(fragment['groups'])
    groups.append(stock)
    _verify_institutional_groups(groups)
    dates = next(group['dates'] for group in groups if group['key'] == 'institutional_normalized:TWSE')
    _require(len(dates) == 11, 'window')
    calendar = next(group['body'] for group in groups if group['key'] == 'calendar_normalized')
    try:
        _require(int(market_date[:4]) in calendar_years(calendar), 'calendar')
        calendar_dates = recent_sessions(calendar, market_date, count=11)
    except (ValueError, TypeError, KeyError) as exc:
        raise MarketCacheError('cache_calendar_window') from exc
    _require(dates == list(reversed(calendar_dates)), 'calendar_window')
    payload = {'marketDate': market_date, 'previousTradingDate': dates[-2], 'generatedAt': release['generatedAt'], 'source': source, 'groups': groups}
    expected = {**{key: value for key, value in payload.items() if key != 'groups'},
                'groups': [{key: value for key, value in group.items() if key != 'body'} for group in groups],
                'sessionDates': dates, 'volumeDates': dates[-7:], 'metricKeys': list(METRIC_KEYS), 'calendarYear': int(market_date[:4])}
    build_market_cache(payload, expected)  # Reject before creating any index output.
    return payload, expected


def write_index(payload: dict, expected: dict, output: Path):
    _require(not output.exists(), 'output_exists')
    files, groups = {}, []
    for group in payload['groups']:
        raw = group['body'] if isinstance(group['body'], bytes) else canonical(group['body'])
        name = group['key'].replace(':', '-') + '.' + sha(raw) + '.json'
        files[name] = raw
        groups.append({**{key: value for key, value in group.items() if key != 'body'}, 'bodyFile': name})
    files['input.json'] = canonical({**payload, 'groups': groups})
    files['expected.json'] = canonical(expected)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f'.{output.name}.', dir=output.parent))
    try:
        for name, content in files.items(): (temporary / name).write_bytes(content)
        _require(not output.exists(), 'output_exists')
        temporary.rename(output)
    finally:
        if temporary.exists(): shutil.rmtree(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['data-dir', 'config', 'source-cache-dir', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ['market-date', 'request-id', 'source-git-commit', 'actions-run-id', 'publication-sha256', 'config-sha256', 'export-payload-hash']:
        parser.add_argument('--' + name, required=True)
    args = vars(parser.parse_args(argv)); output = args.pop('output')
    try:
        payload, expected = assemble_index(**args)
        write_index(payload, expected, output)
    except (MarketCacheError, OSError, ValueError, KeyError, TypeError) as exc:
        print('market_cache_index_failed=' + (str(exc) if isinstance(exc, MarketCacheError) else 'cache_invalid'), file=sys.stderr)
        return 1
    print('market_cache_index_valid')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
