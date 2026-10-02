import pytest

from pipeline.release_contract import compute_funnel, growth_coverage_error, is_common_stock_code


def valuation(*, proxy: bool = True, below: bool = True) -> dict[str, object]:
    if proxy:
        return {"growth_method": "three_month_revenue_proxy", "growth_method_label": "三月營收成長代理", "below_075": below}
    return {"growth_method": "ltm_reported_eps", "growth_method_label": "LTM 已公布 EPS 成長", "below_075": below}


def test_compute_funnel_counts_are_conserving():
    funnel = compute_funnel(
        universe=100,
        price_complete=7,
        instrument_excluded=4,
        valuations=[
            valuation(), valuation(), valuation(), valuation(),
            valuation(proxy=False),
            valuation(proxy=False, below=False),
        ],
        strategy_counts={"trust": 5, "growth": 5, "lowPosition": 2},
    )

    assert funnel["version"] == "funnel-v2-independent-trust-low-position"
    assert funnel["valuationComplete"] == 6
    assert funnel["pegCandidates"] == 5
    assert funnel["proxyValuations"] == 4
    assert funnel["formalValuations"] == 2
    assert funnel["strategyCandidates"]["lowPosition"] == 2
    assert funnel["instrumentExcluded"] == 4
    assert funnel["instrumentPolicy"] == "peg-strategies-exclude-non-common-codes-v1"


def test_compute_funnel_allows_trust_route_above_peg_threshold():
    funnel = compute_funnel(
        universe=10,
        price_complete=2,
        instrument_excluded=0,
        valuations=[valuation(), valuation(below=False)],
        strategy_counts={"trust": 2, "growth": 1, "lowPosition": 1},
    )

    assert funnel["valuationComplete"] == 2
    assert funnel["pegCandidates"] == 1
    assert funnel["strategyCandidates"]["trust"] == 2


def test_compute_funnel_keeps_trust_and_low_position_independent_of_peg_pool():
    funnel = compute_funnel(
        universe=10,
        price_complete=10,
        instrument_excluded=0,
        valuations=[valuation(below=False)],
        strategy_counts={"trust": 10, "growth": 0, "lowPosition": 4},
    )
    assert funnel["strategyCandidates"] == {"trust": 10, "growth": 0, "lowPosition": 4}


def test_compute_funnel_allows_growth_independent_of_the_peg_pool():
    funnel = compute_funnel(
        universe=100,
        price_complete=7,
        instrument_excluded=0,
        valuations=[valuation()],
        strategy_counts={"growth": 2},
    )

    assert funnel["pegCandidates"] == 1
    assert funnel["growthCandidates"] == 2


def growth_coverage(*, outcomes=None):
    return {
        "growthCoverageVersion": "growth-coverage-v1",
        "growthEvaluationState": "partial",
        "growthInputComplete": 2,
        "growthValuationComplete": 1,
        "growthThresholdCandidates": 1,
        "growthHealthCandidates": 1,
        "growthCandidates": 1,
        "growthMissingReasons": [],
        "growthTerminalOutcomes": outcomes or {
            "universe": 2,
            "missing": 1,
            "knownInvalid": 0,
            "extreme": 0,
            "belowThreshold": 0,
            "healthBlocked": 0,
            "selected": 1,
        },
    }


def test_growth_coverage_is_independent_of_peg_candidates():
    funnel = {
        "version": "funnel-v2-independent-trust-low-position",
        "universe": 2,
        "pegCandidates": 0,
        "growthCandidates": 1,
        "growthCoverageVersion": "growth-coverage-v1",
        **{k: v for k, v in growth_coverage().items() if k != "growthCoverageVersion"},
    }

    assert growth_coverage_error(funnel, required=True, expected_universe=2) is None


def test_growth_coverage_rejects_missing_marker_negative_count_and_nonconservation():
    valid = growth_coverage()
    assert growth_coverage_error({key: value for key, value in valid.items() if key != "growthCoverageVersion"}) == "growth_coverage_version"
    assert growth_coverage_error({**valid, "growthInputComplete": -1}, expected_universe=2) == "growth_coverage_count:growthInputComplete"
    broken = {
        **valid,
        "growthTerminalOutcomes": {**valid["growthTerminalOutcomes"], "missing": 2},
    }
    assert growth_coverage_error(broken, expected_universe=2) == "growth_coverage_terminal_conservation"


def test_legacy_funnel_is_accepted_without_reinterpreting_old_growth_zero():
    legacy = {
        "version": "funnel-v2-independent-trust-low-position",
        "growthValuationComplete": 0,
        "growthCandidates": 0,
    }
    assert growth_coverage_error(legacy) is None
    assert growth_coverage_error(legacy, required=True) == "growth_coverage_required"


def test_unversioned_new_missing_reasons_are_not_mistaken_for_legacy():
    legacy_with_partial_v1 = {
        "version": "funnel-v2-independent-trust-low-position",
        "growthCandidates": 0,
        "growthMissingReasons": [{"reason": "missing inputs", "count": 1}],
    }
    assert growth_coverage_error(legacy_with_partial_v1) == "growth_coverage_version"


def test_common_stock_code_filter_separates_etf_and_etn_codes():
    assert is_common_stock_code("2330")
    assert is_common_stock_code("6488")
    assert is_common_stock_code("1504")
    assert not is_common_stock_code("0050")
    assert not is_common_stock_code("0056")
    assert not is_common_stock_code("009803")
    assert not is_common_stock_code("00980A")
    assert not is_common_stock_code("020000")
