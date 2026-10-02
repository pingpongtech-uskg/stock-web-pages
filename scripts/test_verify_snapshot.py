from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from scripts.refresh_snapshot import clean_detail_limitations
from scripts.verify_snapshot import (
    compute_input_hash,
    first_non_finite_path,
    input_hash_error,
    is_number,
    ranking_valuation_error,
    regression_contract_error,
    market_indicator_error,
)


ROOT = Path(__file__).resolve().parents[1]


def test_is_number_rejects_non_finite_values() -> None:
    assert not is_number(float("nan"))
    assert not is_number(float("inf"))
    assert not is_number(float("-inf"))
    assert is_number(1.25)


def test_nested_non_finite_values_are_located() -> None:
    assert first_non_finite_path({"stocks": [{"z": float("nan")}]}) == "stocks[0].z"


def test_input_hash_detects_detail_tampering() -> None:
    latest = {"marketDate": "2026-09-11"}
    manifest = {"baselineRunId": "baseline-1", "inputCodes": []}
    details = [{"code": "2330", "regression": {"observations": 853}}]
    manifest["inputHash"] = compute_input_hash(manifest, latest, details)

    tampered = [{"code": "2330", "regression": {"observations": 852}}]

    assert input_hash_error(manifest, latest, tampered) == "manifest_input_hash"


def test_adjusted_regression_requires_complete_observation_contract() -> None:
    regression = {
        "priceBasis": "adjusted",
        "historyStart": "2023-03-13",
        "historyEnd": "2026-09-11",
        "observations": 852,
        "expectedObservations": 853,
        "coveragePct": 99.88,
        "signalEligible": True,
    }

    assert regression_contract_error(regression, "2330", date(2026, 9, 11)) == "regression_observations_mismatch:2330"


def test_recent_ineligible_short_history_is_valid() -> None:
    regression = {
        "priceBasis": "adjusted",
        "historyStart": "2026-09-22",
        "historyEnd": "2026-10-01",
        "observations": 8,
        "expectedObservations": 8,
        "coveragePct": 100.0,
        "signalEligible": False,
    }

    assert regression_contract_error(regression, "7856", date(2026, 10, 1)) is None


def test_short_history_cannot_be_eligible() -> None:
    regression = {
        "priceBasis": "adjusted",
        "historyStart": "2026-09-22",
        "historyEnd": "2026-10-01",
        "observations": 8,
        "expectedObservations": 8,
        "coveragePct": 100.0,
        "signalEligible": True,
    }
    assert regression_contract_error(regression, "7856", date(2026, 10, 1)) == "regression_window_start:7856"


def test_short_history_requires_boolean_false_eligibility() -> None:
    regression = {
        "priceBasis": "adjusted",
        "historyStart": "2026-09-22",
        "historyEnd": "2026-10-01",
        "observations": 8,
        "expectedObservations": 8,
        "coveragePct": 100.0,
        "signalEligible": "false",
    }
    assert regression_contract_error(regression, "7856", date(2026, 10, 1)) == "regression_signal_eligible_type:7856"


def test_complete_eligible_regression_window_is_valid() -> None:
    regression = {
        "priceBasis": "adjusted",
        "historyStart": "2023-04-02",
        "historyEnd": "2026-10-01",
        "observations": 853,
        "expectedObservations": 853,
        "coveragePct": 100.0,
        "signalEligible": True,
    }
    assert regression_contract_error(regression, "2330", date(2026, 10, 1)) is None


def test_ineligible_regression_cannot_start_after_market_end() -> None:
    regression = {
        "priceBasis": "adjusted",
        "historyStart": "2026-10-02",
        "historyEnd": "2026-10-03",
        "observations": 2,
        "expectedObservations": 2,
        "coveragePct": 100.0,
        "signalEligible": False,
    }
    assert regression_contract_error(regression, "7856", date(2026, 10, 1)) == "regression_window_start:7856"


def test_ineligible_regression_cannot_use_pre_window_history() -> None:
    regression = {
        "priceBasis": "adjusted",
        "historyStart": "2023-03-18",
        "historyEnd": "2026-10-01",
        "observations": 2,
        "expectedObservations": 2,
        "coveragePct": 100.0,
        "signalEligible": False,
    }
    assert regression_contract_error(regression, "7856", date(2026, 10, 1)) == "regression_window_start:7856"


@pytest.mark.parametrize("signal_eligible", [False, True])
def test_reversed_regression_dates_are_rejected(signal_eligible: bool) -> None:
    regression = {
        "priceBasis": "adjusted",
        "historyStart": "2026-09-30",
        "historyEnd": "2026-09-29",
        "observations": 2,
        "expectedObservations": 2,
        "coveragePct": 100.0,
        "signalEligible": signal_eligible,
    }

    assert regression_contract_error(regression, "7856", date(2026, 10, 1)) == "regression_date_order:7856"


def test_missing_regression_object_is_rejected() -> None:
    assert regression_contract_error(None, "2330", date(2026, 9, 11)) == "regression_missing:2330"


def test_partial_numeric_valuation_fields_are_rejected() -> None:
    assert ranking_valuation_error({"code": "2330", "fairPrice": 100}, "trust") == "ranking_row_valuation_partial:trust"


def test_price_observation_without_peg_is_allowed() -> None:
    row = {
        "code": "4915",
        "currentPrice": 65.5,
        "currentPeg": None,
        "fairPrice": None,
        "valuePrice075": None,
        "valuePrice066": None,
    }
    assert ranking_valuation_error(row, "lowPosition") is None


def test_stale_four_year_limitations_are_removed() -> None:
    values = [
        "四年研究曲線使用 yfinance Adj Close；...",
        "3.5 年研究曲線使用 yfinance Adj Close；...",
        "品質代理只看最新可得期",
    ]

    assert clean_detail_limitations(values) == [
        "3.5 年研究曲線使用 yfinance Adj Close；...",
        "品質代理只看最新可得期",
    ]


def test_daily_workflow_runs_v3_refresh_and_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    universe_fetch = workflow.index("python scripts/fetch_research_universe.py --source official")
    universe_gate = workflow.index(
        "python scripts/verify_tracked_universe.py --config config/tracked_symbols.json --snapshot public/data/institutional_universe.json"
    )
    refresh = workflow.index("python scripts/refresh_snapshot.py")
    verify = workflow.index("python scripts/verify_snapshot.py")
    freshness = workflow.index("python scripts/verify_daily_freshness.py")
    fetch_finmind = workflow.index("python scripts/fetch_finmind.py")
    pytest_gate = workflow.index("python -m pytest pipeline scripts -q")
    vitest_gate = workflow.index("npm run test:unit")
    typecheck_gate = workflow.index("npm run typecheck")
    build = workflow.index("npm run build")
    final_universe_gate = workflow.index(
        "python scripts/verify_tracked_universe.py --config config/tracked_symbols.json --snapshot public/data/institutional_universe.json --latest public/data/latest.json"
    )
    publish = workflow.index("git add config/tracked_symbols.json public/data")

    assert fetch_finmind < refresh < verify < freshness
    assert universe_fetch < universe_gate < refresh
    assert "--offline" not in workflow
    assert pytest_gate < vitest_gate < typecheck_gate < build < final_universe_gate < publish
    assert workflow.count("python scripts/verify_tracked_universe.py") == 2


def test_volume_indicator_enforces_two_times_green_boundary() -> None:
    base = {
        "symbol": "00631L", "market": "TWSE",
        "formulaVersion": "twse-volume-multiple-v1", "threshold": 2,
        "displayOnly": True,
        "priorFiveSessions": [{"date": f"2026-09-{day:02d}", "volume": 1500} for day in range(15, 20)],
        "status": "available", "signal": "green",
        "sourceRefs": ["TWSE STOCK_DAY"], "currentVolume": 3000,
        "previous5AverageVolume": 1500, "multiple": 2,
        "marketDate": "2026-09-22",
    }
    assert market_indicator_error({"volumeMultiple00631L": base}, "2026-09-22") is None
    assert market_indicator_error({"volumeMultiple00631L": {**base, "multiple": 1.99, "signal": "green"}}, "2026-09-22") == "volume_indicator_yellow_threshold"
