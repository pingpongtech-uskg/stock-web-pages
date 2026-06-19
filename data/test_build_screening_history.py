import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import build_screening_history as history


def write_report(reports_dir: Path, day: str, rows: list[dict]) -> None:
    compact_day = day.replace("-", "")
    payload = {
        "date": day,
        "time": "20:30",
        "note": "篩選: TOP100金額 → Z<=0 → G>=80 & L>=80",
        "top10": rows,
    }
    (reports_dir / f"daily_trust10_{compact_day}.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def row(code: str, name: str, price: float, rank: int = 1) -> dict:
    return {
        "rank": rank,
        "code": code,
        "name": name,
        "name_zh": name,
        "cur_price": price,
        "net_amount_10d": 302000000,
        "net_amount_10d_k": 302000,
        "net_shares_10d": 101579,
        "net_shares_10d_zhang": 102,
        "last_date": "2026-06-17",
        "g_score": 100,
        "l_score": 80,
        "regression_z": -1.27,
        "statementdog_url": f"https://statementdog.com/analysis/{code}",
    }


def test_builds_active_history_from_daily_trust_reports(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    write_report(reports_dir, "2026-07-01", [row("2330", "台積電", 1000), row("2105", "正新", 29.7, 2)])

    result = history.build_screening_history(reports_dir, reference_date="2026-07-15")

    assert result["summary"]["active_stocks"] == 2
    assert result["summary"]["archive_stocks"] == 0
    assert result["active_days"][0]["date"] == "2026-07-01"
    assert result["active_days"][0]["count"] == 2
    assert result["active_days"][0]["records"][0]["code"] == "2330"
    assert result["active_days"][0]["records"][0]["screening_status"] == "active"
    assert result["active_days"][0]["records"][0]["price"] == 1000


def test_archives_stock_on_thirtieth_idle_day_and_keeps_last_snapshot(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    write_report(reports_dir, "2026-06-18", [row("2330", "台積電", 900)])
    write_report(reports_dir, "2026-06-25", [row("2330", "台積電", 950)])
    write_report(reports_dir, "2026-07-20", [row("2105", "正新", 29.7)])

    result = history.build_screening_history(reports_dir, reference_date="2026-07-25")

    assert result["summary"]["active_stocks"] == 1
    assert result["summary"]["archive_stocks"] == 1
    assert result["active_days"][0]["records"][0]["code"] == "2105"
    assert result["archive_days"][0]["date"] == "2026-06-25"
    assert result["archive_days"][0]["records"][0]["code"] == "2330"
    assert result["archive_days"][0]["records"][0]["price"] == 950
    assert result["archive_days"][0]["records"][0]["days_since_screened"] == 30
    assert result["archive_days"][0]["records"][0]["archived_at"] == "2026-07-25"


def test_write_screening_history_outputs_public_and_src_json(tmp_path: Path):
    reports_dir = tmp_path / "reports"
    public_dir = tmp_path / "public"
    src_dir = tmp_path / "src"
    reports_dir.mkdir()
    write_report(reports_dir, "2026-07-01", [row("2330", "台積電", 1000)])

    result = history.generate_screening_history(
        reports_dir=reports_dir,
        public_data_dir=public_dir,
        src_data_dir=src_dir,
        reference_date="2026-07-15",
    )

    assert result["summary"]["total_records"] == 1
    assert (public_dir / "screening_history.json").exists()
    assert (src_dir / "screening_history.json").exists()
