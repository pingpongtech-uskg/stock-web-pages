#!/usr/bin/env python3
"""Fetch the public A universe: the published ten-session investment-trust rank.

The ranking is an input to every strategy.  We do not recompute it from the
subset we happen to have fetched; the source publishes the rank first and the
rest of the pipeline only evaluates those 100 symbols.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://stock.wearn.com/b50.asp"
USER_AGENT = "taiwan-stock-screener/0.1 (public ranking universe)"
CODE_RE = re.compile(r"^[0-9A-Z]{4,6}$")


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(clean_text(" ".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def parse_rankings(document: str, *, limit: int = 100) -> list[dict[str, Any]]:
    parser = TableParser()
    parser.feed(document)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cells in parser.rows:
        if len(cells) < 3:
            continue
        if not re.fullmatch(r"\d{1,3}", cells[0]):
            continue
        rank = int(cells[0])
        if rank < 1 or rank > 250:
            continue
        code = re.sub(r"[^0-9A-Z]", "", cells[1].upper())
        if not CODE_RE.fullmatch(code) or code in seen:
            continue
        # The first table is the positive investment-trust ranking.  Stop
        # once a page starts the separate sell ranking.
        row_text = " ".join(cells)
        if "投信賣超" in row_text or "賣超金額" in row_text:
            break
        seen.add(code)
        rows.append({
            "rank": rank,
            "code": code,
            "name": cells[2],
            "buy": cells[3] if len(cells) > 3 else None,
            "sell": cells[4] if len(cells) > 4 else None,
            "net": cells[5] if len(cells) > 5 else None,
        })
        if len(rows) >= limit:
            break
    if len(rows) < limit:
        raise ValueError(f"public ranking returned only {len(rows)} usable rows; expected {limit}")
    return rows


def fetch_document(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def update_tracked_config(rows: list[dict[str, Any]], path: Path, source_url: str) -> dict[str, Any]:
    previous: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (OSError, ValueError, json.JSONDecodeError):
            previous = {}
    metadata = previous.get("metadata") if isinstance(previous.get("metadata"), dict) else {}
    for row in rows:
        code = row["code"]
        current = metadata.get(code) if isinstance(metadata.get(code), dict) else {}
        metadata[code] = {**current, "name": row["name"]}
    payload = {
        "symbols": [row["code"] for row in rows],
        "metadata": {code: metadata[code] for code in [row["code"] for row in rows] if code in metadata},
        "purpose": "A：公開投信十日買超前100；所有策略共用此研究母體",
        "universe": {
            "id": "A",
            "label": "投信十日買超前100",
            "sourceUrl": source_url,
            "sourceMethod": "公開排行原表；不在子集合內重新計算排名",
            "asOfFetchedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "rows": rows,
        },
        "updated_at": datetime.now(timezone.utc).date().isoformat(),
    }
    atomic_json(path, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=SOURCE_URL)
    parser.add_argument("--config", default=str(ROOT / "config" / "tracked_symbols.json"))
    parser.add_argument("--output", default="")
    parser.add_argument("--print-codes", action="store_true")
    args = parser.parse_args()
    try:
        rows = parse_rankings(fetch_document(args.url))
        payload = update_tracked_config(rows, Path(args.config), args.url)
        if args.output:
            atomic_json(Path(args.output), payload)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"research_universe_failed={type(exc).__name__}: {exc}")
        return 1
    if args.print_codes:
        print(",".join(payload["symbols"]))
    else:
        print(json.dumps({"universe": "A", "label": "投信十日買超前100", "count": len(payload["symbols"]), "source": args.url}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
