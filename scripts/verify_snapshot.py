#!/usr/bin/env python3
"""Validate a static release without contacting any financial API.

Beyond the v1 key-presence checks this script verifies the contracts the
second product review asked for:

* the published funnel must conserve and match the stock summaries;
* every regression history window must sit inside the fixed 3.5-year frame;
* the manifest must carry a code commit, four formula versions, and hashes
  for both the input details and rankings;
* every parsed JSON number must be finite and every regression object must
  satisfy its complete fail-closed contract.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.release_contract import chip_reference_error

RANKING_KEYS = ('trust', 'growth', 'lowPosition', 'lowBase', 'lowBaseGrowth', 'lowBaseQuality')
STRATEGY_FUNNEL_KEYS = ('trust', 'growth', 'lowPosition')
REGRESSION_WINDOW_DAYS = round(365 * 3.5)
WINDOW_START_TOLERANCE_DAYS = 14
WINDOW_END_TOLERANCE_DAYS = 30


def fail(reason: str) -> int:
    print('snapshot_invalid=' + reason)
    return 1


def is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def first_non_finite_path(value: object, path: str = "") -> str | None:
    """Locate the first JSON numeric value that is NaN or infinite."""

    if isinstance(value, float) and not math.isfinite(value):
        return path or "$"
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = first_non_finite_path(child, f"{path}.{key}" if path else str(key))
            if child_path:
                return child_path
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = first_non_finite_path(child, f"{path}[{index}]")
            if child_path:
                return child_path
    return None


def compute_input_hash(
    manifest: dict[str, object],
    latest: dict[str, object],
    details: list[dict[str, object]],
) -> str:
    """Reproduce refresh_snapshot.py's canonical input digest."""

    raw_codes = manifest.get("inputCodes", [])
    input_codes = [str(code) for code in raw_codes] if isinstance(raw_codes, list) else []
    canonical = json.dumps(
        {
            "baselineRunId": manifest.get("baselineRunId"),
            "codes": input_codes,
            "details": details,
            "marketDate": latest.get("marketDate"),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def input_hash_error(
    manifest: dict[str, object],
    latest: dict[str, object],
    details: list[dict[str, object]],
) -> str | None:
    if manifest.get("inputHash") != compute_input_hash(manifest, latest, details):
        return "manifest_input_hash"
    return None


def regression_contract_error(
    regression: object,
    code: str,
    market_end: date,
) -> str | None:
    """Return a fail-closed regression contract error, if any."""

    if not isinstance(regression, dict):
        return "regression_missing:" + code
    basis = regression.get("priceBasis")
    if basis not in {"adjusted", "raw_proxy", "unknown", None}:
        return "regression_price_basis:" + code

    if basis == "adjusted":
        required = ("historyStart", "historyEnd", "observations", "expectedObservations", "coveragePct", "signalEligible")
        for key in required:
            if key not in regression or regression[key] is None:
                return f"regression_field_missing:{key}:{code}"
        observations = regression.get("observations")
        expected = regression.get("expectedObservations")
        if not is_number(observations) or not is_number(expected):
            return "regression_observations_type:" + code
        observations_value = float(str(observations))
        expected_value = float(str(expected))
        if (
            int(observations_value) != observations_value
            or int(expected_value) != expected_value
            or int(expected_value) <= 0
        ):
            return "regression_observations_type:" + code
        if int(observations_value) != int(expected_value):
            return "regression_observations_mismatch:" + code
        coverage = regression.get("coveragePct")
        if not is_number(coverage):
            return "regression_coverage:" + code
        if float(str(coverage)) < 95:
            return "regression_coverage:" + code
        if not isinstance(regression.get("signalEligible"), bool):
            return "regression_signal_eligible_type:" + code

    window_start = market_end - timedelta(days=REGRESSION_WINDOW_DAYS)
    earliest_start = window_start - timedelta(days=WINDOW_START_TOLERANCE_DAYS)
    latest_end = market_end + timedelta(days=WINDOW_END_TOLERANCE_DAYS)
    history_start = regression.get("historyStart")
    if history_start is not None:
        try:
            start_day = date.fromisoformat(str(history_start)[:10])
        except (TypeError, ValueError):
            return "regression_start_unparsed:" + code
        if start_day < earliest_start or start_day > window_start + timedelta(days=WINDOW_END_TOLERANCE_DAYS):
            return "regression_window_start:" + code
    elif basis == "adjusted":
        return "regression_field_missing:historyStart:" + code

    history_end = regression.get("historyEnd")
    if history_end is not None:
        try:
            end_day = date.fromisoformat(str(history_end)[:10])
        except (TypeError, ValueError):
            return "regression_end_unparsed:" + code
        if end_day < market_end - timedelta(days=WINDOW_END_TOLERANCE_DAYS) or end_day > latest_end:
            return "regression_window_end:" + code
    elif basis == "adjusted":
        return "regression_field_missing:historyEnd:" + code
    return None


def ranking_valuation_error(row: object, key: str) -> str | None:
    """Reject partial numeric valuation payloads without a valuation object."""
    if not isinstance(row, dict):
        return "ranking_row:" + key
    fields = ("currentPeg", "currentPrice", "fairPrice", "valuePrice075", "valuePrice066")
    if not any(row.get(field) is not None for field in fields):
        return None
    # A price/recovery observation may carry only the current price while PEG
    # evidence is unavailable.  Fair/value-band numbers without PEG remain a
    # partial valuation and must fail closed.
    if row.get("currentPeg") is None:
        if any(row.get(field) is not None for field in ("fairPrice", "valuePrice075", "valuePrice066")):
            return "ranking_row_valuation_partial:" + key
        return None
    if any(not is_number(row.get(field)) for field in ("currentPeg", "currentPrice", "fairPrice")):
        return "ranking_row_valuation_partial:" + key
    return None


def main(root: Path | None = None) -> int:
    root = root or Path(__file__).resolve().parents[1]
    data = root / 'public' / 'data'
    latest_path = data / 'latest.json'
    if not latest_path.exists():
        return fail('latest.json missing')
    latest = json.loads(latest_path.read_text(encoding='utf-8'))
    non_finite = first_non_finite_path(latest)
    if non_finite:
        return fail('non_finite:latest.' + non_finite)
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
            chip_error = chip_reference_error(row.get("chipReference"), str(row.get("code")))
            if chip_error:
                return fail(chip_error)
            for field in ('currentPeg', 'currentPrice', 'fairPrice', 'valuePrice075', 'valuePrice066'):
                if field in row and row[field] is not None and not is_number(row[field]):
                    return fail(f'ranking_row_{field}:{key}')
            valuation_error = ranking_valuation_error(row, key)
            if valuation_error:
                return fail(valuation_error)
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
    if counts["growth"] > funnel['pegCandidates']:
        return fail('funnel_conservation_growth')
    if funnel['formalValuations'] + funnel['proxyValuations'] != funnel['valuationComplete']:
        return fail('funnel_conservation_evidence')
    if funnel['universe'] != coverage.get('universeCount') or funnel['priceComplete'] != coverage.get('priceCompleteCount'):
        return fail('funnel_coverage_mismatch')
    stocks = latest.get('stocks')
    if not isinstance(stocks, list):
        return fail('stocks_type')
    for stock in stocks:
        if not isinstance(stock, dict) or not stock.get('code'):
            return fail('stock_row')
        chip_error = chip_reference_error(stock.get("chipReference"), str(stock.get("code")))
        if chip_error:
            return fail(chip_error)
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
    non_finite = first_non_finite_path(manifest)
    if non_finite:
        return fail('non_finite:manifest.' + non_finite)
    if manifest.get('runId') != run_id:
        return fail('manifest_run_mismatch')
    code_commit = manifest.get('codeCommit')
    if not isinstance(code_commit, str) or not re.fullmatch(r'[0-9a-f]{7,64}', code_commit):
        return fail('manifest_code_commit')
    formula_versions = manifest.get('formulaVersions')
    if not isinstance(formula_versions, dict) or set(formula_versions) != {'regression', 'valuation', 'growthValuation', 'growthFallback', 'ranking'}:
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
    codes = [str(stock.get('code', '')) for stock in stocks]
    if any(not re.fullmatch(r'[0-9A-Z-]+', code) for code in codes):
        return fail('bad_code')
    detail_count = 0
    detail_documents: list[dict[str, object]] = []
    for code in codes:
        detail_path = release_dir / 'stocks' / f'{code}.json'
        if not detail_path.exists():
            return fail('detail_missing:' + code)
        detail = json.loads(detail_path.read_text(encoding='utf-8'))
        non_finite = first_non_finite_path(detail)
        if non_finite:
            return fail('non_finite:detail.' + code + '.' + non_finite)
        if detail.get('code') != code or detail.get('runId') not in (None, run_id):
            return fail('detail_mismatch:' + code)
        error = regression_contract_error(detail.get('regression'), code, market_end)
        if error:
            return fail(error)
        detail_documents.append(detail)
        detail_count += 1
    hash_error = input_hash_error(manifest, latest, detail_documents)
    if hash_error:
        return fail(hash_error)
    print(json.dumps({'valid': True, 'run_id': run_id, 'stocks': len(codes), 'details': detail_count, 'market_date': market_date, 'funnel': funnel}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
