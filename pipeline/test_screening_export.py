import copy
import hashlib
import json
import pytest
from pipeline.screening_export import build_export, export_bytes, validate_export, hash_preimage


def release():
    return {'marketDate': '2026-10-02', 'generatedAt': '2026-10-02T10:00:00Z', 'runId': 'run-1',
            'formulaVersion': 'regression-v1', 'freshness': 'current', 'sourceRefs': ['official'],
            'coverage': {'universeCount': 2}, 'funnel': {
                'version': 'funnel-v2-independent-trust-low-position',
                'universe': 2, 'instrumentExcluded': 0, 'pegCandidates': 0,
                'growthCandidates': 1, 'strategyCandidates': {'trust': 1, 'growth': 1, 'lowPosition': 0},
                'growthCoverageVersion': 'growth-coverage-v1',
                'growthEvaluationState': 'partial', 'growthInputComplete': 1,
                'growthValuationComplete': 1, 'growthThresholdCandidates': 1,
                'growthHealthCandidates': 1, 'growthMissingReasons': [],
                'growthTerminalOutcomes': {'universe': 2, 'missing': 1, 'knownInvalid': 0,
                    'extreme': 0, 'belowThreshold': 0, 'healthBlocked': 0, 'selected': 1},
            },
            'stocks': [{'code': '2330', 'name': '台積電', 'lastPrice': 100.0, 'zScore': -1.2}],
            'rankings': {'trust': [{'code': '2330', 'rank': 1, 'reason': 'pass', 'status': 'pass'}],
                         'growth': [{'code': '2330', 'rank': 1, 'reason': 'growth', 'status': 'pass'}], 'lowPosition': []}}


def test_export_deduplicates_and_preserves_strategy_reason_and_versions():
    source = release(); before = copy.deepcopy(source)
    value = build_export(source, request_id='request-1', source_git_commit='a'*40, actions_run_id='123')
    assert source == before
    assert len(value['selectedStocks']) == 1
    assert len(value['selectedStocks'][0]['strategies']) == 2
    assert value['formulaVersions']['regression'] == 'regression-v1'
    assert value['selectedStocks'][0]['metrics']['currentPrice'] == 100
    assert validate_export(value) == []


def test_hash_can_be_verified_from_raw_without_float_reserialization():
    value = build_export(release(), request_id='request-1', source_git_commit='a'*40, actions_run_id='123')
    raw = export_bytes(value)
    assert json.loads(raw) == value
    assert hashlib.sha256(hash_preimage(raw)).hexdigest() == value['payloadHash']
    changed = {**value, 'requestId': 'altered'}
    assert 'payload_hash_mismatch' in validate_export(changed)


@pytest.mark.parametrize('changes', [{'marketDate': None}, {'runId': ''}, {'freshness': 'stale'}, {'coverage': {'universeStale': True}}])
def test_export_rejects_invalid_or_stale_release(changes):
    with pytest.raises(ValueError):
        build_export({**release(), **changes}, request_id='request-1', source_git_commit='a'*40, actions_run_id='123')


def test_nonlegacy_export_requires_complete_growth_coverage_but_legacy_remains_compatible():
    old = release()
    old['funnel'] = {'version': 'funnel-v2-independent-trust-low-position', 'universe': 2, 'growthCandidates': 1}
    with pytest.raises(ValueError, match='growth_coverage_required'):
        build_export(old, request_id='request-1', source_git_commit='a'*40, actions_run_id='123')

    exported = build_export(old, request_id='legacy-request', source_git_commit='legacy', actions_run_id='legacy', legacy=True)
    assert validate_export(exported) == []
    assert 'growthCoverageVersion' not in exported['funnel']


def test_growth_candidate_can_exceed_peg_pool_and_malformed_coverage_blocks_export():
    source = release()
    source['funnel']['pegCandidates'] = 0
    value = build_export(source, request_id='x', source_git_commit='a'*40, actions_run_id='1')
    assert value['funnel']['growthCandidates'] == 1
    assert validate_export(value) == []

    broken = {**source, 'funnel': {**source['funnel'], 'growthInputComplete': -1}}
    with pytest.raises(ValueError, match='growth_coverage_count:growthInputComplete'):
        build_export(broken, request_id='x', source_git_commit='a'*40, actions_run_id='1')


def test_duplicate_rank_and_missing_stock_block_export():
    source = release(); source['rankings']['trust'].append({'code': '2330', 'rank': 2})
    with pytest.raises(ValueError):
        build_export(source, request_id='x', source_git_commit='a'*40, actions_run_id='1')
    source = release(); source['stocks'] = []
    with pytest.raises(ValueError):
        build_export(source, request_id='x', source_git_commit='a'*40, actions_run_id='1')


def test_nested_growth_metrics_and_input_provenance_are_exported():
    details = {'2330': {'growthValuation': {'current_pe': 12, 'ttm_eps': 8.5,
        'earnings_growth': 0.2, 'dividend_yield': 0.03, 'growth_years': [2022,2023,2024,2025]},
        'financialInputs': {'incomeQuarterly': [{'year':2025,'quarter':4,'availableAt':'2026-03-20','source':'TWSE'}]}}}
    value = build_export(release(), request_id='x', source_git_commit='a'*40, actions_run_id='1', details=details)
    stock = value['selectedStocks'][0]
    assert stock['metrics']['earningsGrowth'] == 0.2
    assert stock['metrics']['dividendYield'] == 0.03
    assert stock['provenance']['inputPeriods']['incomeQuarterly'][0]['source'] == 'TWSE'


@pytest.mark.parametrize('value', [None, [], {'selectedStocks':[None]}, {'selectedStocks':None},
    {'selectedStocks':[], 'strategies': []}, {'selectedStocks':[], 'strategies': {'trust':[None]}},
    {'selectedStocks':[{'code':[]}]}, {'metric': float('nan')}])
def test_malformed_export_reports_errors_without_throwing(value):
    assert validate_export(value)


def test_nonfinite_metrics_and_invalid_git_lineage_rejected():
    source = release(); source['stocks'][0]['lastPrice'] = float('inf')
    with pytest.raises(ValueError): build_export(source,request_id='x',source_git_commit='a'*40,actions_run_id='1')
    with pytest.raises(ValueError): build_export(release(),request_id='x',source_git_commit='wrong',actions_run_id='1')
    with pytest.raises(ValueError): hash_preimage(b'{}')


def test_projection_into_history_uses_same_deduplicated_export():
    from pipeline.history_archive import project_export_to_history
    value = build_export(release(),request_id='x',source_git_commit='a'*40,actions_run_id='1')
    record = project_export_to_history(value)
    assert record['payloadHash'] == value['payloadHash']
    assert record['selectedStocks'] == value['selectedStocks']
    assert record['strategies']['growth'][0]['reason'] == 'growth'
    with pytest.raises(ValueError): project_export_to_history({**value,'requestId':'changed'})


def test_real_normalized_health_periods_and_nonvaluation_metric_origins():
    detail = {'healthInputs': {'incomeQuarterly':[{'year':2025,'quarter':4,'source':'FinMind','inputOrigin':'reported'}]},
              'regression':{'historyStart':'2023-04-02','historyEnd':'2026-10-02','method':'regression-v1','priceBasis':'adjusted','sourceRefs':['adjusted-price']},
              'institutionalDaily':[{'date':'2026-10-02','source':'official-institution'}],
              'growthValuation':{'inputAudit':{'price':{'origin':'reported','source':'TWSE','sourcePeriod':'2026-10-02'}}}}
    value=build_export(release(),request_id='x',source_git_commit='a'*40,actions_run_id='1',details={'2330':detail})
    provenance=value['selectedStocks'][0]['provenance']
    assert provenance['inputPeriods']['incomeQuarterly'][0]['source']=='FinMind'
    assert provenance['inputOrigins']['currentPrice']['source']=='TWSE'
    assert provenance['inputOrigins']['zScore']['source']==['adjusted-price']
    assert provenance['inputOrigins']['institutionNetShares10']['source']==['official-institution']


def test_missing_metric_origin_and_extra_unselected_stock_are_rejected():
    value=build_export(release(),request_id='x',source_git_commit='a'*40,actions_run_id='1')
    stock=value['selectedStocks'][0]
    assert stock['metrics']['currentPeg'] is None
    assert stock['provenance']['inputOrigins']['currentPeg']['origin']=='unavailable'
    changed={**value,'selectedStocks':[*value['selectedStocks'],{**stock,'code':'extra','strategies':[]}]}
    assert 'selected_stock_union' in validate_export(changed)


def test_export_optional_chip_is_exact_immutable_and_hash_bound():
    from pipeline.ownership_checks import evaluate_chip_reference
    source = release()
    chip = evaluate_chip_reference([], data_freshness='unavailable', evaluation_date='2026-10-02')
    before = copy.deepcopy(chip)
    plain = build_export(source, request_id='chip', source_git_commit='a'*40, actions_run_id='1')
    value = build_export(source, request_id='chip', source_git_commit='a'*40, actions_run_id='1', details={'2330': {'chipReference': chip}})
    selected = value['selectedStocks'][0]
    assert selected['chipReference'] == before
    assert validate_export(value) == []
    assert value['payloadHash'] != plain['payloadHash'] and value['revision'] != plain['revision']
    assert {key: item for key, item in selected.items() if key != 'chipReference'} == plain['selectedStocks'][0]
    selected['chipReference']['sourceRefs'].append('mutated')
    assert chip == before


@pytest.mark.parametrize('bad', [None, {}, {'displayOnly': False}])
def test_export_rejects_present_invalid_chip(bad):
    with pytest.raises(ValueError, match='chip_reference'):
        build_export(release(), request_id='chip', source_git_commit='a'*40, actions_run_id='1', details={'2330': {'chipReference': bad}})


def test_validator_rejects_invalid_optional_chip_independent_of_hash():
    value = build_export(release(), request_id='chip', source_git_commit='a'*40, actions_run_id='1')
    value['selectedStocks'][0]['chipReference'] = {'displayOnly': False}
    assert any(error.startswith('chip_reference') for error in validate_export(value))
