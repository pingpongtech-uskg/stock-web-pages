#!/usr/bin/env python3
"""Typed validation for public-source normalized snapshots."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

STATUS = frozenset({"PASS", "FAIL", "UNKNOWN", "BLOCKED"})
AUTHORITY = frozenset({"official_primary", "official_crosscheck", "free_secondary", "reference_only"})
SCOPE = frozenset({"consolidated", "standalone", "unknown"})
REQUIRED_FIELD_KEYS = frozenset(
    {
        "canonical_name",
        "source_label",
        "value",
        "unit",
        "status",
        "reason",
        "source_id",
        "source_url",
        "period",
        "published_at",
    }
)
REQUIRED_SNAPSHOT_KEYS = frozenset(
    {
        "entity",
        "as_of",
        "period",
        "published_at",
        "retrieved_at_utc",
        "source_id",
        "source_url",
        "http_status",
        "row_count",
        "raw_snapshot_id",
        "parser_version",
        "schema_version",
        "formula_version",
        "authority",
        "scope",
        "fields",
    }
)


def _allowed_hosts() -> set[str]:
    path = Path(__file__).resolve().parents[1] / "calibration" / "source_registry.json"
    with path.open(encoding="utf-8") as handle:
        registry = json.load(handle)
    return set(registry["policy"]["allowed_hosts"])


def _validate_url(value: Any, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty URL")
    parsed = urlsplit(value)
    if parsed.scheme != "https":
        raise ValueError(f"{name} must use HTTPS")
    if parsed.hostname not in _allowed_hosts():
        raise ValueError(f"{name} host is not allow-listed")
    lowered = value.lower()
    if any(token in lowered for token in ("password", "token=", "cookie", "authorization", "api_key", "apikey")):
        raise ValueError(f"{name} contains a forbidden credential marker")


def _validate_finite(value: Any, path: str) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{path} must be finite")
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_finite(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite(child, f"{path}[{index}]")


def _validate_date(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty date string")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601 compatible") from exc


def validate_field_record(field: Any) -> None:
    if not isinstance(field, dict):
        raise ValueError("field record must be an object")
    missing = REQUIRED_FIELD_KEYS - field.keys()
    if missing:
        raise ValueError(f"field record missing required keys: {', '.join(sorted(missing))}")
    if not isinstance(field["canonical_name"], str) or not field["canonical_name"]:
        raise ValueError("canonical_name must be non-empty")
    if field["status"] not in STATUS:
        raise ValueError("field status is invalid")
    value = field["value"]
    if value is not None and not isinstance(value, (int, float)):
        raise ValueError("field value must be numeric or null")
    _validate_finite(value, "field.value")
    if field["status"] == "PASS" and value is None:
        raise ValueError("PASS field must have a value")
    if field["status"] in {"UNKNOWN", "BLOCKED"} and value is not None:
        raise ValueError(f"{field['status']} field must have null value")
    if field["reason"] is not None and not isinstance(field["reason"], str):
        raise ValueError("field reason must be string or null")
    _validate_url(field["source_url"], name="field source_url")
    for key in ("source_id", "period", "published_at"):
        if not isinstance(field[key], str) or not field[key]:
            raise ValueError(f"field {key} must be non-empty")


def validate_snapshot_record(snapshot: Any) -> None:
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")
    missing = REQUIRED_SNAPSHOT_KEYS - snapshot.keys()
    if missing:
        raise ValueError(f"snapshot missing required keys: {', '.join(sorted(missing))}")
    entity = snapshot["entity"]
    if not isinstance(entity, dict):
        raise ValueError("entity must be an object")
    if not re.fullmatch(r"\d{4,6}", str(entity.get("code", ""))):
        raise ValueError("entity.code must be 4-6 ASCII digits")
    if not isinstance(entity.get("name"), str) or not entity["name"]:
        raise ValueError("entity.name must be non-empty")
    if entity.get("market") not in {"TWSE", "TPEx"}:
        raise ValueError("entity.market must be TWSE or TPEx")
    if entity.get("ordinary_share") is not True:
        raise ValueError("entity.ordinary_share must be true")
    _validate_date(snapshot["as_of"], "as_of")
    _validate_date(snapshot["published_at"], "published_at")
    if not isinstance(snapshot["retrieved_at_utc"], str) or not snapshot["retrieved_at_utc"].endswith("Z"):
        raise ValueError("retrieved_at_utc must end in Z")
    _validate_date(snapshot["retrieved_at_utc"], "retrieved_at_utc")
    _validate_url(snapshot["source_url"], name="source_url")
    if not isinstance(snapshot["http_status"], int) or snapshot["http_status"] < 0:
        raise ValueError("http_status must be a non-negative integer")
    if not isinstance(snapshot["row_count"], int) or snapshot["row_count"] < 0:
        raise ValueError("row_count must be a non-negative integer")
    if not isinstance(snapshot["raw_snapshot_id"], str) or not snapshot["raw_snapshot_id"].startswith("sha256:"):
        raise ValueError("raw_snapshot_id must start with sha256:")
    if snapshot["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    for key in ("period", "source_id", "parser_version", "formula_version"):
        if not isinstance(snapshot[key], str) or not snapshot[key]:
            raise ValueError(f"snapshot {key} must be non-empty")
    if snapshot["authority"] not in AUTHORITY:
        raise ValueError("snapshot authority is invalid")
    if snapshot["scope"] not in SCOPE:
        raise ValueError("snapshot scope is invalid")
    fields = snapshot["fields"]
    if not isinstance(fields, dict):
        raise ValueError("snapshot fields must be an object")
    for name, field in fields.items():
        if name != field.get("canonical_name"):
            raise ValueError(f"field key does not match canonical_name: {name}")
        validate_field_record(field)
    _validate_finite(snapshot, "snapshot")
