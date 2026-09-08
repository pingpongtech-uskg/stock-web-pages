#!/usr/bin/env python3
"""Validate parsed StatementDog health-check reference evidence.

Reference only: this script never becomes the production scoring source.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

GROUPS = {
    "bomb": "safety",
    "cd": "dividend",
    "growth": "growth",
    "cheap": "value",
    "quality": "continuity",
    "turnaround": "turnaround",
    "chip": "chip",
}
EXPECTED = {"safety": 6, "dividend": 5, "growth": 5, "value": 6, "continuity": 5, "turnaround": 3, "chip": 3}


def main(path: str) -> int:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("results", [])
    complete = []
    mismatches = []
    for row in rows:
        groups = {GROUPS[k]: v for k, v in row.get("groups", {}).items() if k in GROUPS}
        if set(groups) == set(EXPECTED) and all(g.get("count") == EXPECTED[name] for name, g in groups.items()):
            complete.append(row["code"])
        else:
            mismatches.append({"code": row.get("code"), "groups": sorted(groups), "counts": {k: v.get("count") for k, v in groups.items()}})
    print(json.dumps({"requested": len(rows), "complete_7_group": len(complete), "complete_codes": complete, "incomplete": len(mismatches), "sample_incomplete": mismatches[:10]}, ensure_ascii=False, indent=2))
    return 0 if not mismatches else 2

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/statementdog-reference-500.json"))
