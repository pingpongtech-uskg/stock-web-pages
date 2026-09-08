#!/usr/bin/env python3
"""Run the public-data seven-category score over a manifest-backed input set."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from screener.public_data_models import ScoreConfig, Status, stable_hash
from screener.public_data_normalizer import NormalizationResult, _read_json_file, normalize_records
from screener.statementdog_like_scorer import score_company, summary

FORMULA_VERSION = "public-data-health-v1"
MODEL_VERSION = "public-data-health-v1"
REQUIRED_OUTPUTS = ("predictions.jsonl", "score_summary.json", "errors.jsonl", "run_manifest.json")


class InputManifestError(ValueError):
    """Input is not a complete, hash-verifiable production snapshot."""


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_message(error: BaseException) -> str:
    message = str(error)
    message = re.sub(r"(?i)(token|password|secret|authorization|api[_-]?key)=([^\s,;]+)", r"\1=[REDACTED]", message)
    message = re.sub(r"(?i)(cookie|session)=([^\s,;]+)", r"\1=[REDACTED]", message)
    return message[:500]


def _load_complete_manifest(input_root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    if not input_root.is_dir():
        raise InputManifestError(f"input must be a directory: {input_root}")
    manifest_path = input_root / "manifest.json"
    if not manifest_path.is_file():
        raise InputManifestError("input manifest.json is required")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise InputManifestError(f"manifest parse failed: {type(exc).__name__}") from exc
    if not isinstance(manifest, dict) or manifest.get("status") != "complete":
        raise InputManifestError("input manifest status must be complete")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise InputManifestError("complete manifest must list input files")
    hashes: dict[str, str] = {"manifest.json": _file_hash(manifest_path)}
    declared_hashes = manifest.get("hashes") if isinstance(manifest.get("hashes"), dict) else {}
    for name in files:
        if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
            raise InputManifestError("manifest contains unsafe file path")
        path = (input_root / name).resolve()
        if input_root.resolve() not in path.parents:
            raise InputManifestError("manifest file escapes input root")
        if not path.is_file():
            raise InputManifestError(f"manifest file missing: {name}")
        actual = _file_hash(path)
        expected = declared_hashes.get(name)
        if expected is not None and expected != actual:
            raise InputManifestError(f"input hash mismatch: {name}")
        hashes[name] = actual
    return manifest, hashes


def _load_manifest_records(input_root: Path, manifest: Mapping[str, Any]) -> NormalizationResult:
    raw_records: list[Mapping[str, Any]] = []
    errors: list[str] = []
    for name in manifest["files"]:
        path = input_root / str(name)
        try:
            raw_records.extend(_read_json_file(path))
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {_safe_message(exc)}")
    result = normalize_records(raw_records)
    return NormalizationResult(result.companies, result.conflicts, tuple(errors) + result.errors)


def _apply_manifest_metadata(result: NormalizationResult, manifest: Mapping[str, Any]) -> NormalizationResult:
    complete = manifest.get("universe_complete") is True
    companies = []
    for company in result.companies:
        metadata = dict(company.metadata)
        metadata.setdefault("universe_complete", complete)
        companies.append(
            company.__class__(
                company_code=company.company_code,
                market=company.market,
                company_name=company.company_name,
                market_date=company.market_date,
                listing_date=company.listing_date,
                statement_scope=company.statement_scope,
                facts=company.facts,
                dividends=company.dividends,
                metadata=metadata,
            )
        )
    return NormalizationResult(tuple(companies), result.conflicts, result.errors)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _write_json(path: Path, payload: Any) -> None:
    _write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _error_record(error: Any, *, company_code: str | None = None, severity: str = "error") -> dict[str, Any]:
    if isinstance(error, BaseException):
        error_type = type(error).__name__
        message = _safe_message(error)
    else:
        error_type = "DataError"
        message = _safe_message(ValueError(str(error)))
    return {"severity": severity, "company_code": company_code, "error_type": error_type, "message": message}


def _write_outputs(
    output_root: Path,
    *,
    scores: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    input_hashes: Mapping[str, str],
    as_of: date,
    conflict_count: int,
    config: ScoreConfig,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    prediction_text = "".join(json.dumps(score.to_dict(), ensure_ascii=False, sort_keys=True) + "\n" for score in scores)
    _write_text_atomic(output_root / "predictions.jsonl", prediction_text)
    summary_payload = summary(scores)
    summary_payload.update({"errors": len(errors), "conflicts": conflict_count, "model_version": config.model_version, "formula_version": config.formula_version, "market_date": as_of.isoformat()})
    _write_json(output_root / "score_summary.json", summary_payload)
    _write_text_atomic(output_root / "errors.jsonl", "".join(json.dumps(dict(error), ensure_ascii=False, sort_keys=True) + "\n" for error in errors))
    unknown_count = sum(sum(result.status == Status.UNKNOWN for result in score.criteria) for score in scores)
    not_applicable_count = sum(sum(result.status == Status.NOT_APPLICABLE for result in score.criteria) for score in scores)
    failure_count = len(errors)
    run_id = f"{as_of.isoformat()}-{stable_hash({'input': dict(input_hashes), 'formula_version': config.formula_version})[7:19]}"
    exit_code = 1 if errors or conflict_count else 0
    run_manifest = {
        "run_id": run_id,
        "market_date": as_of.isoformat(),
        "model_version": config.model_version,
        "formula_version": config.formula_version,
        "input_manifest_hashes": dict(sorted(input_hashes.items())),
        "input_manifest_status": manifest.get("status"),
        "universe_complete": manifest.get("universe_complete") is True,
        "success_count": len(scores),
        "failure_count": failure_count,
        "unknown_count": unknown_count,
        "not_applicable_count": not_applicable_count,
        "conflict_count": conflict_count,
        "gold_used": False,
        "free_fallback_transport_calls": 0,
        "exit_code": exit_code,
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "thresholds": dict(config.category_thresholds),
        "z_max": config.z_max,
    }
    _write_json(output_root / "run_manifest.json", run_manifest)
    return run_manifest


def run_score_job(
    input_root: str | Path,
    output_root: str | Path,
    *,
    as_of: date,
    thresholds: Mapping[str, float] | None = None,
    include_special_dividends: bool = False,
    z_max: int | None = None,
    min_history_observations: int = 20,
) -> dict[str, Any]:
    input_path = Path(input_root)
    output_path = Path(output_root)
    manifest, input_hashes = _load_complete_manifest(input_path)
    normalized = _apply_manifest_metadata(_load_manifest_records(input_path, manifest), manifest)
    errors = [_error_record(error, severity="input_error") for error in normalized.errors]
    errors.extend(_error_record({"type": "data_conflict", **conflict}, severity="data_conflict") for conflict in normalized.conflicts)
    if not normalized.companies and not errors:
        errors.append(_error_record("no company records", severity="input_error"))
    config = ScoreConfig(
        category_thresholds=thresholds or {category: 0.5 for category in ("turnaround", "value", "growth", "chip", "dividend", "continuity", "safety")},
        include_special_dividends=include_special_dividends,
        universe_complete=manifest.get("universe_complete") is True,
        z_max=z_max,
        min_history_observations=min_history_observations,
    )
    scores = []
    for company in sorted(normalized.companies, key=lambda item: (item.market, item.company_code)):
        try:
            scores.append(score_company(company, normalized.companies, as_of=as_of, config=config))
        except Exception as exc:
            errors.append(_error_record(exc, company_code=company.company_code))
    return _write_outputs(output_path, scores=scores, errors=errors, manifest=manifest, input_hashes=input_hashes, as_of=as_of, conflict_count=len(normalized.conflicts), config=config)


def _parse_thresholds(values: Sequence[str]) -> dict[str, float]:
    result = {category: 0.5 for category in ("turnaround", "value", "growth", "chip", "dividend", "continuity", "safety")}
    for value in values:
        if "=" not in value:
            raise ValueError("threshold must be CATEGORY=RATIO")
        category, ratio = value.split("=", 1)
        if category not in result:
            raise ValueError(f"unknown category threshold: {category}")
        result[category] = float(ratio)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, dest="market_date")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threshold", action="append", default=[])
    parser.add_argument("--include-special-dividends", action="store_true")
    parser.add_argument("--z-max", type=int, choices=(0, 1, 2), default=None)
    parser.add_argument("--min-history-observations", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        cutoff = date.fromisoformat(args.market_date)
        report = run_score_job(args.input, args.output, as_of=cutoff, thresholds=_parse_thresholds(args.threshold), include_special_dividends=args.include_special_dividends, z_max=args.z_max, min_history_observations=args.min_history_observations)
    except (ValueError, OSError) as exc:
        args.output.mkdir(parents=True, exist_ok=True)
        failure = {"run_id": None, "market_date": args.market_date, "model_version": MODEL_VERSION, "formula_version": FORMULA_VERSION, "input_manifest_hashes": {}, "success_count": 0, "failure_count": 1, "unknown_count": 0, "exit_code": 2, "gold_used": False}
        _write_text_atomic(args.output / "predictions.jsonl", "")
        _write_json(args.output / "score_summary.json", {"company_count": 0, "errors": 1})
        _write_text_atomic(args.output / "errors.jsonl", json.dumps(_error_record(exc, severity="input_error"), ensure_ascii=False) + "\n")
        _write_json(args.output / "run_manifest.json", failure)
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
