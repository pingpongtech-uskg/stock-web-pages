"""Compact screening interchange shared by the website archive and n8n."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from typing import Any

from pipeline.release_contract import common_share_universe, growth_coverage_error
from pipeline.history_archive import STRATEGIES, canonical_json_bytes

SCHEMA_VERSION = 'screening-export-v1'
HASH_SUFFIX = re.compile(rb',"payloadHash":"([0-9a-f]{64})"}$')
METRICS = {
    'currentPrice': ('lastPrice', 'currentPrice'), 'zScore': ('zScore',), 'slope': ('slope',),
    'currentPeg': ('currentPeg',), 'growthTotalReturnPe': ('growthTotalReturnPe',),
    'growthFairPrice': ('growthFairPrice',), 'growthBuyZonePrice': ('growthBuyZonePrice',),
    'growthHealthPassCount': ('growthHealthPassCount',), 'institutionNetShares10': ('institutionNetShares10',),
    'participation10': ('participation10',),
}


def formula_versions(release: dict[str, Any]) -> dict[str, str]:
    supplied = release.get('formulaVersions') or {}
    result = {str(key): str(value) for key, value in supplied.items() if value}
    if release.get('formulaVersion'):
        result.setdefault('regression', str(release['formulaVersion']))
    for stock in release.get('stocks', []):
        for field, key in [('valuation', 'valuation'), ('growthValuation', 'growthValuation')]:
            version = (stock.get(field) or {}).get('formula_version')
            if version:
                result.setdefault(key, str(version))
    result.setdefault('ranking', str(release.get('strategyVersion') or 'legacy-unspecified'))
    return result


def _body(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != 'payloadHash'}


def export_bytes(value: dict[str, Any]) -> bytes:
    """Hash goes last so consumers hash exact bytes without reserializing floats."""
    body = canonical_json_bytes(_body(value))
    return body[:-1] + b',"payloadHash":"' + str(value['payloadHash']).encode('ascii') + b'"}'


def hash_preimage(raw: bytes) -> bytes:
    match = HASH_SUFFIX.search(raw)
    if not match:
        raise ValueError('screening export hash suffix missing')
    return raw[:match.start()] + b'}'


def _metric_origins(stock: dict[str, Any], day: str) -> dict[str, Any]:
    growth = stock.get('growthValuation') or {}
    origins = {**(growth.get('inputAudit') or stock.get('financialInputOrigins') or stock.get('inputOrigins') or {})}
    aliases = {'currentPrice': 'price', 'currentPe': 'pe'}
    for target, source in aliases.items():
        if source in origins:
            origins[target] = origins[source]
    regression = stock.get('regression') or {}
    price_period = f'{regression.get("historyStart", "unknown")}..{regression.get("historyEnd", "unknown")}'
    for key in ('zScore', 'slope'):
        origins[key] = {'origin': 'derived' if regression.get('priceBasis') == 'adjusted' else 'proxy', 'sourcePeriod': price_period,
            'method': regression.get('method', 'unknown'), 'source': regression.get('sourceRefs', [])}
    valuation = stock.get('valuation') or {}
    origins['currentPeg'] = {'origin': 'proxy' if 'proxy' in str(valuation.get('growth_method')) else 'derived',
        'sourcePeriod': valuation.get('growth_years') or 'unknown',
        'method': valuation.get('formula_version', 'unknown'), 'source': stock.get('sourceRefs', [])}
    daily = stock.get('institutionalDaily') or []
    dates = sorted(str(row['date']) for row in daily if isinstance(row, dict) and row.get('date'))
    source = sorted({str(row.get('source')) for row in daily if isinstance(row, dict) and row.get('source')})
    for key in ('institutionNetShares10', 'participation10'):
        origins[key] = {'origin': 'derived', 'sourcePeriod': f'{dates[0]}..{dates[-1]}' if dates else 'unknown',
            'method': 'ten-market-session-sum' if key == 'institutionNetShares10' else 'ten-market-session-net-over-volume',
            'source': source}
    origins['growthHealthPassCount'] = {'origin': 'derived', 'sourcePeriod': day,
        'method': 'growth-health-v1', 'source': stock.get('sourceRefs', [])}
    earnings_period = (origins.get('earningsGrowth') or {}).get('sourcePeriod') or sorted(str(year) for year in (growth.get('annual_eps') or {})) or 'unknown'
    for key in ('growthTotalReturnPe', 'growthFairPrice', 'growthBuyZonePrice', 'growthYears', 'growthValidYears'):
        origins[key] = {'origin': 'derived', 'sourcePeriod': earnings_period,
            'method': growth.get('formula_version', 'unknown'), 'source': stock.get('sourceRefs', [])}
    return origins


def _stock_projection(stock: dict[str, Any], row: dict[str, Any], day: str, source_refs: list[str]) -> dict[str, Any]:
    metrics = {key: next((stock[k] for k in fields if k in stock), None) for key, fields in METRICS.items()}
    growth = stock.get('growthValuation') or {}
    valuation = stock.get('valuation') or {}
    nested_metrics = {'currentPe': 'current_pe', 'ttmEps': 'ttm_eps', 'earningsGrowth': 'earnings_growth',
        'growthMethod': 'growth_method', 'dividendYield': 'dividend_yield',
        'growthTotalReturnPe': 'total_return_pe', 'growthFairPrice': 'fair_price',
        'growthBuyZonePrice': 'buy_zone_price', 'growthYears': 'growth_years',
        'growthValidYears': 'growth_valid_years'}
    for key, field in nested_metrics.items():
        if field in growth:
            metrics[key] = growth[field]
    metrics.setdefault('currentPe', valuation.get('current_pe'))
    if metrics['currentPeg'] is None:
        metrics['currentPeg'] = valuation.get('current_peg')
    inputs = {**(stock.get('financialInputs') or {}), **(stock.get('healthInputs') or {})}
    origins = _metric_origins(stock, day)
    origins = {**{key: {'origin': 'unavailable', 'sourcePeriod': 'unknown', 'method': 'unknown', 'source': []} for key in metrics}, **origins}
    origins = {key: {**item, 'origin': 'unavailable'} if key in metrics and metrics[key] is None else item for key, item in origins.items()}
    periods = {key: [{field: row[field] for field in ('year', 'quarter', 'periodEnd', 'availableAt', 'source', 'sourceRefs', 'basis', 'inputOrigin', 'derivationMethod', 'periodType') if field in row}
               for row in value[-8:] if isinstance(row, dict)]
               for key, value in inputs.items() if isinstance(value, list) and key in {'incomeQuarterly', 'balanceQuarterly', 'cashflowAnnual', 'cashFlowAnnual', 'dividends', 'monthlyRevenue', 'monthlyRevenueOfficial', 'monthlyRevenueYoy', 'cashflowQuarterly', 'incomeYtd'}}
    return {'code': row['code'], 'name': str(stock.get('name') or row.get('name') or ''),
            'sector': str(stock.get('sector') or row.get('sector') or ''), 'metrics': metrics, 'strategies': [],
            'provenance': {'marketDate': day, 'sourceRefs': stock.get('sourceRefs') or source_refs,
                'dataStatus': stock.get('dataStatus', 'unknown'), 'market': stock.get('market', 'unknown'),
                'inputPeriods': periods, 'inputOrigins': origins,
                'financialCutoff': stock.get('financialCutoff') or stock.get('financialAvailableAt'),
                'valuationEvidenceLevel': stock.get('valuationEvidenceLevel', 'unknown'),
                'missingReasons': growth.get('missingReasons', []), 'inputsComplete': growth.get('inputsComplete', False),
                'regressionEvidence': {key: (stock.get('regression') or {}).get(key) for key in ('status', 'priceBasis', 'signalEligible', 'historyStart', 'historyEnd')}}}


def build_export(release: dict[str, Any], *, request_id: str, source_git_commit: str,
                 actions_run_id: str, legacy: bool = False, details: dict[str, Any] | None = None) -> dict[str, Any]:
    day = release.get('marketDate')
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError('exact marketDate required')
    if not release.get('runId') or not request_id or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,160}', request_id):
        raise ValueError('runId and safe requestId required')
    if not legacy and (release.get('freshness') not in {'current', 'degraded'} or
                       (release.get('coverage') or {}).get('universeStale')):
        raise ValueError('stale release cannot be exported')
    if not legacy and (not re.fullmatch(r'[0-9a-f]{40}', source_git_commit) or not actions_run_id.isdigit()):
        raise ValueError('verified Git and Actions lineage required')
    funnel = release.get('funnel')
    coverage_error = growth_coverage_error(
        funnel,
        required=not legacy,
        expected_universe=common_share_universe(funnel) if not legacy else None,
    )
    if coverage_error:
        raise ValueError(coverage_error)
    stocks = {str(stock['code']): stock for stock in release.get('stocks', [])}
    strategies: dict[str, list[dict[str, Any]]] = {}
    selected: dict[str, dict[str, Any]] = {}
    for strategy in STRATEGIES:
        rows = (release.get('rankings') or {}).get(strategy, [])
        if not isinstance(rows, list):
            raise ValueError('strategy list required')
        codes: set[str] = set(); ranks: set[int] = set(); entries = []
        for position, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError('strategy row object required')
            code = str(row.get('code') or ''); rank = row.get('rank', position)
            if not isinstance(rank, int) or isinstance(rank, bool):
                raise ValueError('strategy rank must be an integer')
            if not code or code in codes or rank in ranks or rank < 1:
                raise ValueError('strategy codes and ranks must be unique')
            if code not in stocks:
                raise ValueError('selected stock missing summary')
            codes.add(code); ranks.add(rank); entries.append({'code': code, 'rank': rank})
            stock = {**stocks[code], **(details or {}).get(code, {})}
            item = selected.setdefault(code, _stock_projection(stock, row, day, release.get('sourceRefs', [])))
            item['strategies'].append({'strategy': strategy, 'rank': rank, 'status': row.get('status', 'unknown'),
                                      'reason': str(row.get('reason') or '')})
        strategies[strategy] = sorted(entries, key=lambda row: row['rank'])
    value = {'schemaVersion': SCHEMA_VERSION, 'marketDate': day, 'generatedAt': str(release.get('generatedAt') or ''),
        'runId': str(release['runId']), 'requestId': request_id, 'sourceGitCommit': source_git_commit,
        'actionsRunId': actions_run_id, 'formulaVersions': formula_versions(release),
        'freshness': release.get('freshness', 'degraded'), 'legacy': legacy,
        'coverage': release.get('coverage', {}), 'funnel': funnel or {},
        'strategies': strategies, 'selectedStocks': [selected[code] for code in sorted(selected)]}
    canonical_json_bytes(value)  # Reject NaN/Infinity before hashing.
    value['revision'] = hashlib.sha256(canonical_json_bytes(value)).hexdigest()[:12]
    value['payloadHash'] = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return value


def validate_export(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ['export_object']
    errors = []
    for key in ('generatedAt', 'runId', 'requestId', 'sourceGitCommit', 'actionsRunId'):
        if not isinstance(value.get(key), str) or not value[key]:
            errors.append('required_string:' + key)
    try:
        generated = datetime.fromisoformat(str(value.get('generatedAt')))
        if generated.tzinfo is None: raise ValueError('timezone missing')
    except ValueError:
        errors.append('generated_at')
    if not isinstance(value.get('requestId'), str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', value.get('requestId', '')):
        errors.append('request_id')
    if not value.get('legacy') and (not isinstance(value.get('sourceGitCommit'), str) or
        not re.fullmatch(r'[0-9a-f]{40}', value.get('sourceGitCommit', '')) or
        not isinstance(value.get('actionsRunId'), str) or not value.get('actionsRunId', '').isdigit()):
        errors.append('publication_lineage')
    if value.get('schemaVersion') != SCHEMA_VERSION:
        errors.append('schema_version')
    body = _body(value)
    try:
        canonical_json_bytes(body)
    except (ValueError, TypeError):
        return [*errors, 'non_json_value']
    if hashlib.sha256(canonical_json_bytes(body)).hexdigest() != value.get('payloadHash'):
        errors.append('payload_hash_mismatch')
    revision_body = {key: item for key, item in body.items() if key != 'revision'}
    if hashlib.sha256(canonical_json_bytes(revision_body)).hexdigest()[:12] != value.get('revision'):
        errors.append('revision_mismatch')
    try:
        if date.fromisoformat(str(value.get('marketDate'))).isoformat() != value.get('marketDate'):
            errors.append('market_date')
    except ValueError:
        errors.append('market_date')
    stocks = value.get('selectedStocks', [])
    if not isinstance(stocks, list):
        return [*errors, 'selected_stocks']
    if any(not isinstance(stock, dict) or not isinstance(stock.get('code'), str) or not stock['code'] or
           not isinstance(stock.get('strategies'), list) or not isinstance(stock.get('metrics'), dict) or
           not isinstance(stock.get('provenance'), dict) for stock in stocks):
        return [*errors, 'selected_stock_shape']
    codes = [stock.get('code') for stock in stocks]
    if len(codes) != len(stocks) or len(codes) != len(set(codes)):
        errors.append('selected_stock_duplicates')
    strategies = value.get('strategies') or {}
    if not isinstance(strategies, dict):
        return [*errors, 'strategies']
    if set(strategies) != set(STRATEGIES):
        errors.append('strategies')
    for strategy in STRATEGIES:
        rows = strategies.get(strategy, [])
        if not isinstance(rows, list):
            errors.append('strategy_rows'); continue
        if any(not isinstance(row, dict) or not isinstance(row.get('code'), str) or
               not isinstance(row.get('rank'), int) or isinstance(row['rank'], bool) or row['rank'] < 1 for row in rows):
            errors.append('strategy_row_shape:' + strategy); continue
        if any(not isinstance(entry, dict) or not isinstance(entry.get('rank'), int) or
               entry.get('strategy') not in STRATEGIES or not isinstance(entry.get('reason'), str) or
               not isinstance(entry.get('status'), str) for stock in stocks for entry in stock['strategies']):
            errors.append('membership_shape'); continue
        expected = {(row.get('code'), row.get('rank')) for row in rows}
        actual = {(stock.get('code'), entry.get('rank')) for stock in stocks
                  for entry in stock.get('strategies', []) if entry.get('strategy') == strategy}
        if expected != actual or len(expected) != len(rows) or len({row['rank'] for row in rows}) != len(rows):
            errors.append('strategy_membership:' + strategy)
    selected_codes = {row['code'] for rows in strategies.values() if isinstance(rows, list) for row in rows if isinstance(row, dict) and isinstance(row.get('code'), str)}
    if set(codes) != selected_codes:
        errors.append('selected_stock_union')
    if not isinstance(value.get('coverage'), dict) or not isinstance(value.get('formulaVersions'), dict):
        return [*errors, 'metadata_shape']
    funnel = value.get('funnel')
    coverage_error = growth_coverage_error(
        funnel,
        required=not value.get('legacy'),
        expected_universe=common_share_universe(funnel) if not value.get('legacy') else None,
    )
    if coverage_error:
        errors.append(coverage_error)
    if not value.get('legacy') and (value.get('freshness') not in {'current', 'degraded'} or
                                    (value.get('coverage') or {}).get('universeStale')):
        errors.append('stale_export')
    return errors
