"""Public MOPS request builders and HTML table parser."""
from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import math
import re
from typing import Any

MOPS_HOST = "mopsov.twse.com.tw"
MOPS_ENDPOINTS = {
    "balance": "/mops/web/ajax_t164sb03",
    "income": "/mops/web/ajax_t164sb04",
    "cashflow": "/mops/web/ajax_t164sb05",
    "monthly_revenue": "/mops/web/ajax_t05st10_ifrs",
    "insider": "/mops/web/ajax_stapap1",
}


def build_historical_form(
    market: str,
    code: str,
    *,
    year: str,
    season: str | None = None,
    month: str | None = None,
    endpoint: str = "financial",
) -> dict[str, str]:
    """Build the public MOPS form used by the historical AJAX endpoints."""
    if market not in {"sii", "otc"}:
        raise ValueError("market must be sii or otc")
    if not re.fullmatch(r"\d{4,6}", str(code)):
        raise ValueError("code must be 4-6 ASCII digits")
    if endpoint not in {"financial", "insider"}:
        raise ValueError("endpoint must be financial or insider")
    if not re.fullmatch(r"\d{3}", str(year)):
        raise ValueError("year must be a three-digit ROC year")
    if (season is None) == (month is None):
        raise ValueError("provide exactly one of season or month")
    if season is not None and season not in {"01", "02", "03", "04"}:
        raise ValueError("season must be 01, 02, 03, or 04")
    if month is not None and month not in {f"{i:02d}" for i in range(1, 13)}:
        raise ValueError("month must be 01..12")
    form = {
        "step": "0" if endpoint == "insider" else "1",
        "firstin": "true" if endpoint == "insider" else "ture",
        "off": "1",
        "keyword4": "",
        "code1": "",
        "TYPEK2": "",
        "checkbtn": "",
        "queryName": "co_id",
        "inpuType": "co_id",
        "TYPEK": market,
        "isnew": "false",
        "co_id": code,
        "year": year,
    }
    if season is not None:
        form["season"] = season
    if month is not None:
        form["month"] = month
    return form


class _TableParser(HTMLParser):
    """Collect every HTML table row as a list of cell strings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._cell_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._cell_tag = tag
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = re.sub(r"\s+", " ", unescape("".join(self._cell))).strip()
            self._row.append(value)
            self._cell = None
            self._cell_tag = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _label_key(value: str) -> str:
    return re.sub(r"\s+", "", _compact_text(value))


def parse_number(value: Any) -> float | None:
    """Parse a MOPS numeric cell; blank markers are missing, not zero."""
    if value is None:
        return None
    text = _compact_text(str(value)).replace(",", "").replace("%", "")
    if text in {"", "-", "－", "—", "–", "N/A", "n/a", "NA"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid number: {value!r}") from exc
    if not math.isfinite(number):
        raise ValueError("number must be finite")
    return -number if negative else number


def _requested_period_key(value: str) -> str:
    return re.sub(r"\s+", "", _compact_text(value))


def parse_mops_html(
    html_text: str,
    *,
    code: str,
    market: str,
    requested_period: str,
) -> dict[str, Any]:
    """Parse a public MOPS response without interpreting financial semantics."""
    if not isinstance(html_text, str) or not html_text.strip():
        raise ValueError("MOPS response is empty")
    parser = _TableParser()
    parser.feed(html_text)
    rows = [
        {"label": cells[0], "values": cells[1:]}
        for cells in parser.rows
        if cells and cells[0]
    ]
    flat = _compact_text(html_text)
    normalized_flat = _requested_period_key(flat)
    requested_key = _requested_period_key(requested_period)
    period_match = requested_key in normalized_flat
    observed_periods = sorted(
        set(re.findall(r"民國\d{3}年第\d季|民國\d{3}年\d{2}月|資料年月[:：]?\d{5,6}", flat))
    )
    unit_match = re.search(r"單位：\s*([^<]+)", html_text)
    unit = _compact_text(unit_match.group(1)) if unit_match else None
    return {
        "code": str(code),
        "market": market,
        "requested_period": requested_period,
        "period_match": period_match,
        "observed_periods": observed_periods,
        "unit": unit,
        "rows": rows,
        "table_count": len(parser.rows),
        "response_markers": {
            "has_html": "<html" in html_text.lower(),
            "has_table": bool(parser.rows),
            "has_error_text": any(x in flat for x in ("查無資料", "無此資料", "請輸入公司代號")),
        },
    }


def select_unique_row(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    """Return one exact label row; duplicate aggregate labels are fatal."""
    wanted = _label_key(label)
    matches = [row for row in rows if _label_key(str(row.get("label", ""))) == wanted]
    if not matches:
        raise KeyError(f"MOPS row not found: {label}")
    if len(matches) != 1:
        populated: list[dict[str, Any]] = []
        for row in matches:
            try:
                if any(parse_number(value) is not None for value in row.get("values", [])):
                    populated.append(row)
            except ValueError:
                continue
        if len(populated) == 1:
            return populated[0]
        raise ValueError(f"duplicate MOPS row: {label}")
    return matches[0]


def row_numbers(row: dict[str, Any]) -> list[float | None]:
    """Parse all value cells in a selected row, preserving missing cells."""
    return [parse_number(value) for value in row.get("values", [])]
