#!/usr/bin/env python3
"""Apply issuer-sourced PEG evidence to the current validated release."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import re
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import prepare_peg_evidence
from scripts.build_peg_review import build_review
from scripts.refresh_snapshot import build_release


def validate_inputs(market_date: str, request_id: str, manifest: dict, latest: dict) -> list[str]:
    if date.fromisoformat(market_date).isoformat() != market_date:
        raise ValueError("exact market_date required")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", request_id):
        raise ValueError("invalid request_id")
    if latest.get("marketDate") != market_date:
        raise ValueError("requested date must match current latest release")
    if manifest.get("marketDate") != market_date:
        raise ValueError("search manifest marketDate mismatch")
    stock_rows = latest.get("stocks")
    if not isinstance(stock_rows, list):
        raise ValueError("latest release stocks must be a list")
    codes = {str(row["code"]) for row in stock_rows if isinstance(row, dict) and row.get("code")}
    if len(codes) != 100:
        raise ValueError(f"expected 100 distinct stocks, found {len(codes)}")
    ranked = {str(row["code"]) for rows in latest.get("rankings", {}).values() for row in rows}
    if not ranked.issubset(codes):
        raise ValueError("rankings contain stock code outside release stocks")
    return sorted(codes)


def dated_evidence(manifest: dict, raw_results: list[dict], as_of: str) -> dict:
    by_code = {str(item.get("code")): item for item in raw_results}
    observed = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    stocks = []
    for source in manifest.get("stocks", []):
        code = str(source.get("code", ""))
        item = by_code.get(code, {"records": [], "sources": [], "reason": "source_not_found"})
        records = []
        for record in item.get("records", []):
            records.append({**record, **({"observedAt": observed} if not record.get("publishedDate") and not record.get("observedAt") else {})})
        stocks.append({"code": code, "records": records, "sources": item.get("sources", []),
                       "reason": item.get("reason")})
    # A missing/empty manifest still yields an explicit review record per stock.
    return {"marketDate": as_of, "stocks": stocks}


def review_lineage(manifest: dict) -> dict:
    return {key: manifest[key] for key in ('prepareRunId', 'prepareRunAttempt', 'candidateSha256') if key in manifest}


def run(*, data_dir: Path, market_date: str, request_id: str, manifest_path: Path,
        source_git_commit: str, actions_run_id: str, dry_run: bool = False) -> dict:
    original_data_dir = data_dir
    temp_context = tempfile.TemporaryDirectory(prefix="peg-repair-") if dry_run else None
    if temp_context:
        data_dir = Path(temp_context.name) / "data"
        shutil.copytree(original_data_dir, data_dir)
    latest_path = data_dir / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"marketDate": market_date, "stocks": []}
    codes = validate_inputs(market_date, request_id, manifest, latest)
    if not isinstance(manifest.get("stocks", []), list):
        raise ValueError("search manifest stocks must be a list")
    known = set(codes)
    if any(str(stock.get("code", "")) not in known for stock in manifest.get("stocks", [])):
        raise ValueError("search manifest contains code outside current release")
    work = data_dir.parent.parent / ".peg-repair-work"
    work.mkdir(parents=True, exist_ok=True)
    parsed = prepare_peg_evidence.run(manifest, output_dir=work / "evidence-cache")
    evidence_path = work / "evidence.json"
    evidence_path.write_text(json.dumps(dated_evidence(manifest, parsed, market_date), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = build_release(data_dir, [], as_of=market_date, offline=False,
                           recompute_existing=True, ownership_snapshot=ROOT / '.cache/ownership_snapshot.json', peg_evidence_path=evidence_path)
    release = json.loads(latest_path.read_text(encoding="utf-8"))
    if release.get("marketDate") != market_date:
        raise ValueError("release build changed target date")
    updated_codes = {str(row["code"]) for row in release.get("stocks", []) if isinstance(row, dict) and row.get("code")}
    if updated_codes != set(codes):
        raise ValueError("release build changed 100-stock universe")
    export = [sys.executable, str(ROOT / "scripts/build_screening_export.py"), "--data-dir", str(data_dir),
              "--request-id", request_id, "--market-date", market_date, "--source-git-commit", source_git_commit,
              "--actions-run-id", actions_run_id]
    if dry_run:
        # The isolated export still runs its production validators, with local
        # placeholder lineage that cannot be mistaken for a published run.
        source_git_commit = source_git_commit if re.fullmatch(r"[0-9a-f]{40}", source_git_commit) else "0" * 40
        actions_run_id = actions_run_id if actions_run_id.isdigit() else "0"
        export[export.index("--source-git-commit") + 1] = source_git_commit
        export[export.index("--actions-run-id") + 1] = actions_run_id
    subprocess.run(export, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/build_publication_fingerprint.py"), "--data-dir", str(data_dir), "--market-date", market_date], check=True)
    lineage = review_lineage(manifest)
    manifest_context = manifest if len(lineage) == 3 else None
    review = build_review(data_dir, market_date, request_id, source_git_commit, actions_run_id,
                          manifest=manifest_context, prepare_run=str(lineage.get('prepareRunId', '')),
                          prepare_attempt=str(lineage.get('prepareRunAttempt', '')),
                          candidate_sha256=str(lineage.get('candidateSha256', '')))
    counts = review['counts']
    summary = {"marketDate": market_date, "runId": release["runId"], "requestId": request_id,
               "counts": counts, "stocks": len(codes), "evidenceStocks": len(manifest.get("stocks", [])), "dryRun": dry_run}
    if temp_context:
        temp_context.cleanup()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-date", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "public/data")
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/peg_search_results.json")
    parser.add_argument("--source-git-commit", default="local")
    parser.add_argument("--actions-run-id", default="1")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(data_dir=args.data_dir, market_date=args.market_date, request_id=args.request_id,
                             manifest_path=args.manifest, source_git_commit=args.source_git_commit,
                             actions_run_id=args.actions_run_id, dry_run=args.dry_run), ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(f"peg_repair_failed={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
