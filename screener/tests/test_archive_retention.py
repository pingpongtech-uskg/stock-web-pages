from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scripts.run_public_screener import load_archive


def _write_report(root: Path, day: str, code: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "market_date": day,
        "records": [{
            "code": code,
            "market": "TWSE",
            "name_zh": "fixture",
            "regression_z": -0.5,
            "categories": {"growth": {"passed": 2, "total": 3}},
            "criteria": [{"criterion_id": "growth.example", "status": "pass", "value": 1}],
        }],
    }
    (root / f"daily_public_screener_{day.replace('-', '')}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_archive_retention_uses_one_calendar_year_and_keeps_details(tmp_path: Path):
    _write_report(tmp_path, "2025-09-08", "keep")
    _write_report(tmp_path, "2025-09-07", "drop")
    _write_report(tmp_path, "2026-01-15", "keep2")
    archive = load_archive(tmp_path, exclude_date="2026-09-08", as_of=date(2026, 9, 8))
    assert set(archive) == {"2025-09-08", "2026-01-15"}
    assert archive["2025-09-08"][0]["criteria"][0]["criterion_id"] == "growth.example"
