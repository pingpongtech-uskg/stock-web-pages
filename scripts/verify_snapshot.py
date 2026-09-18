#!/usr/bin/env python3
"""Validate a static release without contacting any financial API.

Beyond the v1 key-presence checks this script verifies the contracts the
second product review asked for:

* the published funnel must conserve and match the stock summaries;
* every regression history window must sit inside the fixed 3.5-year frame;
* the manifest must carry a code commit, four formula versions, and a
  rankings hash that reproduces from latest.json.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

RANKING_KEYS = ('trust', 'growth', 'lowPosition', 'lowBase', 'lowBaseGrowth', 'lowBaseQuality')
STRATEGY_FUNNEL_KEYS = ('trust', 'growth', 'lowPosition')
REGRESSION_WINDOW_DAYS = round(365 * 3.5)
WINDOW_START_TOLERANCE_DAYS = 14
WINDOW_END_TOLERANCE_DAYS = 30


def fail(reason: str) -> int:
    print('snapshot_invalid=' + reason)
    return 1


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    data = root / 'public' / 'data'
    latest_path = data / 'latest.json'
    if not latest_path.exists():
        return fail('latest.json missing')
    latest = json.loads(latest_path.read_text(encoding='utf-8'))
    required = {'schemaVersion', 'strategyVersion', 'formulaVersion', 'runId', 'marketDate', 'generatedAt', 'sourceRefs', 'stocks', 'rankings', 'coverage', 'funnel'}
    missing = sorted(required - set(latest))
    if missing:
        return fail('missing:' + ','.join(missing))
    if not isinstance(latest.get('rankings'), dict) or set(latest['rankings']) != set(RANKING_KEYS):
        return fail('ranking_keys')
    if not isinstance(latest.get('formulaVersion'), str) or '3.5y' not in latest['formulaVersion']:
        return fail('formula_version')
    if latest.get('formulaVersion') != 'lohas-linear-3.5y-research-v1':
        return fail('formula_version_mismatch')
    for key in sorted(RANKING_KEYS):
        if not isinstance(latest['rankings'][key], list):
            return fail('ranking_not_list:' + key)
        for row in latest['rankings'][key]:
            if not isinstance(row, dict) or not row.get('code') or row.get('status') not in {'pass', 'fail', 'unknown', 'not_applicable'}:
                return fail('ranking_row:' + key)
            for field in ('currentPeg', 'currentPrice', 'fairPrice', 'valuePrice075', 'valuePrice066'):
                if field in row and row[field] is not None and not is_number(row[field]):
                    return fail(f'ranking_row_{field}:{key}')
            if 'currentPeg' in row and is_number(row['currentPeg']):
                if not is_number(row.get('fairPrice')) or not is_number(row.get('currentPrice')):
                    return fail('ranking_row_valuation_missing:' + key)

    coverage = latest.get('coverage')
    if not isinstance(coverage, dict):
        return fail('coverage_type')
    completeness = coverage.get('completenessPct')
    if completeness is not None and not is_number(completeness):
        return fail('coverage_completeness_type')

    funnel = latest.get('funnel')
    if not isinstance(funnel, dict):
        return fail('funnel_type')
    if not isinstance(funnel.get('version'), str) or not funnel['version']:
        return fail('funnel_version')
    for key in ('universe', 'priceComplete', 'valuationComplete', 'pegCandidates', 'formalValuations', 'proxyValuations', 'instrumentExcluded'):
        if not is_number(funnel.get(key)):
            return fail('funnel_field:' + key)
    counts = funnel.get('strategyCandidates')
    if not isinstance(counts, dict) or any(not is_number(counts.get(key)) for key in STRATEGY_FUNNEL_KEYS):
        return fail('funnel_strategy_counts')
    if funnel['pegCandidates'] > funnel['valuationComplete']:
        return fail('funnel_conservation_peg')
    if any(counts[key] > funnel['pegCandidates'] for key in STRATEGY_FUNNEL_KEYS):
        return fail('funnel_conservation_strategy')
    if funnel['formalValuations'] + funnel['proxyValuations'] != funnel['valuationComplete']:
        return fail('funnel_conservation_evidence')
    if funnel['universe'] != coverage.get('universeCount') or funnel['priceComplete'] != coverage.get('priceCompleteCount'):
        return fail('funnel_coverage_mismatch')
    stocks = latest.get('stocks')
    if not isinstance(stocks, list):
        return fail('stocks_type')
    summary_valuations = [stock.get('valuation') for stock in stocks if isinstance(stock.get('valuation'), dict)]
    if len(summary_valuations) != funnel['valuationComplete']:
        return fail('funnel_valuation_mismatch')
    below_count = sum(1 for value in summary_valuations if value.get('below_075'))
    if below_count != funnel['pegCandidates']:
        return fail('funnel_peg_mismatch')

    run_id = latest['runId']
    release_dir = data / 'releases' / run_id
    if not (release_dir / 'manifest.json').exists():
        return fail('manifest_missing')
    manifest = json.loads((release_dir / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('runId') != run_id:
        return fail('manifest_run_mismatch')
    code_commit = manifest.get('codeCommit')
    if not isinstance(code_commit, str) or not re.fullmatch(r'[0-9a-f]{7,64}', code_commit):
        return fail('manifest_code_commit')
    formula_versions = manifest.get('formulaVersions')
    if not isinstance(formula_versions, dict) or set(formula_versions) != {'regression', 'valuation', 'growthFallback', 'ranking'}:
        return fail('manifest_formula_versions')
    if any(not isinstance(value, str) or not value for value in formula_versions.values()):
        return fail('manifest_formula_versions_empty')
    rankings_hash = manifest.get('rankingsHash')
    recomputed = hashlib.sha256(json.dumps(latest['rankings'], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if rankings_hash != recomputed:
        return fail('manifest_rankings_hash')

    market_date = latest.get('marketDate')
    try:
        market_end = date.fromisoformat(str(market_date)[:10])
    except (TypeError, ValueError):
        return fail('market_date')
    window_start = market_end - timedelta(days=REGRESSION_WINDOW_DAYS)
    earliest_start = window_start - timedelta(days=WINDOW_START_TOLERANCE_DAYS)
    latest_end = market_end + timedelta(days=WINDOW_END_TOLERANCE_DAYS)
    codes = [str(stock.get('code', '')) for stock in stocks]
    if any(not re.fullmatch(r'[0-9A-Z-]+', code) for code in codes):
        return fail('bad_code')
    detail_count = 0
    for code in codes:
        detail_path = release_dir / 'stocks' / f'{code}.json'
        if not detail_path.exists():
            return fail('detail_missing:' + code)
        detail = json.loads(detail_path.read_text(encoding='utf-8'))
        if detail.get('code') != code or detail.get('runId') not in (None, run_id):
            return fail('detail_mismatch:' + code)
        regression = detail.get('regression')
        if isinstance(regression, dict):
            history_start = regression.get('historyStart')
            history_end = regression.get('historyEnd')
            if history_start is not None:
                try:
                    start_day = date.fromisoformat(str(history_start)[:10])
                except (TypeError, ValueError):
                    return fail('regression_start_unparsed:' + code)
                # A history that reaches further back than the fixed window
                # (the v2 "3.5y label on 4y data" bug) is rejected here.
                if start_day < earliest_start or start_day > window_start + timedelta(days=WINDOW_END_TOLERANCE_DAYS):
                    return fail('regression_window_start:' + code)
            if history_end is not None:
                try:
                    end_day = date.fromisoformat(str(history_end)[:10])
                except (TypeError, ValueError):
                    return fail('regression_end_unparsed:' + code)
                if end_day < market_end - timedelta(days=WINDOW_END_TOLERANCE_DAYS) or end_day > latest_end:
                    return fail('regression_window_end:' + code)
        detail_count += 1
    print(json.dumps({'valid': True, 'run_id': run_id, 'stocks': len(codes), 'details': detail_count, 'market_date': market_date, 'funnel': funnel}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
