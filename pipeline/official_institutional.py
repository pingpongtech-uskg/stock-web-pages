"""Official daily investment-trust flow collection and ranking.

TWSE reports shares. TPEx reports lots. This module normalizes both to shares
before combining the two markets, then exposes adjacent ten-session windows so
"new entry" means a real rank transition rather than a subset re-rank.
"""

from __future__ import annotations

import json
import csv
import io
import base64
import hashlib
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pipeline.release_contract import is_common_stock_code

TWSE_ENDPOINT = "https://www.twse.com.tw/rwd/zh/fund/TWT44U"
TPEX_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
TWSE_SOURCE = "TWSE:TWT44U"
TPEX_SOURCE = "TPEx:insti/dailyTrade"
USER_AGENT = "taiwan-stock-screener/official-institutional-v1"
TAIPEI = ZoneInfo("Asia/Taipei")
MAX_SOURCE_NUMBER_CHARS = 64
MAX_TPEX_REPORT_BYTES = 2_000_000
MAX_RECEIPT_BYTES = 4_000_000


class OfficialInstitutionalError(RuntimeError):
    """Raised when a complete cross-market daily report is unavailable."""


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\u3000", " ").strip()


def _clean_code(value: Any) -> str:
    return re.sub(r"\s+", "", _clean_text(value)).upper()


def _number(value: Any, *, multiplier: int = 1) -> int | None:
    """Parse exact source quantities and convert only whole shares."""

    if isinstance(value, bool):
        raise ValueError("boolean is not a source quantity")
    text = str(value if value is not None else "").replace("\u3000", " ").strip()
    if not text or text in {"-", "--", "—", "…", "N/A", "無"}:
        return None
    if len(text) > MAX_SOURCE_NUMBER_CHARS:
        raise ValueError("source quantity exceeds length limit")
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
        if text.startswith(("+", "-")):
            raise ValueError("accounting negative quantity cannot include a sign")
    elif "(" in text or ")" in text:
        raise ValueError("malformed negative source quantity")
    if not re.fullmatch(r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)", text):
        raise ValueError("malformed source quantity")
    try:
        quantity = Decimal(text.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("malformed source quantity") from exc
    if not quantity.is_finite():
        raise ValueError("non-finite source quantity")
    if negative:
        quantity = quantity.copy_negate()
    coefficient_digits = len(text.replace(",", "").replace(".", "").lstrip("+-"))
    with localcontext() as context:
        context.prec = max(1, coefficient_digits + len(str(multiplier)) + 1)
        shares = quantity * multiplier
    if shares != shares.to_integral_value():
        raise ValueError("source quantity is not a whole share")
    return int(shares)


def _is_empty_row(row: list[Any]) -> bool:
    return not any(str(value).replace("\u3000", " ").strip() for value in row if value is not None)


def _parse_amounts(row: list[Any], indexes: tuple[int, int, int], *, multiplier: int = 1) -> tuple[int | None, ...]:
    return tuple(_number(_row_value(row, index), multiplier=multiplier) for index in indexes)


def _field_index(fields: list[Any], *names: str) -> int:
    cleaned = [_clean_text(field) for field in fields]
    for name in names:
        if name in cleaned:
            return cleaned.index(name)
    raise OfficialInstitutionalError(f"missing official field: {'/'.join(names)}")


def _row_value(row: list[Any], index: int) -> Any:
    return row[index] if 0 <= index < len(row) else None


def parse_twse_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse TWSE TWT44U JSON, retaining the report's share unit."""

    fields = payload.get("fields")
    rows = payload.get("data")
    if not isinstance(fields, list) or not isinstance(rows, list):
        raise OfficialInstitutionalError("TWSE payload has no tabular data")
    code_i = _field_index(fields, "證券代號")
    name_i = _field_index(fields, "證券名稱")
    buy_i = _field_index(fields, "買進股數")
    sell_i = _field_index(fields, "賣出股數")
    net_i = _field_index(fields, "買賣超股數")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            raise OfficialInstitutionalError("TWSE report contains a malformed row")
        code = _clean_code(_row_value(row, code_i))
        if not code:
            if _is_empty_row(row):
                continue
            raise OfficialInstitutionalError("TWSE report row has no identifiable security code")
        try:
            buy, sell, net = _parse_amounts(row, (buy_i, sell_i, net_i))
        except ValueError as exc:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TWSE common-stock row contains an invalid quantity") from exc
            continue
        if buy is None or sell is None or net is None:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TWSE common-stock row is missing a quantity")
            continue
        if buy < 0 or sell < 0 or buy - sell != net:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TWSE common-stock row has inconsistent quantities")
            continue
        result.append({
            "code": code,
            "name": _clean_text(_row_value(row, name_i)),
            "market": "TWSE",
            "buyShares": buy,
            "sellShares": sell,
            "netShares": net,
        })
    return result


def _parse_twse_response(payload: bytes, *, expected_date: date) -> tuple[list[dict[str, Any]], bool]:
    try:
        response = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise OfficialInstitutionalError("TWSE report returned malformed JSON") from exc
    if not isinstance(response, dict):
        raise OfficialInstitutionalError("TWSE report returned an unexpected response")
    no_data = {"stat": "很抱歉，沒有符合條件的資料!"}
    no_data_with_totals = {**no_data, "hints": "單位：股", "total": 0}
    if response in (no_data, no_data_with_totals):
        return [], True
    if str(response.get("date") or "") != expected_date.strftime("%Y%m%d"):
        raise OfficialInstitutionalError("TWSE report date does not match the requested day")
    return parse_twse_payload(response), False


def parse_twse_json_response(payload: bytes, *, expected_date: date) -> list[dict[str, Any]]:
    """Parse exact TWSE response bytes and reject reports for another date."""

    rows, _no_data = _parse_twse_response(payload, expected_date=expected_date)
    return rows


def parse_tpex_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse TPEx daily report and convert its lot columns to shares."""

    tables = payload.get("tables")
    if not isinstance(tables, list):
        raise OfficialInstitutionalError("TPEx payload has no tables")
    table = next(
        (
            item for item in tables
            if isinstance(item, dict)
            and isinstance(item.get("fields"), list)
            and any("買賣超" in _clean_text(field) for field in item["fields"])
        ),
        None,
    )
    if not isinstance(table, dict):
        raise OfficialInstitutionalError("TPEx payload has no institutional table")
    fields = table["fields"]
    rows = table.get("data")
    if not isinstance(rows, list):
        raise OfficialInstitutionalError("TPEx institutional table has no rows")
    code_i = _field_index(fields, "代號")
    name_i = _field_index(fields, "名稱")
    buy_i = _field_index(fields, "買進")
    sell_i = _field_index(fields, "賣出")
    net_i = _field_index(fields, "買賣超(張數)", "買賣超")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            raise OfficialInstitutionalError("TPEx report contains a malformed row")
        code = _clean_code(_row_value(row, code_i))
        if not code:
            if _is_empty_row(row):
                continue
            raise OfficialInstitutionalError("TPEx report row has no identifiable security code")
        try:
            buy_shares, sell_shares, net_shares = _parse_amounts(
                row, (buy_i, sell_i, net_i), multiplier=1000)
        except ValueError as exc:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TPEx common-stock row contains an invalid quantity") from exc
            continue
        if buy_shares is None or sell_shares is None or net_shares is None:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TPEx common-stock row is missing a quantity")
            continue
        if buy_shares < 0 or sell_shares < 0 or buy_shares - sell_shares != net_shares:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TPEx common-stock row has inconsistent quantities")
            continue
        result.append({
            "code": code,
            "name": _clean_text(_row_value(row, name_i)),
            "market": "TPEx",
            "buyShares": buy_shares,
            "sellShares": sell_shares,
            "netShares": net_shares,
        })
    return result


def parse_tpex_csv(payload: bytes, *, expected_date: date) -> list[dict[str, Any]]:
    """Parse TPEx's published all-securities daily report, whose quantities are shares."""

    if not isinstance(payload, bytes) or len(payload) > MAX_TPEX_REPORT_BYTES:
        raise OfficialInstitutionalError("TPEx report exceeds the response size limit")
    try:
        text = payload.decode("cp950", errors="strict")
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise OfficialInstitutionalError("TPEx report is not a valid MS950 CSV") from exc
    if len(rows) < 2:
        raise OfficialInstitutionalError("TPEx report has no title and header")

    title = _clean_text(_row_value(rows[0], 0))
    report_date = re.match(r"^(\d{2,3})年(\d{1,2})月(\d{1,2})日", title)
    if not report_date:
        raise OfficialInstitutionalError("TPEx report has no recognizable report date")
    try:
        actual_date = date(int(report_date.group(1)) + 1911, int(report_date.group(2)), int(report_date.group(3)))
    except ValueError as exc:
        raise OfficialInstitutionalError("TPEx report contains an invalid report date") from exc
    if actual_date != expected_date:
        raise OfficialInstitutionalError(
            f"TPEx report date mismatch: expected {expected_date.isoformat()}, got {actual_date.isoformat()}"
        )

    fields = rows[1]
    if len(fields) != 24:
        raise OfficialInstitutionalError("TPEx report schema has an unexpected column count")
    code_i = _field_index(fields, "代號")
    name_i = _field_index(fields, "名稱")
    buy_i = _field_index(fields, "投信-買進股數")
    sell_i = _field_index(fields, "投信-賣出股數")
    net_i = _field_index(fields, "投信-買賣超股數")
    result: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    count_footer_seen = False
    footer_prefixes = ("*三大法人", "說明：", "外資及陸資表示", "因外資", "投信表示", "自營商表示", "本資訊", "ETF證券代號")

    for row in rows[2:]:
        if _is_empty_row(row):
            continue
        if len(row) == 1 and re.fullmatch(r"共[\d,]+筆", _clean_text(row[0])):
            if count_footer_seen:
                raise OfficialInstitutionalError("TPEx report contains duplicate row-count footers")
            reported_count = int(re.sub(r"\D", "", row[0]))
            if reported_count != len(seen_codes):
                raise OfficialInstitutionalError("TPEx report row-count footer does not match parsed rows")
            count_footer_seen = True
            continue
        if len(row) == 1 and any(_clean_text(row[0]).startswith(prefix) for prefix in footer_prefixes):
            continue
        if count_footer_seen:
            raise OfficialInstitutionalError("TPEx report has data after its row-count footer")
        if len(row) != len(fields):
            raise OfficialInstitutionalError("TPEx report contains a malformed row")
        code = _clean_code(_row_value(row, code_i))
        if not code:
            raise OfficialInstitutionalError("TPEx report row has no identifiable security code")
        if code in seen_codes:
            raise OfficialInstitutionalError(f"TPEx report contains duplicate security code: {code}")
        seen_codes.add(code)

        try:
            quantities = _parse_amounts(row, (buy_i, sell_i, net_i))
        except ValueError as exc:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TPEx common-stock row contains an invalid quantity") from exc
            continue
        buy_shares, sell_shares, net_shares = quantities
        if buy_shares is None or sell_shares is None or net_shares is None:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TPEx common-stock row is missing a quantity")
            continue
        if buy_shares < 0 or sell_shares < 0 or buy_shares - sell_shares != net_shares:
            if is_common_stock_code(code):
                raise OfficialInstitutionalError("TPEx common-stock row has inconsistent quantities")
            continue
        result.append({
            "code": code,
            "name": _clean_text(_row_value(row, name_i)),
            "market": "TPEx",
            "buyShares": buy_shares,
            "sellShares": sell_shares,
            "netShares": net_shares,
        })
    if not count_footer_seen:
        raise OfficialInstitutionalError("TPEx report has no verified row-count footer")
    return result


def parse_tpex_daily_response(payload: bytes, *, expected_date: date) -> list[dict[str, Any]]:
    """Accept a dated CSV report or TPEx's dated no-trading-day sentinel."""

    if payload.lstrip().startswith(b"{"):
        try:
            response = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise OfficialInstitutionalError("TPEx report returned malformed JSON") from exc
        expected_roc_date = f"{expected_date.year - 1911:03d}/{expected_date.month:02d}/{expected_date.day:02d}"
        tables = response.get("tables") if isinstance(response, dict) else None
        table = tables[0] if isinstance(tables, list) and len(tables) == 1 else None
        if isinstance(response, dict) and response.get("stat") == "無資料可供下載":
            if (
                str(response.get("date") or "") != expected_date.strftime("%Y%m%d")
                or not isinstance(table, dict)
                or table.get("date") != expected_roc_date
            ):
                raise OfficialInstitutionalError("TPEx no-data response date mismatch")
        root_required = {"stat", "date", "tables"}
        root_metadata = {"columnNum", "csvName", "template"}
        table_required = {"date", "fields", "data", "totalCount"}
        table_metadata = {"columnNum", "notes", "subtitle", "summary", "title"}
        fields = table.get("fields") if isinstance(table, dict) else None
        metadata_valid = (
            isinstance(response, dict)
            and set(response).issubset(root_required | root_metadata)
            and root_required.issubset(response)
            and ("columnNum" not in response or
                 (type(response["columnNum"]) is int and 1 <= response["columnNum"] <= 64))
            and all(isinstance(response.get(key), str) for key in ("csvName", "template") if key in response)
            and isinstance(table, dict)
            and set(table).issubset(table_required | table_metadata)
            and table_required.issubset(table)
            and ("columnNum" not in table or
                 (type(table["columnNum"]) is int and 1 <= table["columnNum"] <= 64))
            and ("notes" not in table or isinstance(table["notes"], list))
            and ("summary" not in table or isinstance(table["summary"], list))
            and all(isinstance(table.get(key), str) for key in ("subtitle", "title") if key in table)
        )
        if (
            metadata_valid
            and response.get("stat") == "無資料可供下載"
            and response.get("date") == expected_date.strftime("%Y%m%d")
            and table.get("date") == expected_roc_date
            and table.get("data") == []
            and type(table.get("totalCount")) is int
            and table["totalCount"] == 0
            and isinstance(fields, list)
            and len(fields) == 24
        ):
            return []
        raise OfficialInstitutionalError("TPEx report returned an unexpected JSON response")
    return parse_tpex_csv(payload, expected_date=expected_date)


def _cache_json(raw: bytes) -> dict[str, Any]:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        result = json.loads(raw, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise OfficialInstitutionalError("cached source receipt is malformed") from exc
    if not isinstance(result, dict):
        raise OfficialInstitutionalError("cached source receipt is not an object")
    return result


def _read_bounded_file(path: Path, limit: int, label: str) -> bytes:
    try:
        with path.open("rb") as source:
            raw = source.read(limit + 1)
    except OSError as exc:
        raise OfficialInstitutionalError(f"{label} cannot be read") from exc
    if len(raw) > limit:
        raise OfficialInstitutionalError(f"{label} exceeds the size limit")
    return raw


def _orphaned_capture(
    directory: Path,
    *,
    raw_prefix: str,
    day: date,
    source_url: str,
) -> tuple[bytes, dict[str, Any]] | None:
    """Recover a raw capture only when its original receipt fully authenticates it."""
    raw_paths = sorted(Path(directory).glob(raw_prefix + "*.raw.json"))
    if not raw_paths:
        return None
    if len(raw_paths) != 1:
        raise OfficialInstitutionalError("cached source receipt is incomplete")
    raw_path = raw_paths[0]
    if raw_path.is_symlink() or not raw_path.is_file():
        raise OfficialInstitutionalError("cached source receipt path is invalid")
    raw_file = raw_path.name
    digest_match = re.fullmatch(re.escape(raw_prefix) + r"([a-f0-9]{64})\.raw\.json", raw_file)
    if not digest_match:
        raise OfficialInstitutionalError("cached source receipt raw reference is invalid")
    raw = _read_bounded_file(raw_path, MAX_TPEX_REPORT_BYTES, "cached raw report")
    digest = digest_match.group(1)
    receipt_path = raw_path.with_name(raw_file[:-9] + ".receipt.json")
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise OfficialInstitutionalError("cached source receipt bytes are missing")
    receipt = _cache_json(_read_bounded_file(receipt_path, MAX_RECEIPT_BYTES, "cached raw receipt"))
    if set(receipt) != {"requestDate", "sourceUrl", "unit", "retrievedAt", "rawFile", "rawSha256", "rawBytes", "rawBase64"}:
        raise OfficialInstitutionalError("cached raw receipt has an unexpected schema")
    if (
        receipt.get("requestDate") != day.isoformat()
        or receipt.get("sourceUrl") != source_url
        or receipt.get("unit") != "shares"
        or receipt.get("rawFile") != raw_file
        or receipt.get("rawSha256") != digest
        or type(receipt.get("rawBytes")) is not int
        or receipt["rawBytes"] != len(raw)
        or hashlib.sha256(raw).hexdigest() != digest
    ):
        raise OfficialInstitutionalError("cached source receipt raw hash or lineage is invalid")
    try:
        retrieved_at = datetime.fromisoformat(str(receipt.get("retrievedAt", "")).replace("Z", "+00:00"))
        encoded_raw = base64.b64decode(receipt.get("rawBase64", ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise OfficialInstitutionalError("cached raw receipt encoding or timestamp is invalid") from exc
    if (
        retrieved_at.tzinfo is None
        or retrieved_at.utcoffset() != timezone.utc.utcoffset(retrieved_at)
        or encoded_raw != raw
    ):
        raise OfficialInstitutionalError("cached source receipt encoded bytes or timestamp is invalid")
    return raw, receipt


def _cached_raw(
    source_cache_dir: Path,
    *,
    market: str,
    day: date,
    source_url: str,
    encoding: str,
) -> tuple[bytes, dict[str, Any]] | None:
    directory = Path(source_cache_dir)
    validated_path = directory / f"institutional-{market}-{day.isoformat()}-validated.json"
    raw_prefix = f"inst-{market.lower()}-{day.isoformat()}-"
    if not validated_path.exists():
        if validated_path.is_symlink():
            raise OfficialInstitutionalError("cached source receipt is incomplete")
        orphan = _orphaned_capture(
            directory, raw_prefix=raw_prefix, day=day, source_url=source_url,
        )
        if orphan is None:
            return None
        raw, receipt = orphan
        return raw, {"_recoveryReceipt": receipt}
    if validated_path.is_symlink() or not validated_path.is_file():
        raise OfficialInstitutionalError("cached source receipt path is invalid")
    metadata_raw = _read_bounded_file(validated_path, 64_000, "cached source receipt metadata")
    metadata = _cache_json(metadata_raw)
    required = {
        "requestDate", "sourceUrl", "unit", "retrievedAt", "rawFile", "rawSha256", "rawBytes",
        "market", "reportedDate", "validated", "status", "codes", "encoding",
    }
    if set(metadata) != required:
        raise OfficialInstitutionalError("cached source receipt has an unexpected schema")
    if (
        metadata.get("requestDate") != day.isoformat()
        or metadata.get("reportedDate") != day.isoformat()
        or metadata.get("market") != market
        or metadata.get("sourceUrl") != source_url
        or metadata.get("unit") != "shares"
        or (metadata.get("encoding") not in {"MS950", "utf-8"} if encoding == "auto" else metadata.get("encoding") != encoding)
        or metadata.get("validated") is not True
        or metadata.get("status") not in {"complete", "no_data"}
        or not isinstance(metadata.get("codes"), list)
        or metadata["codes"] != sorted(set(metadata["codes"]))
        or any(not isinstance(code, str) or not re.fullmatch(r"[1-9]\d{3}", code) for code in metadata["codes"])
    ):
        raise OfficialInstitutionalError("cached source receipt does not match this market date")
    try:
        retrieved_at = datetime.fromisoformat(str(metadata.get("retrievedAt", "")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfficialInstitutionalError("cached source receipt timestamp is invalid") from exc
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() != timezone.utc.utcoffset(retrieved_at):
        raise OfficialInstitutionalError("cached source receipt timestamp is not UTC")
    digest = metadata.get("rawSha256")
    raw_file = metadata.get("rawFile")
    if (
        type(metadata.get("rawBytes")) is not int
        or not 0 <= metadata["rawBytes"] <= MAX_TPEX_REPORT_BYTES
        or not isinstance(digest, str)
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
        or not isinstance(raw_file, str)
        or raw_file != f"{raw_prefix}{digest}.raw.json"
    ):
        raise OfficialInstitutionalError("cached source receipt raw reference is invalid")
    raw_path = directory / raw_file
    receipt_path = directory / (raw_file[:-9] + ".receipt.json")
    if raw_path.is_symlink() or receipt_path.is_symlink() or not raw_path.is_file() or not receipt_path.is_file():
        raise OfficialInstitutionalError("cached source receipt bytes are missing")
    raw = _read_bounded_file(raw_path, MAX_TPEX_REPORT_BYTES, "cached raw report")
    receipt_raw = _read_bounded_file(receipt_path, MAX_RECEIPT_BYTES, "cached raw receipt")
    original = _cache_json(receipt_raw)
    if set(original) != {"requestDate", "sourceUrl", "unit", "retrievedAt", "rawFile", "rawSha256", "rawBytes", "rawBase64"}:
        raise OfficialInstitutionalError("cached raw receipt has an unexpected schema")
    if (
        len(raw) != metadata["rawBytes"]
        or len(raw) > MAX_TPEX_REPORT_BYTES
        or hashlib.sha256(raw).hexdigest() != digest
        or original.get("requestDate") != day.isoformat()
        or original.get("sourceUrl") != source_url
        or original.get("unit") != "shares"
        or original.get("rawFile") != raw_file
        or original.get("rawSha256") != digest
        or original.get("rawBytes") != len(raw)
        or original.get("retrievedAt") != metadata.get("retrievedAt")
    ):
        raise OfficialInstitutionalError("cached source receipt raw hash or lineage is invalid")
    try:
        if base64.b64decode(original.get("rawBase64", ""), validate=True) != raw:
            raise OfficialInstitutionalError("cached source receipt encoded bytes do not match")
    except (ValueError, TypeError) as exc:
        raise OfficialInstitutionalError("cached source receipt encoded bytes are invalid") from exc
    return raw, metadata


def _get_bytes(
    url: str,
    *,
    data: dict[str, str] | None = None,
    source_cache_dir: Path | None = None,
    market: str,
    day: date,
) -> tuple[bytes, dict[str, Any] | None]:
    encoded = urllib.parse.urlencode(data or {}).encode() if data is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/csv, application/csv, */*"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    request = urllib.request.Request(url, data=encoded, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if source_cache_dir is None:
                raw = response.read(MAX_TPEX_REPORT_BYTES + 1)
                if len(raw) > MAX_TPEX_REPORT_BYTES:
                    raise OfficialInstitutionalError("official report exceeds the response size limit")
                receipt = None
            else:
                from pipeline.source_receipts import capture_raw, read_raw

                raw = read_raw(response, max_bytes=MAX_TPEX_REPORT_BYTES)
                receipt = capture_raw(
                    source_cache_dir,
                    prefix=f"inst-{market.lower()}-{day.isoformat()}",
                    raw=raw,
                    source_url=url,
                    unit="shares",
                    request_period={"requestDate": day.isoformat()},
                    retrieved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                )
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise OfficialInstitutionalError(f"official report request failed: {url}: {exc}") from exc
    return raw, receipt


def _write_validated_receipt(
    source_cache_dir: Path,
    receipt: dict[str, Any] | None,
    *,
    market: str,
    day: date,
    codes: list[str],
    status: str,
    encoding: str,
) -> None:
    if receipt is None:
        return
    validated = {
        **{key: value for key, value in receipt.items() if key != "rawBase64"},
        "market": market,
        "reportedDate": day.isoformat(),
        "validated": True,
        "status": status,
        "codes": codes,
        "encoding": encoding,
    }
    target = Path(source_cache_dir) / f"institutional-{market}-{day.isoformat()}-validated.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".institutional-receipt-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(validated, output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _codes_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({row["code"] for row in rows if re.fullmatch(r"[1-9]\d{3}", row["code"])})


def _verify_cached_projection(rows: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    status = "complete" if rows else "no_data"
    if _codes_from_rows(rows) != metadata["codes"] or status != metadata["status"]:
        raise OfficialInstitutionalError("cached source receipt projection does not match parsed bytes")


def fetch_twse_day(
    day: date,
    *,
    source_cache_dir: Path | None = None,
    refresh: bool = True,
) -> list[dict[str, Any]]:
    cached = None
    if source_cache_dir is not None and not refresh:
        cached = _cached_raw(source_cache_dir, market="TWSE", day=day, source_url=TWSE_ENDPOINT, encoding="utf-8")
    if cached is None:
        raw, receipt = _get_bytes(
            TWSE_ENDPOINT,
            data={"date": day.strftime("%Y%m%d"), "response": "json"},
            source_cache_dir=source_cache_dir,
            market="TWSE",
            day=day,
        )
        metadata = None
    else:
        raw, metadata = cached
        receipt = metadata.pop("_recoveryReceipt", None)
        if receipt is not None:
            metadata = None
    rows, no_data = _parse_twse_response(raw, expected_date=day)
    if no_data:
        _write_validated_receipt(source_cache_dir, receipt, market="TWSE", day=day, codes=[],
                                 status="no_data", encoding="utf-8")
        if metadata is not None:
            _verify_cached_projection(rows, metadata)
        return rows
    codes = _codes_from_rows(rows)
    _write_validated_receipt(source_cache_dir, receipt, market="TWSE", day=day, codes=codes,
                             status="complete" if rows else "no_data", encoding="utf-8")
    if metadata is not None:
        _verify_cached_projection(rows, metadata)
    return rows


def fetch_tpex_day(
    day: date,
    *,
    source_cache_dir: Path | None = None,
    refresh: bool = True,
) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({
        "type": "Daily", "sect": "AL", "date": day.strftime("%Y/%m/%d"), "response": "csv",
    })
    url = f"{TPEX_ENDPOINT}?{query}"
    cached = None
    if source_cache_dir is not None and not refresh:
        cached = _cached_raw(source_cache_dir, market="TPEx", day=day, source_url=url, encoding="auto")
    if cached is None:
        raw, receipt = _get_bytes(url, source_cache_dir=source_cache_dir, market="TPEx", day=day)
        metadata = None
    else:
        raw, metadata = cached
        receipt = metadata.pop("_recoveryReceipt", None)
        if receipt is not None:
            metadata = None
    rows = parse_tpex_daily_response(raw, expected_date=day)
    status = "complete" if rows else "no_data"
    codes = _codes_from_rows(rows)
    _write_validated_receipt(source_cache_dir, receipt, market="TPEx", day=day, codes=codes,
                             status=status, encoding="MS950" if not raw.lstrip().startswith(b"{") else "utf-8")
    if metadata is not None:
        _verify_cached_projection(rows, metadata)
    return rows


def fetch_complete_day(
    day: date,
    *,
    source_cache_dir: Path | None = None,
    refresh: bool = True,
) -> list[dict[str, Any]]:
    """Fetch both markets; empty means a weekend/holiday, not zero flow."""

    if source_cache_dir is None:
        twse = fetch_twse_day(day)
        tpex = fetch_tpex_day(day)
    else:
        twse = fetch_twse_day(day, source_cache_dir=source_cache_dir, refresh=refresh)
        tpex = fetch_tpex_day(day, source_cache_dir=source_cache_dir, refresh=refresh)
    if not twse or not tpex:
        return []
    return [*twse, *tpex]


def fetch_recent_complete_days(
    *,
    as_of: date | None = None,
    sessions: int = 11,
    lookback_days: int = 35,
    source_cache_dir: Path | None = None,
    calendar: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return newest-first complete cross-market sessions with row data."""

    if sessions < 1 or lookback_days < sessions:
        raise ValueError("invalid institutional session window")
    end = as_of or datetime.now(TAIPEI).date()
    if calendar is not None:
        from pipeline.trading_calendar import SOURCE_URL, TIMEZONE, is_open
        if (
            not isinstance(calendar, dict)
            or calendar.get("schemaVersion") != "trading-calendar-v1"
            or calendar.get("timezone") != TIMEZONE
            or calendar.get("sourceUrl") != SOURCE_URL
            or type(calendar.get("year")) is not int
            or not isinstance(calendar.get("closedDates"), list)
            or not isinstance(calendar.get("openExceptions"), list)
        ):
            raise ValueError("authoritative calendar is invalid")
        parsed_dates = {}
        for key in ("closedDates", "openExceptions"):
            values = calendar[key]
            parsed = set()
            for value in values:
                if not isinstance(value, str):
                    raise ValueError("authoritative calendar dates are invalid")
                try:
                    parsed_day = date.fromisoformat(value)
                except ValueError as exc:
                    raise ValueError("authoritative calendar dates are invalid") from exc
                if parsed_day.isoformat() != value or parsed_day.year != calendar["year"] or value in parsed:
                    raise ValueError("authoritative calendar dates are invalid")
                parsed.add(value)
            parsed_dates[key] = parsed
        if parsed_dates["closedDates"] & parsed_dates["openExceptions"]:
            raise ValueError("authoritative calendar dates conflict")
    result: list[dict[str, Any]] = []
    for offset in range(lookback_days):
        day = end - timedelta(days=offset)
        if calendar is not None:
            if day.year != calendar["year"]:
                raise ValueError("authoritative calendar does not cover requested year")
            if not is_open(calendar, day.isoformat()):
                continue
        if source_cache_dir is None:
            rows = fetch_complete_day(day)
        else:
            rows = fetch_complete_day(day, source_cache_dir=source_cache_dir, refresh=(day == end))
        if calendar is not None and not rows:
            raise OfficialInstitutionalError(f"official sources returned no complete data for open session {day.isoformat()}")
        if rows:
            result.append({"date": day.isoformat(), "rows": rows})
            if len(result) >= sessions:
                break
    if len(result) < sessions:
        raise OfficialInstitutionalError(
            f"only {len(result)} complete market sessions found; need {sessions}"
        )
    return result


def aggregate_window(days: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Sum normalized share flows and rank positive net-buy rows."""

    aggregate: dict[str, dict[str, Any]] = {}
    for rows in days:
        for row in rows:
            code = _clean_code(row.get("code"))
            net = row.get("netShares")
            if not code or not is_common_stock_code(code) or not isinstance(net, (int, float)):
                continue
            current = aggregate.setdefault(
                code,
                {
                    "code": code,
                    "name": _clean_text(row.get("name")),
                    "market": _clean_text(row.get("market")),
                    "netShares": 0,
                },
            )
            current["netShares"] += int(net)
    positive = [row for row in aggregate.values() if row["netShares"] > 0]
    positive.sort(key=lambda row: (-int(row["netShares"]), str(row["code"])))
    for rank, row in enumerate(positive, start=1):
        row["rank"] = rank
    return positive


def rank_adjacent_windows(
    snapshots: list[dict[str, Any]],
    *,
    window: int = 10,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rank current and previous rolling windows from newest-first snapshots."""

    if len(snapshots) < window + 1:
        raise ValueError(f"need at least {window + 1} snapshots")
    current = aggregate_window([snapshot["rows"] for snapshot in snapshots[:window]])
    previous = aggregate_window([snapshot["rows"] for snapshot in snapshots[1:window + 1]])
    return current, previous
