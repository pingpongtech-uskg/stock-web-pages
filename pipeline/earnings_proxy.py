"""Known-data earnings growth fallbacks for the Zulu PEG screen."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _quarter_rows(rows: list[dict[str, Any]]) -> dict[tuple[int, int], list[dict[str, Any]]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try:
            year = int(str(row.get("year")))
            quarter = int(str(row.get("quarter")))
        except (TypeError, ValueError):
            continue
        if quarter not in {1, 2, 3, 4}:
            continue
        grouped[(year, quarter)].append(row)
    return grouped


def _complete_years(grouped: dict[tuple[int, int], list[dict[str, Any]]]) -> list[int]:
    years = sorted({year for year, _quarter in grouped})
    return [year for year in years if all((year, quarter) in grouped for quarter in (1, 2, 3, 4))]


def _sum_field(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [_number(row.get(field)) for row in rows]
    if not values or any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _sum_gross_profit(rows: list[dict[str, Any]]) -> float | None:
    direct = _sum_field(rows, "grossProfit")
    if direct is not None:
        return direct
    values: list[float] = []
    for row in rows:
        revenue = _number(row.get("revenue"))
        margin = _number(row.get("grossMargin"))
        if revenue is None or margin is None:
            return None
        values.append(revenue * margin)
    return sum(values) if values else None


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior <= 0:
        return None
    result = current / prior - 1.0
    return result if math.isfinite(result) else None


def _per_share(value: float | None, shares: float | None) -> float | None:
    if value is None or shares is None or shares <= 0:
        return None
    return value / shares


def derive_ltm_eps_proxy(rows: list[dict[str, Any]], *, shares: float | None) -> dict[str, Any]:
    """Return the best known LTM growth proxy without emitting unknown.

    The method prefers actual reported EPS/net income, then operating profit,
    then gross profit (revenue × gross margin), and finally revenue. The last
    two are explicitly proxies; they are not silently called net EPS.
    """
    grouped = _quarter_rows(rows)
    share_count = _number(shares)
    years = _complete_years(grouped)
    if len(years) >= 2:
        prior_year, current_year = years[-2], years[-1]
        prior_rows = [grouped[(prior_year, quarter)][-1] for quarter in (1, 2, 3, 4)]
        current_rows = [grouped[(current_year, quarter)][-1] for quarter in (1, 2, 3, 4)]
    else:
        ordered = [grouped[key][-1] for key in sorted(grouped)]
        prior_rows, current_rows = ordered[-8:-4], ordered[-4:]
    if len(prior_rows) != 4 or len(current_rows) != 4:
        return {"method": "no_ltm_window", "method_label": "可用期間不足，改用營收觀察", "growth": None, "current_eps": None, "prior_eps": None}

    current_eps = _sum_field(current_rows, "eps")
    prior_eps = _sum_field(prior_rows, "eps")
    eps_growth = _growth(current_eps, prior_eps)
    if eps_growth is not None:
        return {
            "method": "ltm_reported_eps",
            "method_label": "LTM 已公布 EPS 成長",
            "growth": eps_growth,
            "current_eps": current_eps,
            "prior_eps": prior_eps,
        }

    current_net = _sum_field(current_rows, "parentNetIncome") or _sum_field(current_rows, "netIncome")
    prior_net = _sum_field(prior_rows, "parentNetIncome") or _sum_field(prior_rows, "netIncome")
    net_growth = _growth(current_net, prior_net)
    if net_growth is not None:
        return {
            "method": "ltm_net_income_eps",
            "method_label": "LTM 淨利／股數 EPS 代理",
            "growth": net_growth,
            "current_eps": _per_share(current_net, share_count),
            "prior_eps": _per_share(prior_net, share_count),
        }

    current_operating = _sum_field(current_rows, "operatingProfit")
    prior_operating = _sum_field(prior_rows, "operatingProfit")
    operating_growth = _growth(current_operating, prior_operating)
    if operating_growth is not None:
        return {
            "method": "ltm_operating_profit_eps_proxy",
            "method_label": "LTM 營業利益／股數 EPS 代理",
            "growth": operating_growth,
            "current_eps": _per_share(current_operating, share_count),
            "prior_eps": _per_share(prior_operating, share_count),
        }

    current_gross = _sum_gross_profit(current_rows)
    prior_gross = _sum_gross_profit(prior_rows)
    gross_growth = _growth(current_gross, prior_gross)
    if gross_growth is not None:
        return {
            "method": "ltm_gross_profit_eps_proxy",
            "method_label": "LTM 營收×毛利率／股數 EPS 代理",
            "growth": gross_growth,
            "current_eps": _per_share(current_gross, share_count),
            "prior_eps": _per_share(prior_gross, share_count),
        }

    current_revenue = _sum_field(current_rows, "revenue")
    prior_revenue = _sum_field(prior_rows, "revenue")
    revenue_growth = _growth(current_revenue, prior_revenue)
    return {
        "method": "ltm_revenue_proxy",
        "method_label": "LTM 營收成長代理",
        "growth": revenue_growth,
        "current_eps": None,
        "prior_eps": None,
    }
