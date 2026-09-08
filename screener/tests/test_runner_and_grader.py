from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from scripts.run_public_health_score import InputManifestError, run_score_job


def _record(code: str, market: str) -> dict:
    return {
        "market": market,
        "company_code": code,
        "company_name": f"fixture-{code}",
        "market_date": "2025-03-01",
        "listing_date": "2010-01-01",
        "metadata": {"universe_complete": True},
        "facts": [
            {
                "normalized_field": "pb",
                "period": "2025-03-01",
                "period_type": "daily",
                "value": 2,
                "observed_at": "2025-03-01",
                "source_id": "fixture.pb",
                "source_url": "https://fixture.invalid/pb",
                "provider": "fixture",
                "content_sha256": "sha256:" + "a" * 64,
            }
        ],
    }


def _input_dir(tmp_path: Path, *, status: str = "complete") -> Path:
    root = tmp_path / "input"
    root.mkdir()
    records = root / "records.json"
    records.write_text(json.dumps([_record("2330", "TWSE"), _record("6488", "TPEx")]), encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps({"status": status, "schema_version": 1, "universe_complete": True, "files": ["records.json"]}),
        encoding="utf-8",
    )
    return root


def test_runner_requires_complete_input_manifest(tmp_path: Path):
    root = _input_dir(tmp_path, status="partial")
    with pytest.raises(InputManifestError, match="complete"):
        run_score_job(root, tmp_path / "out", as_of=date(2025, 3, 1))


def test_runner_writes_required_artifacts_and_unknowns(tmp_path: Path):
    root = _input_dir(tmp_path)
    out = tmp_path / "out"
    report = run_score_job(root, out, as_of=date(2025, 3, 1))
    assert report["exit_code"] == 0
    assert report["success_count"] == 2
    assert report["failure_count"] == 0
    assert report["unknown_count"] > 0
    for name in ("predictions.jsonl", "score_summary.json", "errors.jsonl", "run_manifest.json"):
        assert (out / name).is_file()
    predictions = [json.loads(line) for line in (out / "predictions.jsonl").read_text().splitlines()]
    assert [row["company_code"] for row in predictions] == ["6488", "2330"]
    manifest = json.loads((out / "run_manifest.json").read_text())
    assert manifest["formula_version"] == "public-data-health-v1"
    assert manifest["input_manifest_hashes"]


def test_runner_does_not_read_gold_labels(tmp_path: Path):
    root = _input_dir(tmp_path)
    (root / "gold.json").write_text(json.dumps({"2330": {"safety": {"passed": 6}}}), encoding="utf-8")
    report = run_score_job(root, tmp_path / "out", as_of=date(2025, 3, 1))
    assert report["gold_used"] is False
