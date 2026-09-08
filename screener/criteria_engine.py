"""Pure, fail-closed evaluator for the seven canonical stock-screen groups."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy

GROUP_SPECS = {
    "safety": ("fcf_latest_five_three_positive", "fcf_mean_positive", "cfo_ni_latest_five_three_over_100", "cfo_ni_mean_over_100", "receivable_days_latest_le_prior", "inventory_days_latest_le_prior"),
    "dividend": ("yield_1y_over_6", "yield_5y_average_over_6", "five_consecutive_dividend_years", "payout_latest_five_three_over_50", "payout_mean_over_50"),
    "growth": ("monthly_revenue_yoy_latest_three_positive", "quarter_gross_profit_yoy_positive", "quarter_operating_income_yoy_positive", "quarter_pretax_income_yoy_positive", "quarter_net_income_yoy_positive"),
    "value": ("pe_at_or_below_5y_p20", "pe_below_peer_median", "pb_at_or_below_5y_p20", "pb_below_peer_median", "yield_1y_over_6", "yield_5y_average_over_6"),
    "turnaround": ("pb_below_3", "piotroski_f_score_at_least_8", "pb_rank_at_most_50"),
    "continuity": ("listed_years_over_3", "fcf_return_current_at_least_prior", "fcf_return_3y_rank_at_most_20", "operating_income_3y_sum_positive", "composite_rank_at_most_50"),
    "chip": ("major_holder_three_month_increases", "director_holder_current_at_least_12m", "shareholders_three_month_decreases"),
}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError
    return float(value)


def _series(value, length, *, unique=False):
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence) or len(value) != length:
        raise ValueError
    out = [_number(v) for v in value]
    if unique and len(set(out)) != len(out):
        raise ValueError
    return out


def _field(data, group, key):
    section = data.get(group)
    if not isinstance(section, Mapping) or key not in section:
        raise ValueError
    return section[key]


def _pair(data, group, key):
    value = _field(data, group, key)
    if not isinstance(value, Mapping):
        raise ValueError
    return _number(value["latest"]), _number(value["prior"])


def _ratio_series(value, length):
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence) or len(value) != length:
        raise ValueError
    result = []
    for item in value:
        if isinstance(item, Mapping):
            denominator = _number(item["ni"])
            if denominator == 0:
                raise ValueError
            result.append(_number(item["cfo"]) / denominator * 100)
        else:
            result.append(_number(item))
    return result


def _p20(values):
    ordered = sorted(values)
    pos = (len(ordered) - 1) * 0.2
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _piotroski(data):
    p = _field(data, "turnaround", "piotroski")
    if not isinstance(p, Mapping):
        raise ValueError
    years = p.get("years")
    tests = p.get("tests")
    def valid_years(value):
        return (isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
                and len(value) >= 1 and len(set(value)) == len(value)
                and all(type(year) is int for year in value))

    if isinstance(tests, Mapping):
        # Nine named tests, each with one value per aligned fiscal year.
        if len(tests) != 9 or not valid_years(years):
            raise ValueError
        cols = [tests[name] for name in tests]
        if any(not isinstance(col, Sequence) or len(col) != len(years) for col in cols):
            raise ValueError
        # Values must be explicit booleans (not truthy numbers), and a current
        # fiscal-year row is scored from the nine aligned tests.
        if any(any(type(v) is not bool for v in tests[name]) for name in tests):
            raise ValueError
        return sum(bool(col[0]) for col in cols) >= 8
    if (not isinstance(tests, Sequence) or isinstance(tests, (str, bytes, bytearray))
            or not valid_years(years) or len(tests) != len(years)):
        raise ValueError
    rows = []
    for row in tests:
        if not isinstance(row, Sequence) or len(row) != 9 or any(type(v) is not bool for v in row):
            raise ValueError
        rows.append(row)
    return sum(rows[0]) >= 8


def evaluate_criteria(canonical: Mapping) -> dict:
    """Evaluate a canonical snapshot. Any invalid prerequisite yields UNKNOWN."""
    if not isinstance(canonical, Mapping):
        canonical = {}
    provenance = deepcopy(canonical.get("provenance"))
    values = {}

    def put(group, name, fn):
        try:
            values[(group, name)] = bool(fn())
        except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
            values[(group, name)] = None

    put("safety", "fcf_latest_five_three_positive", lambda: sum(v > 0 for v in _series(_field(canonical, "safety", "fcf"), 5)) >= 3)
    put("safety", "fcf_mean_positive", lambda: sum(_series(_field(canonical, "safety", "fcf"), 5)) / 5 > 0)
    def cfo_three():
        vals = _ratio_series(_field(canonical, "safety", "cfo_ni"), 5)
        return sum(v > 100 for v in vals) >= 3
    put("safety", "cfo_ni_latest_five_three_over_100", cfo_three)
    put("safety", "cfo_ni_mean_over_100", lambda: sum(_ratio_series(_field(canonical, "safety", "cfo_ni"), 5)) / 5 > 100)
    put("safety", "receivable_days_latest_le_prior", lambda: _pair(canonical, "safety", "receivable_days")[0] <= _pair(canonical, "safety", "receivable_days")[1])
    put("safety", "inventory_days_latest_le_prior", lambda: _pair(canonical, "safety", "inventory_days")[0] <= _pair(canonical, "safety", "inventory_days")[1])

    put("dividend", "yield_1y_over_6", lambda: _number(_field(canonical, "dividend", "yield_1y")) > 6)
    put("dividend", "yield_5y_average_over_6", lambda: _number(_field(canonical, "dividend", "yield_5y_avg")) > 6)
    def consecutive():
        years = _field(canonical, "dividend", "dividend_years")
        if isinstance(years, (str, bytes)) or not isinstance(years, Sequence) or len(years) != 5 or len(set(years)) != 5:
            raise ValueError
        vals = sorted(years)
        if any(isinstance(y, bool) or not isinstance(y, int) for y in vals): raise ValueError
        return all(b - a == 1 for a, b in zip(vals, vals[1:]))
    put("dividend", "five_consecutive_dividend_years", consecutive)
    put("dividend", "payout_latest_five_three_over_50", lambda: sum(v > 50 for v in _series(_field(canonical, "dividend", "payout_ratio"), 5)) >= 3)
    put("dividend", "payout_mean_over_50", lambda: sum(_series(_field(canonical, "dividend", "payout_ratio"), 5)) / 5 > 50)

    put("growth", "monthly_revenue_yoy_latest_three_positive", lambda: all(v > 0 for v in _series(_field(canonical, "growth", "monthly_revenue_yoy"), 3)))
    for key, name in (("gross_profit", "quarter_gross_profit_yoy_positive"), ("operating_income", "quarter_operating_income_yoy_positive"), ("pretax_income", "quarter_pretax_income_yoy_positive"), ("net_income", "quarter_net_income_yoy_positive")):
        put("growth", name, lambda key=key: _number(_field(canonical, "growth", "quarter_yoy")[key]) > 0)

    put("value", "pe_at_or_below_5y_p20", lambda: _number(_field(canonical, "value", "pe_current")) <= _p20(_series(_field(canonical, "value", "pe_5y"), 5)))
    put("value", "pe_below_peer_median", lambda: _number(_field(canonical, "value", "pe_current")) < _number(_field(canonical, "value", "pe_peer_median")))
    put("value", "pb_at_or_below_5y_p20", lambda: _number(_field(canonical, "value", "pb_current")) <= _p20(_series(_field(canonical, "value", "pb_5y"), 5)))
    put("value", "pb_below_peer_median", lambda: _number(_field(canonical, "value", "pb_current")) < _number(_field(canonical, "value", "pb_peer_median")))
    put("value", "yield_1y_over_6", lambda: _number(_field(canonical, "value", "yield_1y")) > 6)
    put("value", "yield_5y_average_over_6", lambda: _number(_field(canonical, "value", "yield_5y_avg")) > 6)

    put("turnaround", "pb_below_3", lambda: _number(_field(canonical, "turnaround", "pb_current")) < 3)
    put("turnaround", "piotroski_f_score_at_least_8", lambda: _piotroski(canonical))
    put("turnaround", "pb_rank_at_most_50", lambda: _number(_field(canonical, "turnaround", "pb_rank")) <= 50)

    put("continuity", "listed_years_over_3", lambda: _number(_field(canonical, "continuity", "listed_years")) > 3)
    put("continuity", "fcf_return_current_at_least_prior", lambda: _pair(canonical, "continuity", "fcf_return")[0] >= _pair(canonical, "continuity", "fcf_return")[1])
    put("continuity", "fcf_return_3y_rank_at_most_20", lambda: _number(_field(canonical, "continuity", "fcf_return_rank_3y")) <= 20)
    put("continuity", "operating_income_3y_sum_positive", lambda: _number(_field(canonical, "continuity", "operating_income_3y_sum")) > 0)
    put("continuity", "composite_rank_at_most_50", lambda: _number(_field(canonical, "continuity", "composite_rank")) <= 50)

    put("chip", "major_holder_three_month_increases", lambda: all(a > b for a, b in zip(_series(_field(canonical, "chip", "major_holder_ownership"), 3), _series(_field(canonical, "chip", "major_holder_ownership"), 3)[1:])))
    put("chip", "director_holder_current_at_least_12m", lambda: _pair(canonical, "chip", "director_holder_months")[0] >= _pair(canonical, "chip", "director_holder_months")[1])
    put("chip", "shareholders_three_month_decreases", lambda: all(a < b for a, b in zip(_series(_field(canonical, "chip", "shareholder_count"), 3), _series(_field(canonical, "chip", "shareholder_count"), 3)[1:])))

    groups = {}
    for group, names in GROUP_SPECS.items():
        criteria = [{"id": name, "status": "UNKNOWN" if values[(group, name)] is None else ("PASS" if values[(group, name)] else "FAIL"), "provenance": deepcopy(provenance)} for name in names]
        complete = all(c["status"] != "UNKNOWN" for c in criteria)
        passed = sum(c["status"] == "PASS" for c in criteria) if complete else None
        groups[group] = {"status": ("ok" if complete else "missing"), "result": ("pass" if complete and passed is not None and passed >= len(names) / 2 else "fail" if complete else "unknown"), "criteria": criteria, "passed": passed, "count": len(names) if complete else None, "pass_ratio": passed / len(names) if complete and passed is not None else None, "provenance": deepcopy(provenance)}
    return {"groups": groups, "provenance": provenance}

# Friendly alias for callers using the engine terminology.
evaluate = evaluate_criteria
