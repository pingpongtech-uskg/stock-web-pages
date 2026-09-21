"""Normalization for the frozen TDCC/MOPS ownership reference contract."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import math
import re
from typing import Any, Iterable

SCHEMA_VERSION = "ownership-v1"
DIRECTOR_SCOPE = ("董事長本人", "董事本人", "獨立董事本人", "監察人本人")


def _text(value: Any) -> str:
    return str(value or "").replace("\u3000", " ").strip()


def _number(value: Any) -> float | None:
    text = _text(value).replace(",", "").replace("%", "")
    if not text or text in {"-", "--", "—", "…", "N/A", "無"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _date(value: Any) -> str | None:
    text = _text(value)[:10].replace("/", "-")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _month(value: Any) -> str | None:
    text = _text(value)[:7].replace("/", "-")
    if re.fullmatch(r"\d{4}-\d{2}", text):
        try:
            date.fromisoformat(f"{text}-01")
        except ValueError:
            return None
        return text
    parsed = _date(value)
    return parsed[:7] if parsed else None


def _base(code: str, period: str, *, retrieved_at: str | None, source: str, dataset: str, snapshot_id: str | None) -> dict[str, Any]:
    return {
        "code": code, "market": "TWSE", "period": period, "asOf": None,
        "publishedAt": None, "retrievedAt": retrieved_at,
        "largeHolderPct": None, "directorSupervisorPct": None, "shareholderCount": None,
        "source": source, "dataset": dataset, "snapshotId": snapshot_id,
        "schemaVersion": SCHEMA_VERSION,
    }


def normalize_tdcc_rows(
    rows: Iterable[dict[str, Any]], *, retrieved_at: str | None = None,
    snapshot_id: str | None = None, source: str = "TDCC", dataset: str = "1-5",
) -> list[dict[str, Any]]:
    """Collapse TDCC weekly 1-5 rows to each code's latest published week/month.

    The frozen mapping is class 15 for percentage (TDCC labels it
    ``1,000,001以上``); class 16 is a difference adjustment and is not a
    holding band. Class 17 supplies the official total shareholder count.
    Missing values remain ``None``.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = re.sub(r"\s+", "", _text(row.get("證券代號") or row.get("code")))
        as_of = _date(row.get("資料日期") or row.get("asOf"))
        period = as_of[:7] if as_of else _month(row.get("period"))
        if code and period and as_of:
            grouped[(code, period)].append({**row, "_asOf": as_of})
    result = []
    for (code, period), candidates in sorted(grouped.items()):
        latest = max(row["_asOf"] for row in candidates)
        selected = [row for row in candidates if row["_asOf"] == latest]
        item = _base(code, period, retrieved_at=retrieved_at, source=source, dataset=dataset, snapshot_id=snapshot_id)
        item["asOf"] = latest
        item["publishedAt"] = next((row.get("發布日期") or row.get("publishedAt") for row in selected if row.get("發布日期") or row.get("publishedAt")), None)
        pct_values = [_number(row.get("占集保庫存數比例%")) for row in selected if _text(row.get("持股分級")) == "15"]
        pct = sum(value for value in pct_values if value is not None)
        count = next((_number(row.get("人數")) for row in selected if _text(row.get("持股分級")) == "17"), None)
        item["largeHolderPct"] = round(pct, 10) if pct_values and all(value is not None for value in pct_values) else None
        item["shareholderCount"] = int(count) if count is not None and count.is_integer() else count
        item["sourceRefs"] = [f"{source}:{dataset}:{latest}"]
        result.append(item)
    return result


def normalize_director_rows(
    rows: Iterable[dict[str, Any]], *, retrieved_at: str | None = None,
    snapshot_id: str | None = None, source: str = "TWSE OpenAPI", dataset: str = "t187ap11_L/P",
) -> list[dict[str, Any]]:
    """Normalize monthly director holdings, excluding representatives/managers."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = re.sub(r"\s+", "", _text(row.get("職稱") or row.get("title")))
        if title not in DIRECTOR_SCOPE:
            continue
        code = re.sub(r"\s+", "", _text(row.get("公司代號") or row.get("code")))
        period = _month(row.get("資料年月") or row.get("period"))
        holding = _number(row.get("目前持股") or row.get("holding"))
        denominator = _number(row.get("已發行普通股數") or row.get("issuedCommonShares") or row.get("denominator"))
        if code and period and holding is not None:
            grouped[(code, period)].append({"title": title, "holding": holding, "denominator": denominator, "row": row})
    result = []
    for (code, period), entries in sorted(grouped.items()):
        denominators = {entry["denominator"] for entry in entries}
        denominator = next(iter(denominators)) if len(denominators) == 1 and next(iter(denominators)) is not None and next(iter(denominators)) > 0 else None
        item = _base(code, period, retrieved_at=retrieved_at, source=source, dataset=dataset, snapshot_id=snapshot_id)
        item["directorDenominator"] = denominator
        item["directorScope"] = sorted({entry["title"] for entry in entries}, key=DIRECTOR_SCOPE.index)
        item["directorSupervisorPct"] = round(sum(entry["holding"] for entry in entries) / denominator * 100, 10) if denominator else None
        item["asOf"] = period
        item["sourceRefs"] = [f"{source}:{dataset}:{period}"]
        result.append(item)
    return result


def merge_ownership_rows(*collections: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge normalized source rows by code/month without inventing missing values."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for collection in collections:
        for row in collection:
            if not isinstance(row, dict) or not row.get("code") or not row.get("period"):
                continue
            key = (str(row["code"]), str(row["period"]))
            current = merged.setdefault(key, dict(row))
            for field, value in row.items():
                if value is not None and (current.get(field) is None or field in {"sourceRefs", "directorScope"}):
                    current[field] = list(dict.fromkeys([*(current.get(field) or []), *(value or [])])) if field in {"sourceRefs", "directorScope"} else value
    return [merged[key] for key in sorted(merged)]


# Descriptive aliases retained for callers that name each official dataset.
normalize_tdcc_ownership = normalize_tdcc_rows
normalize_twse_director_ownership = normalize_director_rows
normalize_ownership_inputs = merge_ownership_rows
