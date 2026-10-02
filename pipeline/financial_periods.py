"""Calendar and statement-period normalization; no interpolated financial values."""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Iterable

INCOME_FIELDS = ("revenue", "grossProfit", "operatingProfit", "pretaxProfit", "pretaxNetIncome", "netIncome", "parentNetIncome", "eps")


def number(value: Any) -> float | None:
    try:
        result = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def gregorian_year(value: Any) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year + 1911 if 1 <= year <= 300 else year if 1900 <= year <= 2200 else None


def normalized_date(value: Any) -> str | None:
    text = str(value or "").strip()
    parts = re.findall(r"\d+", text)
    if len(parts) == 1:
        digits = parts[0]
        width = 4 if len(digits) in (6, 8) and digits[:2] in ("19", "20", "21") else 3
        parts = [digits[:width], digits[width:width + 2], digits[width + 2:width + 4]]
    if len(parts) < 2 or (year := gregorian_year(parts[0])) is None:
        return None
    try:
        month = int(parts[1])
        day = int(parts[2]) if len(parts) > 2 and parts[2] else 1
        parsed = date(year, month, day)
    except ValueError:
        return None
    return parsed.isoformat() if len(parts) > 2 and parts[2] else parsed.isoformat()[:7]


def normalized_period(row: dict[str, Any]) -> tuple[int, int] | None:
    year = gregorian_year(row.get("year"))
    try:
        quarter = int(row.get("quarter"))
    except (TypeError, ValueError):
        return None
    return (year, quarter) if year and quarter in (1, 2, 3, 4) else None


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if (year := gregorian_year(row.get("year"))) is not None:
        result["year"] = year
    if (period := normalized_period(row)) is not None:
        result["quarter"] = period[1]
    for field in ("month", "date", "periodEnd", "availableAt", "publishedAt", "boardDate", "exDate", "paymentDate"):
        if row.get(field) and (value := normalized_date(row[field])):
            result[field] = value[:7] if field == "month" else value
    return result


def compatible_rows(rows: Iterable[dict[str, Any]], *, eps: bool = False) -> bool:
    values = list(rows)
    fields = ("currency", "statementScope", "accountingBasis", "restatementBasis") + (("epsBasis",) if eps else ("amountUnit",))
    return all(len({str(row[field]) for row in values if row.get(field) is not None}) <= 1 for field in fields) and not any(row.get("epsComparable") is False for row in values if eps)


def quarterly_income(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recover additive quarterly values from adjacent compatible YTD reports.

    EPS YTD subtraction additionally requires an explicitly shared EPS basis
    and unchanged weighted-average shares. Missing predecessors remain unknown.
    Explicit reported quarters always take precedence over cumulative snapshots.
    """
    normalized = [normalize_row(row) for row in rows if isinstance(row, dict) and normalized_period(row)]
    ytd = {normalized_period(row): row for row in normalized if row.get("periodType") == "ytd"}
    result: dict[tuple[int, int], dict[str, Any]] = {}
    for row in normalized:
        key = normalized_period(row)
        assert key is not None
        item = dict(row)
        if row.get("periodType") == "ytd":
            previous = ytd.get((key[0], key[1] - 1))
            item["cumulativeValues"] = {field: row[field] for field in INCOME_FIELDS if row.get(field) is not None}
            for field in INCOME_FIELDS:
                value = number(row.get(field))
                if key[1] == 1:
                    item[field] = value
                elif previous and compatible_rows([row, previous]):
                    before = number(previous.get(field))
                    eps_safe = field != "eps" or (row.get("epsBasis") is not None and row.get("epsBasis") == previous.get("epsBasis") and row.get("weightedAverageShares") is not None and row.get("weightedAverageShares") == previous.get("weightedAverageShares"))
                    item[field] = value - before if value is not None and before is not None and eps_safe else None
                else:
                    item[field] = None
            item["periodType"] = "quarter"
            item["inputOrigin"] = ("derived" if key[1] > 1 else "reported") if any(number(item.get(field)) is not None for field in INCOME_FIELDS) else "unavailable"
            item["derivationMethod"] = "compatible_ytd_difference" if key[1] > 1 else "first_quarter_ytd"
        existing = result.get(key, {})
        if existing and row.get("periodType") != "ytd" and not any(number(item.get(field)) is not None for field in INCOME_FIELDS):
            # An empty financial overlay cannot establish new units or source.
            continue
        if row.get("periodType") != "ytd" and not row.get("derivationMethod") and (existing.get("derivationMethod") or not compatible_rows([existing, item])):
            # Replace recovered or incompatible rows as a whole: unsupplied
            # amounts cannot inherit the direct report's source or units.
            # The cumulative evidence remains separately in incomeYtd.
            existing = {}
        if row.get("periodType") == "ytd" and existing.get("derivationMethod") is None and existing:
            continue
        result[key] = {**existing, **{field: value for field, value in item.items() if value is not None and (field not in INCOME_FIELDS or number(value) is not None)}}
    return [result[key] for key in sorted(result)]


def dividend_period(value: Any, year: Any = None) -> tuple[int, str] | None:
    """Identify an annual/quarter/half distribution, never an event-date period."""
    text = str(value or "").strip().upper().replace(" ", "")
    if year is not None and text in {"ANNUAL", "Q1", "Q2", "Q3", "Q4", "H1", "H2"}:
        normalized_year = gregorian_year(year)
        return (normalized_year, "annual" if text == "ANNUAL" else text) if normalized_year else None
    if year is not None and (text in {"年度", "全年", "上半年度", "下半年度"} or re.fullmatch(r"第[1-4]季", text)):
        text = str(year) + ("年全年" if text == "全年" else text)
    annual = re.fullmatch(r"(\d{2,4})(?:年(?:度|全年)?)?", text)
    quarter = re.fullmatch(r"(\d{2,4})(?:年?第?)?(?:Q([1-4])|([1-4])季)", text)
    half = re.fullmatch(r"(\d{2,4})(?:年)?(?:H([12])|(上|下)半年度?)", text)
    match = annual or quarter or half
    if match is None:
        return None
    normalized_year = gregorian_year(match.group(1))
    if normalized_year is None or (year is not None and gregorian_year(year) != normalized_year):
        return None
    label = "annual" if annual else "Q" + (quarter.group(2) or quarter.group(3)) if quarter else "H" + (half.group(2) or ("1" if half.group(3) == "上" else "2"))
    return normalized_year, label
