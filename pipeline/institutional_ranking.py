"""Pure helpers for official institutional-rank snapshots."""

from __future__ import annotations

from typing import Any


def _rank_value(row: dict[str, Any]) -> int | None:
    raw = row.get("rank")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _code_value(row: dict[str, Any]) -> str:
    return str(row.get("code") or "").strip().upper()


def annotate_top_n_entries(
    current_rows: list[dict[str, Any]],
    previous_rows: list[dict[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return current top-N rows with an honest previous-rank status.

    ``previous_rows`` may contain more than N rows.  Keeping those rows lets a
    current top-N member that was ranked 11+ yesterday be labelled as a true
    new entry instead of being mistaken for a never-seen code.
    """

    if limit <= 0:
        return []

    current = [
        row for row in current_rows
        if _rank_value(row) is not None and _code_value(row)
    ]
    current.sort(key=lambda row: (_rank_value(row) or 10**9, _code_value(row)))
    current = current[:limit]

    previous_rank_by_code: dict[str, int] = {}
    for row in previous_rows:
        code = _code_value(row)
        rank = _rank_value(row)
        if code and rank is not None:
            previous_rank_by_code.setdefault(code, rank)

    has_previous_snapshot = bool(previous_rank_by_code)
    result: list[dict[str, Any]] = []
    for display_rank, row in enumerate(current, start=1):
        source_rank = _rank_value(row)
        code = _code_value(row)
        previous_rank = previous_rank_by_code.get(code)
        if not has_previous_snapshot:
            entry_status = "unknown"
        elif previous_rank is None or previous_rank > limit:
            entry_status = "new"
        else:
            entry_status = "retained"
        result.append(
            {
                **row,
                "code": code,
                "rank": display_rank,
                "sourceRank": source_rank,
                "previousRank": previous_rank,
                "entryStatus": entry_status,
            }
        )
    return result
