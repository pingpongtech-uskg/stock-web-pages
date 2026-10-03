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
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.institutional_ranking import annotate_top_n_entries  # noqa: E402
from pipeline.official_institutional import (  # noqa: E402
    TPEX_SOURCE,
    TWSE_SOURCE,
    aggregate_window,
    fetch_recent_complete_days,
    rank_adjacent_windows,
    OfficialInstitutionalError,
)

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


def stale_previous_config(path: Path, reason: str) -> dict[str, Any]:
    """Return a marked stale copy without mutating the tracked config."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"previous universe config unavailable: {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list) or not payload["symbols"]:
        raise ValueError(f"previous universe config is incomplete: {path}")
    return {
        **payload,
        "stale": True,
        "staleReason": reason,
        "staleAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


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
        "stale": False,
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


def update_official_tracked_config(
    snapshots: list[dict[str, Any]],
    path: Path,
    *,
    limit: int = 100,
) -> dict[str, Any]:
    """Persist the official cross-market ten-session institutional universe."""

    current, previous = rank_adjacent_windows(snapshots, window=10)
    current_rows = annotate_top_n_entries(current, previous, limit=limit)
    current_top10 = annotate_top_n_entries(current, previous, limit=10)
    top10_by_code = {str(row["code"]): row for row in current_top10}
    tracked_codes = {str(row["code"]) for row in current_rows}
    # Keep daily source rows for the current universe. The aggregate rank alone
    # cannot reproduce positiveDays10 or participation10 on the next refresh.
    daily_rows = []
    for snapshot in snapshots[:10]:
        day = str(snapshot.get("date") or "")[:10]
        rows = []
        for raw_row in snapshot.get("rows", []):
            if not isinstance(raw_row, dict) or str(raw_row.get("code") or "") not in tracked_codes:
                continue
            rows.append({
                "code": str(raw_row.get("code") or ""),
                "name": str(raw_row.get("name") or ""),
                "market": str(raw_row.get("market") or ""),
                "buyShares": raw_row.get("buyShares"),
                "sellShares": raw_row.get("sellShares"),
                "netShares": raw_row.get("netShares"),
            })
        daily_rows.append({"date": day, "rows": rows})

    previous_config: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous_config = loaded
        except (OSError, ValueError, json.JSONDecodeError):
            previous_config = {}
    raw_metadata = previous_config.get("metadata")
    previous_metadata: dict[str, dict[str, Any]] = {
        str(key): value
        for key, value in raw_metadata.items()
        if isinstance(value, dict)
    } if isinstance(raw_metadata, dict) else {}

    rows: list[dict[str, Any]] = []
    metadata: dict[str, dict[str, Any]] = {}
    for row in current_rows:
        code = str(row["code"])
        old_meta = previous_metadata.get(code, {})
        name = str(row.get("name") or old_meta.get("name") or code)
        metadata[code] = {**old_meta, "name": name, "market": row.get("market", old_meta.get("market", "unknown"))}
        top10_row = top10_by_code.get(code)
        previous_rank = top10_row.get("previousRank") if top10_row is not None else row.get("previousRank")
        entry_status = top10_row.get("entryStatus", "not_applicable") if top10_row is not None else "not_applicable"
        rows.append(
            {
                "rank": int(row["rank"]),
                "sourceRank": int(row.get("sourceRank") or row["rank"]),
                "code": code,
                "name": name,
                "market": str(row.get("market") or old_meta.get("market") or "unknown"),
                "netShares": int(row["netShares"]),
                # Compatibility field for older readers; it is still shares,
                # never mislabeled as lots.
                "net": str(int(row["netShares"])),
                "previousRank": previous_rank,
                "entryStatus": entry_status,
            }
        )

    market_dates = [str(snapshot["date"]) for snapshot in snapshots[:10]]
    previous_market_dates = [str(snapshot["date"]) for snapshot in snapshots[1:11]]
    payload = {
        "stale": False,
        "symbols": [row["code"] for row in rows],
        "metadata": {code: metadata[code] for code in [row["code"] for row in rows]},
        "purpose": "A：TWSE＋TPEx 官方投信十日買賣超前100；所有策略共用此研究母體",
        "universe": {
            "id": "A",
            "label": "官方投信十日買超前100",
            "sourceUrl": "https://www.twse.com.tw/zh/trading/foreign/twt44u.html + https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/domestic-inst/day.html",
            "sourceUrls": [TWSE_SOURCE, TPEX_SOURCE],
            "sourceMethod": "兩市場每日投信買進／賣出；TPEx 張數轉股；最近10個市場日累積；不在子集合內重算",
            "asOfFetchedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "marketDates": market_dates,
            "previousMarketDates": previous_market_dates,
            "rows": rows,
            "previousRows": previous[:limit],
            "top10": current_top10,
            "previousTop10": previous[:10],
            "dailyRows": daily_rows,
        },
        "updated_at": market_dates[0] if market_dates else datetime.now(timezone.utc).date().isoformat(),
    }
    atomic_json(path, payload)
    return payload


def fetch_official_universe(*, limit: int = 100, as_of: date | None = None) -> dict[str, Any]:
    snapshots = fetch_recent_complete_days(as_of=as_of, sessions=11, lookback_days=35)
    return {
        "snapshots": snapshots,
        "current": aggregate_window([snapshot["rows"] for snapshot in snapshots[:10]])[:limit],
        "previous": aggregate_window([snapshot["rows"] for snapshot in snapshots[1:11]])[:limit],
    }


def _iso_date(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("as-of must use YYYY-MM-DD")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("official", "legacy"), default="official")
    parser.add_argument("--url", default=SOURCE_URL)
    parser.add_argument("--config", default=str(ROOT / "config" / "tracked_symbols.json"))
    parser.add_argument("--output", default="")
    parser.add_argument("--print-codes", action="store_true")
    parser.add_argument("--sessions", type=int, default=11, help="complete sessions to fetch; 11 supports adjacent 10-session windows")
    parser.add_argument("--lookback-days", type=int, default=35)
    parser.add_argument("--as-of", type=_iso_date, help="latest requested official market date (YYYY-MM-DD)")
    parser.add_argument("--allow-stale", action="store_true", help="keep the last complete universe when the official source is unavailable")
    args = parser.parse_args()
    try:
        if args.source == "official":
            snapshots = fetch_recent_complete_days(as_of=args.as_of, sessions=args.sessions, lookback_days=args.lookback_days)
            payload = update_official_tracked_config(snapshots, Path(args.config))
        else:
            rows = parse_rankings(fetch_document(args.url))
            payload = update_tracked_config(rows, Path(args.config), args.url)
        if args.output:
            atomic_json(Path(args.output), payload)
    except (OSError, ValueError, urllib.error.URLError, OfficialInstitutionalError) as exc:
        if args.allow_stale:
            try:
                payload = stale_previous_config(Path(args.config), f"{type(exc).__name__}: {exc}")
                if args.output:
                    atomic_json(Path(args.output), payload)
                print(json.dumps({"universe": "A", "stale": True, "reason": payload["staleReason"]}, ensure_ascii=False, sort_keys=True))
                return 0
            except (OSError, ValueError, json.JSONDecodeError) as fallback_exc:
                print(f"research_universe_stale_fallback_failed={type(fallback_exc).__name__}: {fallback_exc}")
                return 1
        print(f"research_universe_failed={type(exc).__name__}: {exc}")
        return 1
    if args.print_codes:
        print(",".join(payload["symbols"]))
    elif args.source == "official":
        print(json.dumps({
            "universe": "A",
            "label": payload["universe"]["label"],
            "count": len(payload["symbols"]),
            "marketDates": payload["universe"]["marketDates"],
            "top10": payload["universe"]["top10"],
            "source": payload["universe"]["sourceUrls"],
        }, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps({"universe": "A", "label": "投信十日買超前100", "count": len(payload["symbols"]), "source": args.url}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
