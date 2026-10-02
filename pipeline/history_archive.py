"""Build and publish compact, content-addressed screening history archives."""
from __future__ import annotations
import hashlib, json, os, secrets, shutil, tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "screening-history-month-v1"
INDEX_VERSION = "screening-history-index-v1"
STRATEGIES = ("trust", "growth", "lowPosition")

def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

def _date(value: Any) -> date:
    try: return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc: raise ValueError("invalid marketDate") from exc

def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0

def _row(row: dict[str, Any], rank: int) -> dict[str, Any]:
    code = str(row.get("code", ""))
    if not code: raise ValueError("ranking row missing code")
    out: dict[str, Any] = {"rank": int(row.get("rank", rank)), "code": code,
        "name": str(row.get("name", "")), "sector": str(row.get("sector", "")),
        "value": row.get("value", row.get("currentPeg")),
        "valueLabel": str(row.get("valueLabel", "")),
        "status": row.get("status", "unknown"), "reason": str(row.get("reason", ""))}
    optional = ("entryStatus", "sourceRank", "previousRank", "currentPrice", "currentPeg",
        "growthTotalReturnPe", "growthFairPrice", "growthBuyZonePrice", "valuationEvidenceLevel",
        "valuationFormulaVersion")
    for key in optional:
        if key in row: out[key] = row[key]
    return out

def revision_for_record(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k not in {"revision", "revisionRefs", "_priorRevisions"}}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()[:12]

def project_release_to_history(release: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(release, dict) or not release.get("marketDate"):
        raise ValueError("marketDate is required")
    _date(release["marketDate"])
    freshness = release.get("freshness", "current")
    if freshness not in {"current", "stale", "degraded"}: raise ValueError("unavailable baseline")
    if not str(release.get("runId", "")): raise ValueError("runId is required")
    if freshness == "unavailable": raise ValueError("unavailable baseline")
    rankings = release.get("rankings") or {}
    strategies = {}
    for strategy in STRATEGIES:
        rows = rankings.get(strategy, [])
        if not isinstance(rows, list): raise ValueError("strategy must be a list")
        strategies[strategy] = [_row(row, i) for i, row in enumerate(rows, 1) if isinstance(row, dict)]
    funnel_in = release.get("funnel") if isinstance(release.get("funnel"), dict) else {}
    funnel = {k: _int(funnel_in.get(k)) for k in ("universe", "priceComplete", "valuationComplete", "growthValuationComplete", "pegCandidates", "growthCandidates", "formalValuations", "proxyValuations")}
    sc = funnel_in.get("strategyCandidates") if isinstance(funnel_in.get("strategyCandidates"), dict) else {}
    funnel["strategyCandidates"] = {k: _int(sc.get(k)) for k in STRATEGIES}
    from pipeline.screening_export import formula_versions as resolve_formula_versions
    formula_versions = resolve_formula_versions(release)
    record = {"marketDate": str(release["marketDate"])[:10], "generatedAt": str(release.get("generatedAt", "")),
        "runId": str(release.get("runId", "")), "revision": "", "freshness": freshness,
        "statusMessage": str(release.get("statusMessage", "")), "formulaVersions": formula_versions,
        "funnel": funnel, "strategies": strategies,
        "sourceRefs": [str(x) for x in release.get("sourceRefs", [])] if isinstance(release.get("sourceRefs", []), list) else []}
    record["revision"] = revision_for_record(record)
    return record

def merge_month(existing: list[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    _date(record.get("marketDate"))
    merged = {str(item["marketDate"]): item for item in existing if isinstance(item, dict) and item.get("marketDate")}
    previous = merged.get(str(record["marketDate"]))
    if previous and previous.get("revision") != record.get("revision"):
        previous_body = {k: v for k, v in previous.items() if k not in {"revisionRefs", "_priorRevisions"}}
        record = {**record, "revisionRefs": previous.get("revisionRefs", []),
                  "_priorRevisions": [*previous.get("_priorRevisions", []), previous_body]}
    elif previous:
        record = {**record, "revisionRefs": previous.get("revisionRefs", []),
                  "_priorRevisions": previous.get("_priorRevisions", [])}
    merged[str(record["marketDate"])] = record
    return [merged[key] for key in sorted(merged)]

def prune_to_retention(months: dict[str, list[dict[str, Any]]], today: date | str, retention_days: int = 366) -> dict[str, list[dict[str, Any]]]:
    end = _date(today); start = end - timedelta(days=retention_days - 1); result = {}
    for month, records in months.items():
        kept = [r for r in records if start <= _date(r.get("marketDate")) <= end]
        if kept: result[month] = sorted(kept, key=lambda r: r["marketDate"])
    return result

def month_filename(month: str, payload: bytes) -> str:
    return f"{month}.{hashlib.sha256(payload).hexdigest()[:12]}.json"

def _month_payload(month: str, records: list[dict[str, Any]]) -> bytes:
    return canonical_json_bytes({"schemaVersion": SCHEMA_VERSION, "month": month, "records": records})

def write_archive_atomic(staging_dir: Path | str, archive_dir: Path | str, months: dict[str, list[dict[str, Any]]], generated_at: str | None = None) -> dict[str, Any]:
    staging, archive = Path(staging_dir), Path(archive_dir)
    target = staging / secrets.token_hex(8) / "archive" / "v1"; month_dir = target / "months"; month_dir.mkdir(parents=True)
    metadata = []
    revision_dir = target / "revisions"; revision_dir.mkdir()
    for month in sorted(months):
        prepared = []
        for record in months[month]:
            refs = {ref["revision"]: ({**ref, "legacy": True} if record.get("legacy") else ref) for ref in record.get("revisionRefs", [])}
            body = {k: v for k, v in record.items() if k not in {"revisionRefs", "_priorRevisions"}}
            for revision in [*record.get("_priorRevisions", []), body]:
                raw = canonical_json_bytes(revision)
                name = f'{revision["marketDate"]}.{revision["revision"]}.json'
                (revision_dir / name).write_bytes(raw)
                refs[revision["revision"]] = {"revision": revision["revision"],
                    "path": f"/data/archive/v1/revisions/{name}", "sha256": hashlib.sha256(raw).hexdigest(),
                    "runId": revision["runId"], "legacy": bool(revision.get("legacy", not revision.get("payloadHash")))}
            prepared.append({**body, "revisionRefs": list(refs.values())})
        payload = _month_payload(month, prepared); filename = month_filename(month, payload)
        (month_dir / filename).write_bytes(payload)
        dates = [r["marketDate"] for r in months[month]]
        metadata.append({"month": month, "path": f"/data/archive/v1/months/{filename}", "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "marketDateStart": min(dates), "marketDateEnd": max(dates), "marketDates": sorted(dates), "recordCount": len(dates)})
    all_dates = [r["marketDate"] for rs in months.values() for r in rs]
    index = {"schemaVersion": INDEX_VERSION, "generatedAt": generated_at or "", "retentionDays": 366, "earliestMarketDate": min(all_dates) if all_dates else None, "latestMarketDate": max(all_dates) if all_dates else None, "months": metadata}
    (target / "index.json").write_bytes(canonical_json_bytes(index))
    archive.mkdir(parents=True, exist_ok=True); (archive / "months").mkdir(exist_ok=True)
    (archive / "revisions").mkdir(exist_ok=True)
    for f in revision_dir.iterdir():
        destination = archive / "revisions" / f.name
        if destination.exists() and destination.read_bytes() != f.read_bytes():
            raise ValueError("immutable revision collision: " + f.name)
        os.replace(f, destination)
    for f in month_dir.iterdir(): os.replace(f, archive / "months" / f.name)
    tmp = archive / "index.json.tmp"; tmp.write_bytes(canonical_json_bytes(index)); os.replace(tmp, archive / "index.json")
    shutil.rmtree(target.parent.parent, ignore_errors=True)
    return index


def project_export_to_history(export: dict[str, Any]) -> dict[str, Any]:
    from pipeline.screening_export import validate_export
    errors = validate_export(export)
    if errors:
        raise ValueError("invalid screening export: " + ",".join(errors))
    selected = {stock["code"]: stock for stock in export["selectedStocks"]}
    rankings = {}
    for strategy in STRATEGIES:
        rankings[strategy] = []
        for row in export["strategies"][strategy]:
            stock = selected[row["code"]]
            membership = next(item for item in stock["strategies"] if item["strategy"] == strategy)
            value_key = {'trust': 'currentPeg', 'growth': 'growthTotalReturnPe', 'lowPosition': 'currentPrice'}[strategy]
            value_label = {'trust': 'PEG', 'growth': '總報酬本益比', 'lowPosition': '現價'}[strategy]
            rankings[strategy].append({**row, "value": stock["metrics"].get(value_key), "valueLabel": value_label, "name": stock["name"], "sector": stock["sector"],
                **stock["metrics"], "status": membership["status"], "reason": membership["reason"]})
    record = project_release_to_history({**export, "rankings": rankings})
    record = {**record, "screeningExportRevision": export["revision"], "payloadHash": export["payloadHash"],
        "requestId": export["requestId"], "sourceGitCommit": export["sourceGitCommit"],
        "actionsRunId": export["actionsRunId"], "legacy": export["legacy"],
        "selectedStocks": export["selectedStocks"]}
    record["revision"] = revision_for_record(record)
    return record
