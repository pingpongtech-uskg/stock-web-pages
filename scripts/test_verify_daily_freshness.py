from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_daily_freshness import freshness_errors


def write_release(tmp_path: Path, *, market_date: str = "2026-09-23", detail_date: str = "2026-09-23") -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    run_id = "run-1"
    detail_dir = data_dir / "releases" / run_id / "stocks"
    detail_dir.mkdir(parents=True)
    config_path = tmp_path / "tracked_symbols.json"
    config_path.write_text(json.dumps({"universe": {"marketDates": ["2026-09-23"]}}), encoding="utf-8")
    detail = {
        "code": "2330",
        "asOf": detail_date,
        "institutionDataAsOf": "2026-09-23",
        "institutionalDaily": [{"status": "pass"} for _ in range(10)],
        "regression": {"historyEnd": detail_date, "priceBasis": "adjusted"},
    }
    (detail_dir / "2330.json").write_text(json.dumps(detail), encoding="utf-8")
    release = {
        "runId": run_id,
        "marketDate": market_date,
        "marketIndicators": {"volumeMultiple00631L": {"marketDate": market_date}},
        "stocks": [{"code": "2330"}],
    }
    data_dir.mkdir(exist_ok=True)
    (data_dir / "latest.json").write_text(json.dumps(release), encoding="utf-8")
    return data_dir, config_path


def test_current_release_passes(tmp_path: Path) -> None:
    data_dir, config_path = write_release(tmp_path)
    assert freshness_errors(data_dir, config_path) == []


def test_old_market_date_is_rejected(tmp_path: Path) -> None:
    data_dir, config_path = write_release(tmp_path, market_date="2026-09-18", detail_date="2026-09-18")
    errors = freshness_errors(data_dir, config_path)
    assert any(error.startswith("release_market_date:") for error in errors)
    assert any(error.startswith("00631L_market_date:") for error in errors)
    assert any(error.startswith("price_date:") for error in errors)
