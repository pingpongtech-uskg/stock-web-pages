#!/usr/bin/env python3
"""
build_screener_history.py — Consolidate daily_trust10_*.json into screener_history.json.

Input:  /root/tw-stock-monitor/output/reports/daily_trust10_*.json
Output: src/data/screener_history.json

Structure:
  - active: unique stocks sorted by most recent 上榜日 (newest first)
  - archive: all screening entries grouped by date (newest first)
"""
import json
import os
import glob
from datetime import date, datetime, timedelta
from collections import defaultdict

REPORTS_DIR = "/root/tw-stock-monitor/output/reports"
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "data", "screener_history.json")
ARCHIVE_AFTER_DAYS = 30


def load_reports(reports_dir: str) -> list[dict]:
    """Load all daily_trust10_*.json files, return sorted by date DESC."""
    pattern = os.path.join(reports_dir, "daily_trust10_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    reports = []
    for fpath in files:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        reports.append(data)
    return reports


def consolidate(reports: list[dict], reference_date: str | None = None) -> dict:
    """
    Build active (unique per stock, latest entry) and archive (grouped by date).
    """
    ref = date.today() if reference_date is None else datetime.strptime(reference_date, "%Y-%m-%d").date()
    cutoff = ref - timedelta(days=ARCHIVE_AFTER_DAYS)

    # Collect all entries + build name_zh lookup (older reports may lack name_zh)
    name_zh_map: dict[str, str] = {
        # Fallback for stocks that only appeared in older reports without name_zh
        "2377": "微星",
        "1229": "聯華",
        "2548": "華固",
    }
    for report in reports:
        for stock in report.get("top10", []):
            code = stock.get("code", "")
            zh = stock.get("name_zh", "")
            if code and zh:
                name_zh_map[code] = zh

    all_entries: list[dict] = []
    for report in reports:
        report_date = report.get("date", "")
        for stock in report.get("top10", []):
            code = stock.get("code", "")
            name_zh = stock.get("name_zh", "") or name_zh_map.get(code, "")
            entry = {
                "code": code,
                "name_zh": name_zh,
                "name_en": stock.get("name", ""),
                "net_amount_10d": stock.get("net_amount_10d", 0),
                "net_amount_10d_k": stock.get("net_amount_10d_k", 0),
                "net_shares_10d": stock.get("net_shares_10d", 0),
                "net_shares_10d_zhang": stock.get("net_shares_10d_zhang", 0),
                "last_date": stock.get("last_date", report_date),
                "cur_price": stock.get("cur_price", 0),
                "g_score": stock.get("g_score", 0),
                "l_score": stock.get("l_score", 0),
                "regression_z": stock.get("regression_z", 0),
                "rank": stock.get("rank", 0),
                "screening_date": report_date,
            }
            all_entries.append(entry)

    # Active: deduplicate by code, keep latest (by screening_date)
    latest_by_code: dict[str, dict] = {}
    for entry in all_entries:
        code = entry["code"]
        if code not in latest_by_code or entry["screening_date"] > latest_by_code[code]["screening_date"]:
            latest_by_code[code] = entry

    # Separate active vs archive based on last_date
    active = []
    archive_date_to_stocks: dict[str, list[dict]] = defaultdict(list)

    for code, entry in latest_by_code.items():
        try:
            last_d = datetime.strptime(entry["last_date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            last_d = date(2000, 1, 1)
        if last_d >= cutoff:
            active.append(entry)
        else:
            # Archive: add all entries for this stock grouped by date
            for e in all_entries:
                if e["code"] == code:
                    archive_date_to_stocks[e["screening_date"]].append(e)

    # Also add entries for stocks that are active but have historical appearances
    # Active stocks should also have their full history in archive
    for code, entry in latest_by_code.items():
        try:
            last_d = datetime.strptime(entry["last_date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            last_d = date(2000, 1, 1)
        if last_d >= cutoff:
            for e in all_entries:
                if e["code"] == code and e["screening_date"] != entry["screening_date"]:
                    archive_date_to_stocks[e["screening_date"]].append(e)

    # Sort active: by last_date DESC (newest first)
    active.sort(key=lambda x: x["last_date"], reverse=True)

    # Build archive: sorted by date DESC, within each date sorted by net_amount_10d DESC
    archive = {}
    for d in sorted(archive_date_to_stocks.keys(), reverse=True):
        stocks = sorted(archive_date_to_stocks[d], key=lambda x: x["net_amount_10d"], reverse=True)
        archive[d] = stocks

    return {"active": active, "archive": archive}


def main():
    reports = load_reports(REPORTS_DIR)
    print(f"Loaded {len(reports)} reports")

    result = consolidate(reports)

    active_count = len(result["active"])
    archive_dates = len(result["archive"])
    archive_entries = sum(len(v) for v in result["archive"].values())
    print(f"Active: {active_count} unique stocks")
    print(f"Archive: {archive_entries} entries across {archive_dates} dates")

    out_dir = os.path.dirname(OUTPUT_FILE)
    os.makedirs(out_dir, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"Written: {OUTPUT_FILE} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
