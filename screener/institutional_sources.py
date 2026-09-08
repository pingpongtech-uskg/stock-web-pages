"""Official TWSE T86 and TPEx institutional-flow adapters.

Only the investment-trust daily net-share field is normalized here.  The
adapter deliberately keeps zero-net rows: omitting them would make a "last ten
trading days" sum silently use older observations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import copy
import math
import re
from typing import Any, Mapping, Sequence


TWSE_T86_URL = "https://www.twse.com.tw/fund/T86"
TPEX_3INSTI_URL = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php"
_TPEX_INVESTMENT_TRUST_NET_INDEX = 13


@dataclass(frozen=True)
class InstitutionalRow:
    code: str
    name: str
    market: str
    date: str
    net_shares: int


def normalize_market_date(value: Any) -> str:
    """Normalize Gregorian/ROC compact or slash dates to ISO date."""
    text = str(value or "").strip()
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) == 7:  # ROC yyyMMdd
        return f"{1911 + int(digits[:3]):04d}-{digits[3:5]}-{digits[5:7]}"
    if len(digits) == 8:
        year = int(digits[:4])
        if year < 1911:
            year += 1911
        return f"{year:04d}-{digits[4:6]}-{digits[6:8]}"
    raise ValueError(f"invalid market date: {value!r}")


def _number(value: Any) -> int:
    text = str(value if value is not None else "").strip().replace(",", "")
    if text in {"", "-", "—", "－－", "－", "N/A", "NA"}:
        return 0
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer value: {value!r}") from exc
    if not math.isfinite(number) or number != int(number):
        raise ValueError(f"non-integral share value: {value!r}")
    return int(number)


def _ordinary_code(value: Any) -> str | None:
    code = str(value or "").strip()
    return code if re.fullmatch(r"\d{4}", code) else None


def _validate_date_matches(payload_date: Any, requested_date: str | None) -> str:
    actual = normalize_market_date(payload_date)
    if requested_date is not None and actual != normalize_market_date(requested_date):
        raise ValueError(f"response date {actual} does not match requested date {requested_date}")
    return actual


def parse_twse_t86(payload: Mapping[str, Any], *, source_url: str = TWSE_T86_URL, requested_date: str | None = None) -> list[InstitutionalRow]:
    if not isinstance(payload, Mapping) or str(payload.get("stat", "")).upper() != "OK":
        raise ValueError("TWSE T86 status is not OK")
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise ValueError("TWSE T86 fields/data missing")
    try:
        code_index = fields.index("證券代號")
        name_index = fields.index("證券名稱")
        net_index = fields.index("投信買賣超股數")
    except ValueError as exc:
        raise ValueError("TWSE T86 investment trust field missing") from exc
    if net_index >= len(fields) or len({code_index, name_index, net_index}) != 3:
        raise ValueError("TWSE T86 field indexes invalid")
    market_date = _validate_date_matches(payload.get("date"), requested_date)
    result: list[InstitutionalRow] = []
    for row in data:
        if not isinstance(row, Sequence) or len(row) <= max(code_index, name_index, net_index):
            continue
        code = _ordinary_code(row[code_index])
        if code is None:
            continue
        result.append(InstitutionalRow(code, str(row[name_index]).strip(), "TWSE", market_date, _number(row[net_index])))
    if not result:
        raise ValueError("TWSE T86 contained no ordinary-share rows")
    return result


def _tpex_net_index(table: Mapping[str, Any]) -> int:
    fields = table.get("fields")
    if not isinstance(fields, list):
        raise ValueError("TPEx fields missing")
    # Some public responses expose unique English/Chinese field names.
    named = [index for index, field in enumerate(fields) if str(field).strip() in {"投信買賣超股數", "SecuritiesInvestmentTrustCompanies-Difference"}]
    if len(named) == 1:
        return named[0]
    # The official hedge-result table uses repeated three-column labels.  Its
    # schema is: foreign ex-dealer, foreign dealer, foreign total, investment
    # trust, dealer self, dealer total, dealer hedge, total.  Validate the
    # shape and subtitle before using the documented group offset.
    subtitle = str(table.get("subtitle", ""))
    if len(fields) == 24 and int(table.get("columnNum", 25) or 25) == 25 and "投信" in subtitle:
        return _TPEX_INVESTMENT_TRUST_NET_INDEX
    raise ValueError("TPEx investment trust net-share field cannot be identified")


def parse_tpex_3insti(payload: Mapping[str, Any], *, source_url: str = TPEX_3INSTI_URL, requested_date: str | None = None) -> list[InstitutionalRow]:
    if not isinstance(payload, Mapping) or str(payload.get("stat", "")).lower() != "ok":
        raise ValueError("TPEx three-institution status is not OK")
    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables or not isinstance(tables[0], Mapping):
        raise ValueError("TPEx three-institution table missing")
    table = tables[0]
    data = table.get("data")
    if not isinstance(data, list):
        raise ValueError("TPEx three-institution data missing")
    payload_date = payload.get("date") or table.get("date")
    market_date = _validate_date_matches(payload_date, requested_date)
    net_index = _tpex_net_index(table)
    result: list[InstitutionalRow] = []
    for row in data:
        if not isinstance(row, Sequence) or len(row) <= max(1, net_index):
            continue
        code = _ordinary_code(row[0])
        if code is None:
            continue
        result.append(InstitutionalRow(code, str(row[1]).strip(), "TPEx", market_date, _number(row[net_index])))
    if not result:
        raise ValueError("TPEx three-institution response contained no ordinary-share rows")
    return result


def merge_daily_rows(cache: Mapping[str, Any], rows: Sequence[InstitutionalRow]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Merge official rows idempotently; preserve unresolved same-day conflicts."""
    result = copy.deepcopy(dict(cache))
    conflicts: list[dict[str, Any]] = []
    for row in rows:
        item = result.setdefault(row.code, {"market": row.market, "name": row.name, "dates": [], "net": []})
        item.setdefault("market", row.market)
        item.setdefault("name", row.name)
        dates = list(item.get("dates", []))
        nets = list(item.get("net", []))
        if len(dates) != len(nets):
            raise ValueError(f"cache dates/net length mismatch for {row.code}")
        normalized_dates = [normalize_market_date(value) for value in dates]
        if row.date in normalized_dates:
            index = normalized_dates.index(row.date)
            old_value = _number(nets[index])
            if old_value != row.net_shares:
                conflicts.append({"status": "data_conflict", "code": row.code, "market": row.market, "date": row.date, "old_net_shares": old_value, "new_net_shares": row.net_shares, "source": "official_daily_institutional"})
            continue
        normalized_dates.append(row.date)
        nets.append(row.net_shares)
        pairs = sorted(zip(normalized_dates, nets))
        item["dates"] = [pair[0] for pair in pairs]
        item["net"] = [int(pair[1]) for pair in pairs]
        item["market"] = row.market
        item["name"] = row.name
    return result, conflicts


def ten_day_rank(
    cache: Mapping[str, Any],
    *,
    as_of: str,
    prices: Mapping[str, float],
    limit: int | None = 100,
    share_limit: int | None = None,
) -> list[dict[str, Any]]:
    cutoff = normalize_market_date(as_of)
    ranked: list[dict[str, Any]] = []
    for code, item in cache.items():
        if not isinstance(item, Mapping):
            continue
        dates = [normalize_market_date(value) for value in item.get("dates", [])]
        nets = list(item.get("net", []))
        if len(dates) != len(nets):
            continue
        eligible = sorted((day, _number(net)) for day, net in zip(dates, nets) if day <= cutoff)
        if len(eligible) < 10:
            continue
        window = eligible[-10:]
        net_shares = sum(value for _, value in window)
        price = prices.get(str(code))
        if price is None:
            continue
        try:
            price_value = float(price)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price_value) or price_value <= 0 or net_shares <= 0:
            continue
        ranked.append({
            "code": str(code),
            "name": str(item.get("name", code)),
            "market": str(item.get("market", "")),
            "last_date": window[-1][0],
            "net_shares_10d": net_shares,
            "cur_price": round(price_value, 2),
            "net_amount_10d": round(net_shares * price_value, 2),
            "window_dates": [day for day, _ in window],
            "window_net_shares": [value for _, value in window],
            "institutional_source": "official_twse_t86_or_tpex_3insti",
        })
    ranked.sort(key=lambda row: (-row["net_shares_10d"], row["code"]))
    if share_limit is not None:
        ranked = ranked[:share_limit]
    ranked.sort(key=lambda row: (-row["net_amount_10d"], -row["net_shares_10d"], row["code"]))
    if limit is None:
        return ranked
    return ranked[:limit]
