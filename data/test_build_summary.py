import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import build_summary as summary


def stock_payload(code, end, latest_price=100):
    return {
        "code": code,
        "name": f"{code} 測試",
        "end": end,
        "latest": {"price": latest_price, "change_pct": 1.2, "volume": 12345},
        "ma_status": "多頭排列",
        "price": {"close": [latest_price - 2, latest_price - 1, latest_price]},
    }


def test_classifies_archive_on_thirtieth_day():
    result = summary.classify_screening_status("2026-06-25", "2026-07-25")

    assert result["screening_status"] == "archive"
    assert result["days_since_screened"] == 30
    assert result["archived_at"] == "2026-07-25"


def test_classifies_recent_screening_as_active():
    result = summary.classify_screening_status("2026-06-25", "2026-07-24")

    assert result["screening_status"] == "active"
    assert result["days_since_screened"] == 29
    assert result["archived_at"] is None


def test_archived_summary_preserves_previous_price_snapshot(tmp_path: Path):
    stocks_dir = tmp_path / "stocks"
    output_dir = tmp_path / "out"
    src_data_dir = tmp_path / "src"
    stocks_dir.mkdir()
    output_dir.mkdir()
    src_data_dir.mkdir()

    (stocks_dir / "2330.json").write_text(
        json.dumps(stock_payload("2330", "2026-06-25", latest_price=888)),
        encoding="utf-8",
    )
    previous = [
        {
            "code": "2330",
            "name": "2330 測試",
            "latest": {"price": 777, "change_pct": -0.5, "volume": 999},
            "ma_status": "盤整",
            "sparkline": [775, 776, 777],
            "last_screened_at": "2026-06-25",
            "screening_status": "active",
        }
    ]
    (output_dir / "stocks_summary.json").write_text(json.dumps(previous), encoding="utf-8")

    summaries = summary.generate_summary(
        stocks_dir=stocks_dir,
        output_dir=output_dir,
        src_data_dir=src_data_dir,
        reference_date="2026-07-25",
    )

    assert summaries[0]["screening_status"] == "archive"
    assert summaries[0]["latest"]["price"] == 777
    assert summaries[0]["ma_status"] == "盤整"
    assert summaries[0]["sparkline"] == [775, 776, 777]
    assert (src_data_dir / "stocks_summary.json").exists()
