from __future__ import annotations

import json
from pathlib import Path

from scripts.grade_public_health_score import grade_predictions


def _prediction(code: str, values: dict[str, int]) -> dict:
    categories = {
        name: {
            "passed": passed,
            "failed": 6 - passed if name in {"safety", "value"} else 5 - passed,
            "unknown": 0,
            "not_applicable": 0,
            "total": 6 if name in {"safety", "value"} else 5,
            "score": f"{passed}/{6 if name in {'safety', 'value'} else 5}",
            "status": "pass",
            "criteria": [],
        }
        for name, passed in values.items()
    }
    return {"company_code": code, "market": "TWSE", "categories": categories, "criteria": [], "data_quality": {"unknown_criteria": 0}}


def test_grader_reports_exact_category_and_vector_metrics():
    predictions = [_prediction("2330", {"safety": 5, "value": 0, "growth": 5})]
    gold = [{"company_code": "2330", "market": "TWSE", "categories": {"safety": {"passed": 5, "total": 6}, "value": {"passed": 0, "total": 6}, "growth": {"passed": 5, "total": 5}}}]
    report = grade_predictions(predictions, gold, bootstrap_iterations=50)
    assert report["matched_companies"] == 1
    assert report["categories"]["safety"]["exact_score_agreement"] == 1.0
    assert report["seven_category_vector"]["exact_match"] == 1.0
    assert report["claim"]["statementdog_like"] is False


def test_grader_marks_mismatch_and_unknown_rate():
    prediction = _prediction("2330", {"safety": 4, "value": 0})
    prediction["categories"]["safety"]["unknown"] = 1
    prediction["categories"]["safety"]["failed"] = 1
    prediction["data_quality"] = {"unknown_criteria": 1, "total_criteria": 33}
    gold = [{"company_code": "2330", "market": "TWSE", "categories": {"safety": {"passed": 5, "total": 6}, "value": {"passed": 0, "total": 6}}}]
    report = grade_predictions([prediction], gold, bootstrap_iterations=20)
    assert report["categories"]["safety"]["exact_score_agreement"] == 0.0
    assert report["unknown_rate"] > 0
