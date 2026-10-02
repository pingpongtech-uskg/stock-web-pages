import pytest

from pipeline.growth_coverage import build_growth_coverage, validate_growth_coverage
from pipeline.growth_health import CHECK_LABELS


def detail(code, status, *, complete=False, pe=None, growth=None, eligible=False, reasons=()):
    valuation = {
        "status": status,
        "inputsComplete": complete,
        "total_return_pe": pe,
        "earnings_growth": growth,
        "missingReasons": list(reasons),
    }
    row = {
        "code": code,
        "growthValuation": valuation,
    }
    if eligible:
        row["healthCategories"] = [
            {
                "key": "growth",
                "checks": [
                    {"label": label, "status": "pass" if index < 4 else "unknown"}
                    for index, label in enumerate(CHECK_LABELS)
                ],
            }
        ]
    return row


def test_coverage_counts_stages_and_conserves_exclusive_common_stock_outcomes():
    rows = [
        detail("2330", "unavailable", reasons=("ttm_eps", "dividend")),
        detail("2303", "unavailable", complete=True, growth=0),
        detail("2317", "extreme", complete=True, pe=3.0),
        detail("2454", "available", complete=True, pe=1.19),
        detail("2881", "available", complete=True, pe=1.4),
        detail("2882", "available", complete=True, pe=1.5, eligible=True),
    ]

    coverage = build_growth_coverage(
        rows,
        universe=7,
        selected_codes={"2882"},
    )

    assert coverage == {
        "growthCoverageVersion": "growth-coverage-v1",
        "growthEvaluationState": "partial",
        "growthInputComplete": 5,
        "growthValuationComplete": 3,
        "growthThresholdCandidates": 2,
        "growthHealthCandidates": 1,
        "growthCandidates": 1,
        "growthMissingReasons": [
            {"reason": "dividend", "count": 1},
            {"reason": "ttm_eps", "count": 1},
        ],
        "growthTerminalOutcomes": {
            "universe": 7,
            "missing": 2,
            "knownInvalid": 1,
            "extreme": 1,
            "belowThreshold": 1,
            "healthBlocked": 1,
            "selected": 1,
        },
    }
    assert validate_growth_coverage(coverage, expected_universe=7) == []


def test_four_pass_and_one_unknown_qualifies_when_aggregate_is_unknown():
    row = detail("2330", "available", complete=True, pe=1.2)
    row["healthCategories"] = [{"key": "growth", "status": "unknown", "checks": [
        {"label": label, "status": "pass" if index < 4 else "unknown"}
        for index, label in enumerate(CHECK_LABELS)
    ]}]

    coverage = build_growth_coverage([row], universe=1)

    assert coverage["growthHealthCandidates"] == 1
    assert coverage["growthCandidates"] == 1
    assert coverage["growthTerminalOutcomes"]["selected"] == 1


def test_four_pass_and_one_fail_qualifies_even_when_aggregate_fails():
    row = detail("2330", "available", complete=True, pe=1.2)
    row["healthCategories"] = [{"key": "growth", "status": "fail", "checks": [
        {"label": label, "status": "pass" if index < 4 else "fail"}
        for index, label in enumerate(CHECK_LABELS)
    ]}]

    coverage = build_growth_coverage([row], universe=1)

    assert coverage["growthHealthCandidates"] == 1
    assert coverage["growthCandidates"] == 1


def test_three_pass_two_unknown_and_aggregate_pass_does_not_qualify():
    row = detail("2330", "available", complete=True, pe=1.2)
    row["healthCategories"] = [{"key": "growth", "status": "pass", "passCount": 5, "checks": [
        {"label": label, "status": "pass" if index < 3 else "unknown"}
        for index, label in enumerate(CHECK_LABELS)
    ]}]

    coverage = build_growth_coverage([row], universe=1)

    assert coverage["growthHealthCandidates"] == 0
    assert coverage["growthCandidates"] == 0
    assert coverage["growthTerminalOutcomes"]["healthBlocked"] == 1


def test_aggregate_or_precomputed_eligibility_without_real_checks_does_not_qualify():
    row = detail("2330", "available", complete=True, pe=1.2)
    row["growthHealthEligible"] = True
    row["healthCategories"] = [{"key": "growth", "status": "pass", "passCount": 5, "total": 5}]

    coverage = build_growth_coverage([row], universe=1)

    assert coverage["growthHealthCandidates"] == 0
    assert coverage["growthTerminalOutcomes"]["healthBlocked"] == 1


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "not_evaluable"),
        (["unavailable", "unavailable"], "not_evaluable"),
        (["available", "unavailable"], "partial"),
        (["available", "extreme"], "evaluated"),
    ],
)
def test_evaluation_state_tracks_valuation_completeness(statuses, expected):
    rows = [
        detail(f"{2000 + index}", status, complete=status == "available", pe=1.3 if status == "available" else None)
        for index, status in enumerate(statuses)
    ]
    assert build_growth_coverage(rows, universe=len(statuses))["growthEvaluationState"] == expected


@pytest.mark.parametrize(
    "coverage",
    [
        {},
        {"growthCoverageVersion": "old"},
        {"growthCoverageVersion": "growth-coverage-v1", "growthEvaluationState": "complete"},
    ],
)
def test_growth_coverage_validator_rejects_missing_or_unknown_contract_fields(coverage):
    assert validate_growth_coverage(coverage)


def test_growth_coverage_rejects_bad_denominators_duplicate_codes_and_impossible_selection():
    with pytest.raises(ValueError):
        build_growth_coverage([detail("2330", "available")], universe=0)
    with pytest.raises(ValueError):
        build_growth_coverage([detail("2330", "available"), detail("2330", "available")])
    with pytest.raises(ValueError):
        build_growth_coverage([detail("2330", "unavailable")], selected_codes={"2330"})


def test_coverage_validator_refuses_negative_counts_and_failed_conservation():
    rows = [detail("2330", "available", complete=True, pe=1.3, eligible=True)]
    coverage = build_growth_coverage(rows, universe=1, selected_codes={"2330"})

    negative = {**coverage, "growthInputComplete": -1}
    assert "growth_coverage_count:growthInputComplete" in validate_growth_coverage(negative, expected_universe=1)

    broken = {
        **coverage,
        "growthTerminalOutcomes": {**coverage["growthTerminalOutcomes"], "missing": 1},
    }
    assert "growth_coverage_terminal_conservation" in validate_growth_coverage(broken, expected_universe=1)


def test_available_valuation_with_known_invalid_input_is_rejected_as_inconsistent():
    with pytest.raises(ValueError, match="known-invalid"):
        build_growth_coverage(
            [detail("2330", "available", complete=True, pe=1.3, growth=0)],
            universe=1,
        )


@pytest.mark.parametrize(
    ("audit", "missing_reasons"),
    [
        ({"ttmEps": {"reason": "nonpositive_ttm_eps"}}, ["ttmEps", "dividendYield"]),
        ({"earningsGrowth": {"reason": "完整年度 EPS 包含非正值"}}, ["earningsGrowth", "dividendYield"]),
    ],
)
def test_explicit_nonpositive_financial_evidence_is_known_invalid_not_missing(audit, missing_reasons):
    row = detail("2330", "unavailable", complete=True)
    row["growthValuation"]["inputAudit"] = audit
    row["growthValuation"]["missingReasons"] = missing_reasons
    coverage = build_growth_coverage([row], universe=1)

    assert coverage["growthTerminalOutcomes"]["knownInvalid"] == 1
    assert coverage["growthTerminalOutcomes"]["missing"] == 0
    assert coverage["growthEvaluationState"] == "evaluated"
    assert coverage["growthMissingReasons"] == [{"reason": "dividendYield", "count": 1}]
