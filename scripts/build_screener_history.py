#!/usr/bin/env python3
"""
build_screener_history.py — Consolidate daily_trust10_*.json into screener_history.json.

Input:  /root/tw-stock-monitor/output/reports/daily_trust10_*.json
Output: src/data/screener_history.json

Structure:
  - active: unique stocks sorted by last_date DESC (newest first)
  - archive: all screening entries grouped by date (newest first)

Each entry includes:
  - first_date: earliest screening date (首次上榜日)
  - last_date: most recent screening date (最新上榜日)
  - consecutive_days: consecutive screening streak (連續買超日數)
"""
import json
import os
import glob
from datetime import date, datetime, timedelta
from collections import defaultdict

REPORTS_DIR = "/root/tw-stock-monitor/output/reports"
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "data", "screener_history.json")
ARCHIVE_AFTER_DAYS = 30
# Maximum gap (calendar days) between screening dates that still counts as consecutive
# 3 days covers Fri→Mon and single-day holidays
MAX_CONSECUTIVE_GAP = 3


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


def calc_consecutive_days(screening_dates: list[str]) -> int:
    """
    Count consecutive screening dates from the most recent backwards.
    A gap of MAX_CONSECUTIVE_GAP calendar days or fewer is considered consecutive
    (handles weekends and single-day holidays).
    """
    if not screening_dates:
        return 0
    dates = sorted([datetime.strptime(d, "%Y-%m-%d").date() for d in set(screening_dates)], reverse=True)
    if not dates:
        return 0
    consecutive = 1
    for i in range(1, len(dates)):
        gap = (dates[i - 1] - dates[i]).days
        if gap <= MAX_CONSECUTIVE_GAP:
            consecutive += 1
        else:
            break
    return consecutive


def consolidate(reports: list[dict], reference_date: str | None = None) -> dict:
    """
    Build active (unique per stock, latest entry) and archive (grouped by date).
    """
    ref = date.today() if reference_date is None else datetime.strptime(reference_date, "%Y-%m-%d").date()
    cutoff = ref - timedelta(days=ARCHIVE_AFTER_DAYS)

    # Build name_zh lookup (older reports may lack name_zh)
    name_zh_map: dict[str, str] = {
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

    # Collect all entries
    all_entries: list[dict] = []
    code_to_dates: dict[str, list[str]] = defaultdict(list)

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
            code_to_dates[code].append(report_date)

    # Active: deduplicate by code, keep latest entry, add computed fields
    latest_by_code: dict[str, dict] = {}
    for entry in all_entries:
        code = entry["code"]
        if code not in latest_by_code or entry["screening_date"] > latest_by_code[code]["screening_date"]:
            latest_by_code[code] = entry

    # Compute per-stock aggregates
    for code, entry in latest_by_code.items():
        dates = code_to_dates.get(code, [])
        first_date = min(dates) if dates else entry["last_date"]
        consecutive = calc_consecutive_days(dates)
        entry["first_date"] = first_date
        entry["consecutive_days"] = consecutive

    # Also add to archive entries
    for e in all_entries:
        code = e["code"]
        dates = code_to_dates.get(code, [])
        first_date = min(dates) if dates else e["last_date"]
        consecutive = calc_consecutive_days(dates)
        e["first_date"] = first_date
        e["consecutive_days"] = consecutive

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

        # All entries (including active stocks' history) go to archive
        for e in all_entries:
            if e["code"] == code:
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

    # Show a few active stocks with new fields
    print(f"\nActive: {active_count} unique stocks")
    for s in result["active"][:5]:
        print(f"  {s['code']} {s['name_zh']} | 首次:{s['first_date']} 最新:{s['last_date']} 連續:{s['consecutive_days']}日 | Z={s['regression_z']}")

    print(f"\nArchive: {archive_entries} entries across {archive_dates} dates")

    out_dir = os.path.dirname(OUTPUT_FILE)
    os.makedirs(out_dir, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"\nWritten: {OUTPUT_FILE} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
