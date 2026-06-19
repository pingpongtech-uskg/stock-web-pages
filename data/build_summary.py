#!/usr/bin/env python3
"""
build_summary.py — Generate lightweight stock summary JSON for the list page.
Output: public/data/stocks_summary.json (~2-3 MB vs 160MB of full data)
"""
import json
import os
import glob
from datetime import date, datetime
from pathlib import Path

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "data")
STOCKS_DIR = os.path.join(OUTPUT_DIR, "stocks")
SRC_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "data")
ARCHIVE_AFTER_DAYS = 30


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def classify_screening_status(last_screened_at: str, reference_date: str | None = None) -> dict:
    """
    Active until the stock has not appeared in screening for 30 calendar days.

    Example: last screened on 2026-06-25, archive on 2026-07-25.
    """
    ref = parse_iso_date(reference_date) if reference_date else date.today()
    last_seen = parse_iso_date(last_screened_at)
    days_since_screened = max((ref - last_seen).days, 0)
    is_archive = days_since_screened >= ARCHIVE_AFTER_DAYS

    return {
        "screening_status": "archive" if is_archive else "active",
        "days_since_screened": days_since_screened,
        "archived_at": ref.isoformat() if is_archive else None,
    }


def resolve_last_screened_at(stock: dict) -> str:
    for key in ("last_screened_at", "last_screened_on", "screened_at", "screening_date", "end"):
        if stock.get(key):
            return str(stock[key])

    screening = stock.get("screening")
    if isinstance(screening, dict):
        for key in ("last_screened_at", "last_screened_on", "screened_at", "date"):
            if screening.get(key):
                return str(screening[key])

    for key in ("screened_dates", "screening_dates"):
        values = stock.get(key)
        if isinstance(values, list) and values:
            return str(max(values))

    raise ValueError(f"Missing last screened date for {stock.get('code', '?')}")


def load_previous_summary(output_dir: Path) -> dict[str, dict]:
    path = output_dir / "stocks_summary.json"
    if not path.exists():
        return {}

    with path.open(encoding="utf-8") as f:
        previous = json.load(f)

    return {
        item["code"]: item
        for item in previous
        if isinstance(item, dict) and item.get("code")
    }


def build_summary_item(stock: dict, previous_by_code: dict[str, dict], reference_date: str | None = None) -> dict:
    closes = stock.get("price", {}).get("close", [])
    sparkline_closes = closes[-60:] if len(closes) > 60 else closes
    code = stock["code"]
    last_screened_at = resolve_last_screened_at(stock)
    lifecycle = classify_screening_status(last_screened_at, reference_date)
    previous = previous_by_code.get(code, {})
    is_archive = lifecycle["screening_status"] == "archive"

    latest = previous.get("latest") if is_archive and previous.get("latest") else stock["latest"]
    ma_status = previous.get("ma_status") if is_archive and previous.get("ma_status") else stock["ma_status"]
    sparkline = previous.get("sparkline") if is_archive and previous.get("sparkline") else sparkline_closes

    return {
        "code": code,
        "name": stock["name"],
        "latest": latest,
        "ma_status": ma_status,
        "sparkline": sparkline,
        "last_screened_at": last_screened_at,
        **lifecycle,
    }


def write_summary(summaries: list[dict], output_dir: Path, src_data_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    src_data_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / "stocks_summary.json"
    src_path = src_data_dir / "stocks_summary.json"

    for path in (out_path, src_path):
        with path.open("w", encoding="utf-8") as f:
            json.dump(summaries, f, ensure_ascii=False, separators=(",", ":"))

    return out_path


def generate_summary(
    stocks_dir: str | Path = STOCKS_DIR,
    output_dir: str | Path = OUTPUT_DIR,
    src_data_dir: str | Path = SRC_DATA_DIR,
    reference_date: str | None = None,
) -> list[dict]:
    stocks_dir = Path(stocks_dir)
    output_dir = Path(output_dir)
    src_data_dir = Path(src_data_dir)
    previous_by_code = load_previous_summary(output_dir)
    summaries = []
    files = sorted(glob.glob(str(stocks_dir / "*.json")))
    
    for fpath in files:
        with open(fpath, encoding="utf-8") as f:
            d = json.load(f)
        summaries.append(build_summary_item(d, previous_by_code, reference_date))

    write_summary(summaries, output_dir, src_data_dir)
    return summaries


def main():
    summaries = generate_summary()
    out_path = os.path.join(OUTPUT_DIR, "stocks_summary.json")
    
    size_kb = os.path.getsize(out_path) / 1024
    print(f"Generated {out_path}: {len(summaries)} stocks, {size_kb:.0f} KB")

if __name__ == "__main__":
    main()
