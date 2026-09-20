from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts.refresh_snapshot import clean_detail_limitations
from scripts.verify_snapshot import (
    compute_input_hash,
    first_non_finite_path,
    input_hash_error,
    is_number,
    ranking_valuation_error,
    regression_contract_error,
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
    refresh = workflow.index("python scripts/refresh_snapshot.py")
    verify = workflow.index("python scripts/verify_snapshot.py")
    fetch = workflow.index("python scripts/fetch_finmind.py")
    assert fetch < refresh < verify
    assert "python -m pytest pipeline scripts -q" in workflow
