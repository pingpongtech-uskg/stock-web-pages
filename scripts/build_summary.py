#!/usr/bin/env python3
"""
build_summary.py — Generate lightweight stock summary JSON for the list page.
Output: public/data/stocks_summary.json (~2-3 MB vs 160MB of full data)
"""
import json, os, glob

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "data")
STOCKS_DIR = os.path.join(OUTPUT_DIR, "stocks")

def main():
    summaries = []
    files = sorted(glob.glob(os.path.join(STOCKS_DIR, "*.json")))
    
    for fpath in files:
        with open(fpath) as f:
            d = json.load(f)
        
        # Extract only what the list page needs
        closes = d.get("price", {}).get("close", [])
        # Last 60 for sparkline
        sparkline_closes = closes[-60:] if len(closes) > 60 else closes
        
        summaries.append({
            "code": d["code"],
            "name": d["name"],
            "latest": d["latest"],
            "ma_status": d["ma_status"],
            "sparkline": sparkline_closes,
        })
    
    out_path = os.path.join(OUTPUT_DIR, "stocks_summary.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, separators=(",", ":"))
    
    size_kb = os.path.getsize(out_path) / 1024
    print(f"Generated {out_path}: {len(summaries)} stocks, {size_kb:.0f} KB")

if __name__ == "__main__":
    main()
