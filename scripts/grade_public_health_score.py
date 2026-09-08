#!/usr/bin/env python3
"""Grade public-data predictions against an externally supplied gold file.

Gold labels are deliberately isolated here.  The production scorer has no
path to this module or to the gold file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screener.public_data_models import CATEGORY_ORDER


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("predictions", "records", "companies", "data"):
            if isinstance(payload.get(key), list):
                return [row for row in payload[key] if isinstance(row, dict)]
        return [payload]
    raise ValueError(f"{path} JSON root must be object or list")


def _key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("company_code", row.get("code", ""))), str(row.get("market", ""))


def _count(category: Mapping[str, Any]) -> int | None:
    if isinstance(category.get("passed"), int):
        return int(category["passed"])
    score = category.get("score")
    if isinstance(score, str) and "/" in score:
        try:
            return int(score.split("/", 1)[0])
        except ValueError:
            return None
    return None


def _total(category: Mapping[str, Any]) -> int | None:
    if isinstance(category.get("total"), int):
        return int(category["total"])
    score = category.get("score")
    if isinstance(score, str) and "/" in score:
        try:
            return int(score.split("/", 1)[1])
        except ValueError:
            return None
    return None


def _bootstrap_interval(values: Sequence[float], iterations: int, *, seed: int) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    rng = random.Random(seed)
    estimates = []
    for _ in range(iterations):
        sample = [values[rng.randrange(len(values))] for _ in values]
        estimates.append(sum(sample) / len(sample))
    estimates.sort()
    low_index = max(0, min(len(estimates) - 1, int(0.025 * len(estimates))))
    high_index = max(0, min(len(estimates) - 1, int(0.975 * len(estimates)) - 1))
    return estimates[low_index], estimates[high_index]


def _wilson_lower(successes: int, total: int, *, z: float = 2.45) -> float | None:
    if total <= 0:
        return None
    n = float(total)
    p = successes / n
    denominator = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) / n) + (z * z / (4 * n * n)))
    return (center - margin) / denominator


def _category_rows(predictions: Mapping[tuple[str, str], Mapping[str, Any]], gold: Mapping[tuple[str, str], Mapping[str, Any]], category: str) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    rows = []
    for key in sorted(set(predictions) & set(gold)):
        pred_cat = predictions[key].get("categories", {}).get(category)
        gold_cat = gold[key].get("categories", {}).get(category)
        if isinstance(pred_cat, Mapping) and isinstance(gold_cat, Mapping):
            rows.append((pred_cat, gold_cat))
    return rows


def _criterion_metrics(rows: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, Any]:
    pairs: list[tuple[str, str, str]] = []
    for pred, gold in rows:
        pred_criteria = pred.get("criteria", []) if isinstance(pred, Mapping) else []
        gold_criteria = gold.get("criteria", []) if isinstance(gold, Mapping) else []
        pred_map = {str(item["criterion_id"]): str(item.get("status", "unknown")).lower() for item in pred_criteria if isinstance(item, Mapping) and item.get("criterion_id")}
        gold_map = {str(item["criterion_id"]): str(item.get("status", "unknown")).lower() for item in gold_criteria if isinstance(item, Mapping) and item.get("criterion_id")}
        for criterion_id in sorted(set(pred_map) & set(gold_map)):
            pairs.append((criterion_id, pred_map[criterion_id], gold_map[criterion_id]))
    ids = sorted({item[0] for item in pairs})
    if not ids:
        return {"available": False, "criterion_count": 0, "macro_f1": None, "metrics": {}}
    metrics: dict[str, Any] = {}
    f1_values = []
    for criterion_id in ids:
        relevant = [(pred_status, gold_status) for item, pred_status, gold_status in pairs if item == criterion_id]
        tp = sum(pred_status == "pass" and gold_status == "pass" for pred_status, gold_status in relevant)
        fp = sum(pred_status == "pass" and gold_status != "pass" for pred_status, gold_status in relevant)
        fn = sum(pred_status != "pass" and gold_status == "pass" for pred_status, gold_status in relevant)
        tn = sum(pred_status != "pass" and gold_status != "pass" for pred_status, gold_status in relevant)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
        tpr = tp / (tp + fn) if tp + fn else None
        tnr = tn / (tn + fp) if tn + fp else None
        balanced = (tpr + tnr) / 2 if tpr is not None and tnr is not None else None
        metrics[criterion_id] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": f1, "balanced_accuracy": balanced}
        if f1 is not None:
            f1_values.append(f1)
    return {"available": True, "criterion_count": len(ids), "macro_f1": sum(f1_values) / len(f1_values) if f1_values else None, "metrics": metrics}


def grade_predictions(
    predictions: Sequence[Mapping[str, Any]],
    gold: Sequence[Mapping[str, Any]],
    *,
    bootstrap_iterations: int = 1000,
) -> dict[str, Any]:
    if bootstrap_iterations < 1:
        raise ValueError("bootstrap_iterations must be positive")
    pred_map = {_key(row): row for row in predictions}
    gold_map = {_key(row): row for row in gold}
    common = sorted(set(pred_map) & set(gold_map))
    if not common:
        raise ValueError("no matching company_code/market rows")
    category_names = [category for category in CATEGORY_ORDER if any(category in pred_map[key].get("categories", {}) and category in gold_map[key].get("categories", {}) for key in common)]
    categories: dict[str, Any] = {}
    for category in category_names:
        rows = _category_rows(pred_map, gold_map, category)
        exact_values: list[float] = []
        errors: list[float] = []
        normalized_errors: list[float] = []
        weighted_values: list[float] = []
        unknown_numerator = 0
        unknown_denominator = 0
        for pred_cat, gold_cat in rows:
            pred_count, gold_count = _count(pred_cat), _count(gold_cat)
            total = _total(gold_cat) or _total(pred_cat)
            if pred_count is None or gold_count is None or total is None or total <= 0:
                continue
            exact_values.append(float(pred_count == gold_count and (_total(pred_cat) in (None, total))))
            error = abs(pred_count - gold_count)
            errors.append(float(error))
            normalized_errors.append(error / total)
            weighted_values.append(max(0.0, 1.0 - error / total))
            unknown_numerator += int(pred_cat.get("unknown", 0) or 0)
            unknown_denominator += int(_total(pred_cat) or total)
        exact = sum(exact_values) / len(exact_values) if exact_values else None
        seed = int.from_bytes(hashlib.sha256(category.encode("utf-8")).digest()[:4], "big")
        ci_low, ci_high = _bootstrap_interval(exact_values, bootstrap_iterations, seed=seed)
        categories[category] = {
            "matched_companies": len(rows),
            "exact_score_agreement": exact,
            "bootstrap_95ci": [ci_low, ci_high],
            "bonferroni_adjusted_lower_bound": _wilson_lower(int(sum(exact_values)), len(exact_values)) if exact_values else None,
            "absolute_pass_count_error": sum(errors) / len(errors) if errors else None,
            "normalized_mae": sum(normalized_errors) / len(normalized_errors) if normalized_errors else None,
            "weighted_ordinal_agreement": sum(weighted_values) / len(weighted_values) if weighted_values else None,
            "unknown_rate": unknown_numerator / unknown_denominator if unknown_denominator else 0.0,
            "criterion_metrics": _criterion_metrics(rows),
        }
    vectors = []
    for key in common:
        pred_categories = pred_map[key].get("categories", {})
        gold_categories = gold_map[key].get("categories", {})
        shared = [name for name in category_names if name in pred_categories and name in gold_categories]
        vectors.append(all(_count(pred_categories[name]) == _count(gold_categories[name]) for name in shared) if shared else False)
    vector_exact = sum(vectors) / len(vectors) if vectors else None
    vector_low, vector_high = _bootstrap_interval([float(value) for value in vectors], bootstrap_iterations, seed=9173)
    unknown_values = []
    proxy_values = []
    for key in common:
        quality = pred_map[key].get("data_quality", {})
        total = int(quality.get("total_criteria", 33) or 33)
        unknown_values.append(int(quality.get("unknown_criteria", 0) or 0) / total)
        criteria = pred_map[key].get("criteria", [])
        proxy_values.append(sum(bool(item.get("proxy")) for item in criteria if isinstance(item, Mapping)) / len(criteria) if isinstance(criteria, list) and criteria else 0.0)
    unknown_rate = sum(unknown_values) / len(unknown_values) if unknown_values else 0.0
    proxy_rate = sum(proxy_values) / len(proxy_values) if proxy_values else 0.0
    available_category_gates = all(category in categories for category in CATEGORY_ORDER)
    normalized_mae_values = [value["normalized_mae"] for value in categories.values() if value["normalized_mae"] is not None]
    weighted_values = [value["weighted_ordinal_agreement"] for value in categories.values() if value["weighted_ordinal_agreement"] is not None]
    f1_values = [value["criterion_metrics"]["macro_f1"] for value in categories.values() if value["criterion_metrics"].get("macro_f1") is not None]
    lower_bounds = [value["bonferroni_adjusted_lower_bound"] for value in categories.values() if value["bonferroni_adjusted_lower_bound"] is not None]
    public_model_gate = bool(
        available_category_gates
        and lower_bounds
        and min(lower_bounds) >= 0.90
        and vector_low is not None
        and vector_low >= 0.80
        and normalized_mae_values
        and max(normalized_mae_values) <= 0.05
        and weighted_values
        and min(weighted_values) >= 0.80
        and f1_values
        and min(f1_values) >= 0.90
        and unknown_rate <= 0.02
    )
    return {
        "matched_companies": len(common),
        "prediction_count": len(predictions),
        "gold_count": len(gold),
        "categories": categories,
        "seven_category_vector": {"category_count": len(category_names), "exact_match": vector_exact, "bootstrap_95ci": [vector_low, vector_high], "lower_bound": _wilson_lower(int(sum(vectors)), len(vectors)) if vectors else None},
        "unknown_rate": unknown_rate,
        "proxy_rate": proxy_rate,
        "claim": {
            "public_data_model_gate": public_model_gate,
            "statementdog_like": False,
            "statementdog_exact": False,
            "reason": "This scorer is an independent transparent public-data model; gold labels are calibration only.",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    args = parser.parse_args(argv)
    report = grade_predictions(_read_rows(args.predictions), _read_rows(args.gold), bootstrap_iterations=args.bootstrap_iterations)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["claim"]["public_data_model_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
