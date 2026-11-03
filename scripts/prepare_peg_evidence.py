#!/usr/bin/env python3
"""Fetch bounded, issuer-host financial documents from a search-results manifest."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.financial_discovery import discover, fetch_document, merge_eps, parse_document


def run(manifest: dict, *, details_dir: Path | None = None, output_dir: Path | None = None) -> list[dict]:
    results = []
    cache_root = (output_dir or Path(".peg-evidence-cache")) / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    for stock in manifest.get("stocks", []):
        found = discover(stock)
        code = str(stock.get("code", ""))
        records, tried = [], []
        for cand in found["candidates"][:3]:
            url = cand["url"]
            tried.append({**cand, "status": "pending"})
            cache_material = "\0".join((url, code, str(stock.get("legalName", "")), "parser-v3-identity-currency"))
            cache_key = __import__("hashlib").sha256(cache_material.encode()).hexdigest()
            cache_file = cache_root / f"{cache_key}.json"
            if cache_file.exists() and time.time() - cache_file.stat().st_mtime < 86400:
                cached = json.loads(cache_file.read_text())
                tried[-1]["status"] = cached["status"]
                records.extend(cached.get("records", []))
                continue
            error = None
            for attempt in range(2):
                try:
                    body, digest = fetch_document(url, stock.get("officialDomains", []))
                    observed_at = datetime.now(timezone.utc).isoformat()
                    parsed = parse_document(body, url, digest, code=code, legal_name=str(stock.get("legalName", "")))
                    for record in parsed:
                        record["observedAt"] = observed_at
                    tried[-1]["status"] = "parsed" if parsed else "unparseable_document"
                    records.extend(parsed)
                    cache_file.write_text(json.dumps({"status": tried[-1]["status"], "records": parsed}, ensure_ascii=False))
                    error = None
                    break
                except Exception as exc:  # report failure as evidence gap; continue other candidates
                    error = exc
            if error is not None:
                exc = error
                tried[-1]["status"] = "fetch_error"
                tried[-1]["error"] = type(exc).__name__
                cache_file.write_text(json.dumps({"status": "fetch_error", "records": []}))
        periods = {}
        for record in records:
            periods.setdefault(record["period"], set()).add((record["eps"], record["epsKind"], record["scope"]))
        conflicts = sorted(period for period, values in periods.items() if len(values) > 1)
        if conflicts:
            records = [r for r in records if r["period"] not in conflicts]
            reason = "source_conflict"
        elif records:
            reason = None
        elif not found["candidates"]:
            reason = "source_not_found"
        else:
            reason = "unparseable_document"
        item = {"code": code, "records": records, "sources": tried, "candidates": found["candidates"], "reason": reason}
        results.append(item)
        if details_dir:
            detail_path = details_dir / f"{code}.json"
            if detail_path.exists() and records:
                detail = json.loads(detail_path.read_text())
                updated = merge_eps(detail, records)
                if output_dir:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    (output_dir / f"{code}.json").write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--details-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("peg-evidence-output"))
    args = parser.parse_args()
    payload = run(json.loads(args.manifest.read_text()), details_dir=args.details_dir, output_dir=args.output_dir)
    (args.output_dir / "manifest.json").write_text(json.dumps({"stocks": payload}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"processed": len(payload), "withEvidence": sum(bool(x["records"]) for x in payload)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
