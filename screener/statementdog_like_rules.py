"""Transparent public-data rules for the seven-category Taiwan screener.

This module is intentionally independent of StatementDog.  It implements the
user-owned public-data definitions and returns a diagnostic result for every
criterion.  Missing inputs are ``unknown``; they never become a failed boolean.
"""
from __future__ import annotations

from datetime import date, timedelta
import math
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from .f_score import calculate_f_score
from .public_data_models import (
    CATEGORY_COUNTS,
    CATEGORY_ORDER,
    CategoryScore,
    CompanyData,
    CriterionResult,
    Fact,
    ScoreConfig,
    Status,
    add_years,
    as_date,
    period_sort_key,
    previous_year_period,
)

FORMULA_VERSION = "public-data-health-v1"

CATEGORY_CRITERIA: dict[str, tuple[str, ...]] = {
    "turnaround": (
        "turnaround.pb_lt_3",
        "turnaround.f_score_ge_8",
        "turnaround.pb_lowest_top50",
    ),
    "value": (
        "value.pe_lowest_20pct_5y",
        "value.pe_below_50pct_universe",
        "value.pb_lowest_20pct_5y",
        "value.pb_below_50pct_universe",
        "value.trailing_yield_gt_6",
        "value.avg_yield_5y_gt_6",
    ),
    "growth": (
        "growth.monthly_revenue_yoy_3_consecutive",
        "growth.gross_profit_yoy_gt_0",
        "growth.operating_income_yoy_gt_0",
        "growth.pretax_income_yoy_gt_0",
        "growth.after_tax_income_yoy_gt_0",
    ),
    "chip": (
        "chip.major_holder_ratio_up_3m",
        "chip.director_holdings_not_down_12m",
        "chip.shareholder_count_down_3m",
    ),
    "dividend": (
        "dividend.trailing_yield_gt_6",
        "dividend.avg_yield_5y_gt_6",
        "dividend.consecutive_5y",
        "dividend.payout_gt_50_3_of_5",
        "dividend.payout_mean_gt_50",
    ),
    "continuity": (
        "continuity.listed_over_3y",
        "continuity.croic_not_down",
        "continuity.croic_3y_top20",
        "continuity.operating_income_3y_sum_gt_0",
        "continuity.combined_value_top50",
    ),
    "safety": (
        "safety.fcf_positive_3_of_5",
        "safety.fcf_mean_positive",
        "safety.cfo_ni_ratio_3_of_5",
        "safety.cfo_ni_ratio_mean",
        "safety.receivable_days_not_worse",
        "safety.inventory_days_not_worse",
    ),
}

CRITERION_LABELS = {
    "turnaround.pb_lt_3": "PB < 3",
    "turnaround.f_score_ge_8": "Piotroski F-score >= 8",
    "turnaround.pb_lowest_top50": "PB ranking top 50",
    "value.pe_lowest_20pct_5y": "PE in own five-year lowest 20%",
    "value.pe_below_50pct_universe": "PE at or below eligible-universe 50th percentile",
    "value.pb_lowest_20pct_5y": "PB in own five-year lowest 20%",
    "value.pb_below_50pct_universe": "PB at or below eligible-universe 50th percentile",
    "value.trailing_yield_gt_6": "trailing twelve-month cash yield > 6%",
    "value.avg_yield_5y_gt_6": "five-year average cash yield > 6%",
    "growth.monthly_revenue_yoy_3_consecutive": "monthly revenue YoY positive for three consecutive months",
    "growth.gross_profit_yoy_gt_0": "latest-quarter gross profit YoY > 0",
    "growth.operating_income_yoy_gt_0": "latest-quarter operating income YoY > 0",
    "growth.pretax_income_yoy_gt_0": "latest-quarter pretax income YoY > 0",
    "growth.after_tax_income_yoy_gt_0": "latest-quarter after-tax income YoY > 0",
    "chip.major_holder_ratio_up_3m": "major-holder ratio rises three consecutive months",
    "chip.director_holdings_not_down_12m": "director/supervisor holdings not down versus twelve months prior",
    "chip.shareholder_count_down_3m": "total shareholder count falls three consecutive months",
    "dividend.trailing_yield_gt_6": "trailing twelve-month cash yield > 6%",
    "dividend.avg_yield_5y_gt_6": "five-year average cash yield > 6%",
    "dividend.consecutive_5y": "cash dividend exists for five consecutive attribution years",
    "dividend.payout_gt_50_3_of_5": "payout ratio > 50% in at least three of five years",
    "dividend.payout_mean_gt_50": "five-year mean payout ratio > 50%",
    "continuity.listed_over_3y": "listed for more than three years",
    "continuity.croic_not_down": "FCF ROE not below prior year",
    "continuity.croic_3y_top20": "three-year mean FCF ROE in top 20%",
    "continuity.operating_income_3y_sum_gt_0": "three-year operating income sum > 0",
    "continuity.combined_value_top50": "transparent PB+PE+yield composite top 50",
    "safety.fcf_positive_3_of_5": "FCF positive in at least three of five years",
    "safety.fcf_mean_positive": "five-year mean FCF > 0",
    "safety.cfo_ni_ratio_3_of_5": "CFO/net income > 100% in at least three of five years",
    "safety.cfo_ni_ratio_mean": "five-year mean CFO/net income > 100%",
    "safety.receivable_days_not_worse": "receivable days not worse than same quarter prior year",
    "safety.inventory_days_not_worse": "inventory days not worse than same quarter prior year",
}


def _cutoff(as_of: date | str) -> date:
    result = as_date(as_of)
    if result is None:
        raise ValueError("as_of is required")
    return result


def _value(fact: Fact | None) -> float | None:
    return float(fact.value) if fact is not None and fact.value is not None else None


def _sources(*items: Fact | None, dividends: Iterable[Any] = ()) -> tuple[str, ...]:
    result = {item.content_sha256 for item in items if item is not None}
    result.update(item.content_sha256 for item in dividends if getattr(item, "content_sha256", None))
    return tuple(sorted(result))


def _proxy(*items: Fact | None, dividends: Iterable[Any] = ()) -> bool:
    return any(item is not None and item.proxy for item in items) or any(getattr(item, "proxy", False) for item in dividends)


def _result(
    criterion_id: str,
    status: Status,
    *,
    value: Any = None,
    threshold: Any = None,
    period: str | None = None,
    as_of: date,
    facts: Sequence[Fact | None] = (),
    dividends: Sequence[Any] = (),
    reason: str | None = None,
    proxy: bool | None = None,
    details: Mapping[str, Any] | None = None,
) -> CriterionResult:
    return CriterionResult(
        criterion_id=criterion_id,
        status=status,
        value=value,
        threshold=threshold,
        period=period,
        as_of=as_of.isoformat(),
        source_snapshot=_sources(*facts, dividends=dividends),
        formula_version=FORMULA_VERSION,
        reason=reason,
        proxy=_proxy(*facts, dividends=dividends) if proxy is None else proxy,
        details=details or {},
    )


def _unknown(criterion_id: str, as_of: date, reason: str, *, facts: Sequence[Fact | None] = (), dividends: Sequence[Any] = (), period: str | None = None, details: Mapping[str, Any] | None = None) -> CriterionResult:
    return _result(criterion_id, Status.UNKNOWN, as_of=as_of, facts=facts, dividends=dividends, period=period, reason=reason, details=details)


def _not_applicable(criterion_id: str, as_of: date, reason: str) -> CriterionResult:
    return _result(criterion_id, Status.NOT_APPLICABLE, as_of=as_of, reason=reason)


def _available(company: CompanyData, field: str, period: str, as_of: date, *, period_type: str | None = None) -> Fact | None:
    fact = company.get_fact(field, period, as_of=as_of)
    if fact is None:
        return None
    if period_type is not None and fact.period_type != period_type:
        return None
    return fact


def _valid_periods(company: CompanyData, fields: Sequence[str], period_type: str, as_of: date) -> list[str]:
    sets = []
    for field in fields:
        sets.append(set(company.periods(field, period_type=period_type, as_of=as_of)))
    if not sets:
        return []
    return sorted(set.intersection(*sets), key=period_sort_key)


def _annual_years(company: CompanyData, fields: Sequence[str], as_of: date, count: int) -> list[int]:
    periods = _valid_periods(company, fields, "annual", as_of)
    years = []
    for period in periods:
        match = re.fullmatch(r"(\d{4})-FY", period)
        if match:
            years.append(int(match.group(1)))
    return sorted(set(years))[-count:]


def _annual_facts(company: CompanyData, fields: Sequence[str], years: Sequence[int], as_of: date) -> list[dict[str, Fact]]:
    result: list[dict[str, Fact]] = []
    for year in years:
        row: dict[str, Fact] = {}
        for field in fields:
            fact = _available(company, field, f"{year:04d}-FY", as_of, period_type="annual")
            if fact is None:
                break
            row[field] = fact
        if len(row) == len(fields):
            result.append(row)
    return result


def _f_cfs(row: Mapping[str, Fact]) -> float:
    """FCF convention owned by this scorer: CFO minus positive CapEx."""
    return float(row["cfo"].value) - float(row["capex"].value)


def _annual_fcf_rows(company: CompanyData, as_of: date, count: int = 5) -> list[tuple[int, dict[str, Fact], float]]:
    years = _annual_years(company, ("cfo", "capex"), as_of, count)
    rows = _annual_facts(company, ("cfo", "capex"), years, as_of)
    return [(year, row, _f_cfs(row)) for year, row in zip(years, rows)]


def _fcf_rule(criterion_id: str, company: CompanyData, as_of: date, *, mean: bool) -> CriterionResult:
    rows = _annual_fcf_rows(company, as_of, 5)
    if len(rows) != 5:
        return _unknown(criterion_id, as_of, "exactly five complete annual CFO and CapEx rows required")
    values = [value for _, _, value in rows]
    facts = [fact for _, row, _ in rows for fact in row.values()]
    observed = sum(value > 0 for value in values) if not mean else sum(values) / 5
    threshold = 0 if mean else 3
    condition = observed > threshold if mean else observed >= threshold
    return _result(criterion_id, Status.PASS if condition else Status.FAIL, value=observed, threshold=threshold, period="five-complete-fiscal-years", as_of=as_of, facts=facts, details={"fcf_by_year": {str(year): value for (year, _, value) in rows}, "fcf_formula": "CFO - CapEx"})


def _cfo_ni_rule(criterion_id: str, company: CompanyData, as_of: date, *, mean: bool) -> CriterionResult:
    years = _annual_years(company, ("cfo", "net_income"), as_of, 5)
    rows = _annual_facts(company, ("cfo", "net_income"), years, as_of)
    if len(rows) != 5:
        return _unknown(criterion_id, as_of, "exactly five complete annual CFO and net income rows required")
    ratios: list[float] = []
    for row in rows:
        ni = _value(row["net_income"])
        cfo = _value(row["cfo"])
        if ni is None or cfo is None or ni <= 0:
            return _unknown(criterion_id, as_of, "net income must be positive for every ratio year", facts=list(row.values()))
        ratios.append(cfo / ni * 100)
    observed = sum(ratios) / len(ratios) if mean else sum(ratio > 100 for ratio in ratios)
    condition = observed > 100 if mean else observed >= 3
    return _result(criterion_id, Status.PASS if condition else Status.FAIL, value=observed, threshold=100 if mean else 3, period="five-complete-fiscal-years", as_of=as_of, facts=[fact for row in rows for fact in row.values()], details={"cfo_ni_ratio_percent": ratios, "negative_or_zero_net_income": "unknown"})


def _latest_quarter(company: CompanyData, field: str, as_of: date) -> tuple[str, Fact] | None:
    periods = company.periods(field, period_type="quarterly", as_of=as_of)
    for period in reversed(periods):
        fact = _available(company, field, period, as_of, period_type="quarterly")
        if fact is not None:
            return period, fact
    return None


def _quarter_yoy(criterion_id: str, company: CompanyData, as_of: date, field: str) -> CriterionResult:
    latest = _latest_quarter(company, field, as_of)
    if latest is None:
        return _unknown(criterion_id, as_of, f"latest quarterly {field} unavailable")
    period, current = latest
    prior_period = previous_year_period(period)
    prior = _available(company, field, prior_period, as_of, period_type="quarterly")
    if prior is None or _value(prior) is None or _value(current) is None:
        return _unknown(criterion_id, as_of, "same fiscal quarter prior-year value unavailable", facts=(current, prior), period=period)
    if float(prior.value) == 0:
        return _unknown(criterion_id, as_of, "prior-year denominator is zero", facts=(current, prior), period=period)
    yoy = (float(current.value) - float(prior.value)) / abs(float(prior.value)) * 100
    return _result(criterion_id, Status.PASS if yoy > 0 else Status.FAIL, value=yoy, threshold=0, period=period, as_of=as_of, facts=(current, prior), details={"current_period": period, "prior_period": prior_period, "comparison": "same fiscal quarter", "yoy_percent": yoy})


def _latest_month_pairs(company: CompanyData, as_of: date) -> list[tuple[str, Fact, Fact]]:
    periods = _valid_periods(company, ("monthly_revenue", "prior_year_same_month_revenue"), "monthly", as_of)
    result: list[tuple[str, Fact, Fact]] = []
    for period in periods:
        current = _available(company, "monthly_revenue", period, as_of, period_type="monthly")
        prior = _available(company, "prior_year_same_month_revenue", period, as_of, period_type="monthly")
        if current is not None and prior is not None:
            result.append((period, current, prior))
    return result[-3:]


def _monthly_revenue_rule(criterion_id: str, company: CompanyData, as_of: date) -> CriterionResult:
    pairs = _latest_month_pairs(company, as_of)
    if len(pairs) != 3:
        return _unknown(criterion_id, as_of, "three chronological monthly revenue and prior-year rows required")
    yoys: list[float] = []
    facts: list[Fact] = []
    for period, current, prior in pairs:
        if _value(prior) is None or _value(current) is None or float(prior.value) == 0:
            return _unknown(criterion_id, as_of, "monthly prior-year revenue denominator missing or zero", facts=[current, prior], period=period)
        yoys.append((float(current.value) - float(prior.value)) / abs(float(prior.value)) * 100)
        facts.extend((current, prior))
    return _result(criterion_id, Status.PASS if all(value > 0 for value in yoys) else Status.FAIL, value=yoys, threshold=0, period=",".join(pair[0] for pair in pairs), as_of=as_of, facts=facts, details={"chronological_periods": [pair[0] for pair in pairs], "yoy_percent": yoys})


def _date_for_fact(fact: Fact) -> date | None:
    if fact.observed_date is not None:
        return fact.observed_date
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fact.period):
        return as_date(fact.period)
    return None


def _daily_facts(company: CompanyData, field: str, as_of: date) -> list[Fact]:
    return [fact for fact in company.all_facts(field, period_type="daily") if fact.is_available_as_of(as_of, require_announcement=False) and _date_for_fact(fact) is not None]


def _current_daily(company: CompanyData, field: str, as_of: date, *, positive: bool = False) -> Fact | None:
    candidates = sorted(_daily_facts(company, field, as_of), key=lambda fact: (_date_for_fact(fact), fact.source_id))
    for fact in reversed(candidates):
        if _value(fact) is not None and (not positive or float(fact.value) > 0):
            return fact
    return None


def _price_on_or_before(company: CompanyData, target: date, as_of: date) -> Fact | None:
    candidates = [fact for fact in _daily_facts(company, "price", as_of) if (_date_for_fact(fact) or target) <= target and _value(fact) is not None and float(fact.value) > 0]
    return sorted(candidates, key=lambda fact: (_date_for_fact(fact), fact.source_id))[-1] if candidates else None


def _valid_valuation_facts(company: CompanyData, field: str, as_of: date) -> list[Fact]:
    result = []
    for fact in _daily_facts(company, field, as_of):
        value = _value(fact)
        if value is not None and value > 0:
            result.append(fact)
    return sorted(result, key=lambda fact: (_date_for_fact(fact), fact.source_id))


def _ascending_percentile(value: float, values: Sequence[float]) -> float:
    if not values:
        raise ValueError("percentile needs values")
    rank_min = 1 + sum(item < value for item in values)
    return rank_min / len(values)


def _valuation_history_rule(criterion_id: str, company: CompanyData, as_of: date, field: str, config: ScoreConfig) -> CriterionResult:
    current = _current_daily(company, field, as_of, positive=True)
    history = _valid_valuation_facts(company, field, as_of)
    if current is None or len(history) < config.min_history_observations:
        return _unknown(criterion_id, as_of, f"current {field} and at least {config.min_history_observations} valid five-year observations required", facts=[current, *history])
    cutoff_start = as_of - timedelta(days=365 * 5 + 2)
    history = [fact for fact in history if (_date_for_fact(fact) or as_of) >= cutoff_start]
    if len(history) < config.min_history_observations:
        return _unknown(criterion_id, as_of, "five-year history does not meet configured observation floor", facts=[current, *history])
    values = [_value(fact) for fact in history]
    numeric_values = [value for value in values if value is not None]
    percentile = _ascending_percentile(float(current.value), numeric_values)
    return _result(criterion_id, Status.PASS if percentile <= 0.20 else Status.FAIL, value=percentile, threshold=0.20, period="five-year-daily-history", as_of=as_of, facts=[current, *history], details={"field": field, "observation_count": len(history), "percentile_rule": "rank_min / n", "current": current.value})


def _universe_complete(universe: Sequence[CompanyData], config: ScoreConfig) -> bool:
    return config.universe_complete or (bool(universe) and all(company.metadata.get("universe_complete") is True for company in universe))


def _current_universe_values(universe: Sequence[CompanyData], field: str, as_of: date) -> list[tuple[CompanyData, Fact]]:
    result = []
    for company in universe:
        current = _current_daily(company, field, as_of, positive=True)
        if current is not None:
            result.append((company, current))
    return result


def _universe_percentile_rule(criterion_id: str, company: CompanyData, universe: Sequence[CompanyData], as_of: date, field: str, config: ScoreConfig) -> CriterionResult:
    if not _universe_complete(universe, config):
        return _unknown(criterion_id, as_of, "complete TWSE+TPEx ordinary-share universe required")
    current = _current_daily(company, field, as_of, positive=True)
    rows = _current_universe_values(universe, field, as_of)
    if current is None or not rows:
        return _unknown(criterion_id, as_of, f"valid current {field} and universe values required")
    values = [_value(fact) for _, fact in rows]
    numeric_values = [value for value in values if value is not None]
    percentile = _ascending_percentile(float(current.value), numeric_values)
    return _result(criterion_id, Status.PASS if percentile <= 0.50 else Status.FAIL, value=percentile, threshold=0.50, period=as_of.isoformat(), as_of=as_of, facts=[current, *[fact for _, fact in rows]], details={"field": field, "universe_count": len(rows), "percentile_rule": "rank_min / n", "direction": "lower_is_better"})


def _rank_top50_rule(criterion_id: str, company: CompanyData, universe: Sequence[CompanyData], as_of: date, field: str, config: ScoreConfig) -> CriterionResult:
    if not _universe_complete(universe, config):
        return _unknown(criterion_id, as_of, "complete TWSE+TPEx ordinary-share universe required")
    rows = _current_universe_values(universe, field, as_of)
    target = _current_daily(company, field, as_of, positive=True)
    if target is None or not rows:
        return _unknown(criterion_id, as_of, f"valid current {field} and universe values required")
    ordered = sorted(rows, key=lambda pair: (float(pair[1].value), pair[0].company_code))
    rank = next(index for index, (item, _) in enumerate(ordered, 1) if item.company_code == company.company_code and item.market == company.market)
    return _result(criterion_id, Status.PASS if rank <= 50 else Status.FAIL, value=rank, threshold=50, period=as_of.isoformat(), as_of=as_of, facts=[target, *[fact for _, fact in rows]], details={"field": field, "universe_count": len(rows), "rank_direction": "ascending", "tie_break": "company_code"})


def _dividend_year_end(as_of: date) -> tuple[int, ...]:
    end_year = as_of.year if (as_of.month == 12 and as_of.day == 31) else as_of.year - 1
    return tuple(range(end_year - 4, end_year + 1))


def _available_dividends(company: CompanyData, as_of: date, config: ScoreConfig) -> list[Any]:
    return [item for item in company.dividends if (config.include_special_dividends or not item.special) and item.is_available_as_of(as_of)]


def _annual_dividends(company: CompanyData, as_of: date, config: ScoreConfig) -> tuple[dict[int, float], list[Any]]:
    records = _available_dividends(company, as_of, config)
    totals: dict[int, float] = {}
    for item in records:
        totals[item.attribution_year] = totals.get(item.attribution_year, 0.0) + float(item.cash_per_share)
    return totals, records


def _trailing_yield(company: CompanyData, as_of: date, config: ScoreConfig) -> tuple[float | None, list[Any], Fact | None]:
    records = [item for item in _available_dividends(company, as_of, config) if as_date(item.ex_date) is not None and as_date(item.ex_date) > as_of - timedelta(days=365)]
    price = _price_on_or_before(company, as_of, as_of)
    if not records or price is None or _value(price) is None or float(price.value) <= 0:
        return None, records, price
    total = sum(float(item.cash_per_share) for item in records)
    return total / float(price.value) * 100, records, price


def _yield_rule(criterion_id: str, company: CompanyData, as_of: date, config: ScoreConfig, *, average: bool) -> CriterionResult:
    if average:
        years = _dividend_year_end(as_of)
        totals, records = _annual_dividends(company, as_of, config)
        yields: list[float] = []
        facts: list[Fact] = []
        for year in years:
            price = _price_on_or_before(company, date(year, 12, 31), as_of)
            if year not in totals or price is None or _value(price) is None or float(price.value) <= 0:
                return _unknown(criterion_id, as_of, "five attribution years require cash dividend and year-end/reference price", dividends=records, facts=facts)
            yields.append(totals[year] / float(price.value) * 100)
            facts.append(price)
        mean_yield = sum(yields) / len(yields)
        return _result(criterion_id, Status.PASS if mean_yield > 6 else Status.FAIL, value=mean_yield, threshold=6, period="five-complete-dividend-years", as_of=as_of, facts=facts, dividends=records, details={"annual_yield_percent": {str(year): value for year, value in zip(years, yields)}, "price_rule": "last trading close on or before December 31"})
    value, records, price = _trailing_yield(company, as_of, config)
    if value is None:
        return _unknown(criterion_id, as_of, "trailing cash dividend and as-of market price required", facts=[price], dividends=records)
    return _result(criterion_id, Status.PASS if value > 6 else Status.FAIL, value=value, threshold=6, period="trailing-365-days", as_of=as_of, facts=[price], dividends=records, details={"price_date": _date_for_fact(price).isoformat() if price and _date_for_fact(price) else None, "cash_only": True})


def _dividend_consecutive(criterion_id: str, company: CompanyData, as_of: date, config: ScoreConfig) -> CriterionResult:
    years = _dividend_year_end(as_of)
    totals, records = _annual_dividends(company, as_of, config)
    if any(year not in totals for year in years):
        return _unknown(criterion_id, as_of, "cash dividend required for every five attribution years", dividends=records)
    return _result(criterion_id, Status.PASS, value=True, threshold=5, period="five-complete-dividend-years", as_of=as_of, dividends=records, details={"attribution_years": list(years), "annual_cash_per_share": {str(year): totals[year] for year in years}})


def _payout_rule(criterion_id: str, company: CompanyData, as_of: date, config: ScoreConfig, *, mean: bool) -> CriterionResult:
    years = _dividend_year_end(as_of)
    totals, records = _annual_dividends(company, as_of, config)
    rows: list[tuple[int, Fact, float]] = []
    for year in years:
        eps = _available(company, "eps", f"{year:04d}-FY", as_of, period_type="annual")
        if year not in totals or eps is None or _value(eps) is None or float(eps.value) <= 0:
            return _unknown(criterion_id, as_of, "five-year payout requires cash dividend and positive EPS in every year", facts=[eps], dividends=records)
        rows.append((year, eps, totals[year] / float(eps.value) * 100))
    ratios = [value for _, _, value in rows]
    observed = sum(ratios) / 5 if mean else sum(value > 50 for value in ratios)
    condition = observed > 50 if mean else observed >= 3
    return _result(criterion_id, Status.PASS if condition else Status.FAIL, value=observed, threshold=50 if mean else 3, period="five-complete-fiscal-years", as_of=as_of, facts=[eps for _, eps, _ in rows], dividends=records, details={"payout_percent": {str(year): value for (year, _, value) in rows}, "negative_eps": "unknown"})


def _working_capital_days(company: CompanyData, period: str, as_of: date, *, kind: str, config: ScoreConfig) -> tuple[float | None, list[Fact], str | None]:
    begin_field = f"{kind}_begin"
    end_field = f"{kind}_end"
    begin = _available(company, begin_field, period, as_of, period_type="quarterly")
    end = _available(company, end_field, period, as_of, period_type="quarterly")
    facts = [begin, end]
    if begin is None or end is None or _value(begin) is None or _value(end) is None:
        return None, facts, f"{kind} beginning/end balances required"
    if kind == "receivables":
        denominator_fact = _available(company, "revenue", period, as_of, period_type="quarterly")
        denominator_name = "revenue"
    else:
        denominator_fact = _available(company, "cost_of_goods_sold", period, as_of, period_type="quarterly")
        denominator_name = "cost_of_goods_sold"
        if denominator_fact is None:
            revenue = _available(company, "revenue", period, as_of, period_type="quarterly")
            gross_profit = _available(company, "gross_profit", period, as_of, period_type="quarterly")
            if revenue is not None and gross_profit is not None and _value(revenue) is not None and _value(gross_profit) is not None:
                derived = float(revenue.value) - float(gross_profit.value)
                if derived <= 0:
                    return None, facts + [revenue, gross_profit], "derived COGS is non-positive"
                denominator = derived
                facts.extend((revenue, gross_profit))
                days = ((float(begin.value) + float(end.value)) / 2) / denominator * config.working_days
                return days, facts, "COGS derived as revenue minus gross profit"
            return None, facts + [revenue, gross_profit], "cost of goods sold required; revenue cannot substitute"
    denominator = _value(denominator_fact)
    if denominator is None or denominator <= 0:
        return None, facts + [denominator_fact], f"{denominator_name} must be positive"
    facts.append(denominator_fact)
    days = ((float(begin.value) + float(end.value)) / 2) / denominator * config.working_days
    return days, facts, None


def _turnover_rule(criterion_id: str, company: CompanyData, as_of: date, *, kind: str, config: ScoreConfig) -> CriterionResult:
    periods = company.periods("revenue", period_type="quarterly", as_of=as_of)
    if not periods:
        return _unknown(criterion_id, as_of, "quarterly revenue periods required")
    current_period = periods[-1]
    previous_period = previous_year_period(current_period)
    current_days, current_facts, current_reason = _working_capital_days(company, current_period, as_of, kind=kind, config=config)
    prior_days, prior_facts, prior_reason = _working_capital_days(company, previous_period, as_of, kind=kind, config=config)
    facts = current_facts + prior_facts
    if current_days is None or prior_days is None:
        return _unknown(criterion_id, as_of, current_reason or prior_reason or "turnover-days inputs unavailable", facts=facts, period=current_period)
    return _result(criterion_id, Status.PASS if current_days <= prior_days else Status.FAIL, value=current_days, threshold=prior_days, period=current_period, as_of=as_of, facts=facts, details={"current_days": current_days, "prior_year_same_quarter_days": prior_days, "days_in_year": config.working_days, "denominator": "revenue" if kind == "receivables" else "cost_of_goods_sold"})


def _listed_rule(criterion_id: str, company: CompanyData, as_of: date) -> CriterionResult:
    listed = company.listed_day
    if listed is None:
        return _unknown(criterion_id, as_of, "listing date unavailable")
    threshold_date = add_years(listed, 3)
    age_days = (as_of - listed).days
    return _result(criterion_id, Status.PASS if as_of > threshold_date else Status.FAIL, value=age_days / 365.2425, threshold=3, period=as_of.isoformat(), as_of=as_of, details={"listing_date": listed.isoformat(), "comparison": "calendar date strictly greater than listing date plus three years"})


def _annual_fcf_roe(company: CompanyData, year: int, as_of: date) -> tuple[float | None, list[Fact], str | None]:
    fields = {field: _available(company, field, f"{year:04d}-FY", as_of, period_type="annual") for field in ("cfo", "capex", "equity")}
    prior_equity = _available(company, "equity", f"{year - 1:04d}-FY", as_of, period_type="annual")
    facts = [*fields.values(), prior_equity]
    if any(item is None or _value(item) is None for item in fields.values()) or prior_equity is None or _value(prior_equity) is None:
        return None, facts, "FCF and two consecutive equity values required"
    denominator = (float(fields["equity"].value) + float(prior_equity.value)) / 2
    if denominator <= 0:
        return None, facts, "average shareholders equity must be positive"
    fcf = float(fields["cfo"].value) - float(fields["capex"].value)
    return fcf / denominator * 100, facts, None


def _latest_annual_year(company: CompanyData, as_of: date) -> int | None:
    periods = company.periods("cfo", period_type="annual", as_of=as_of)
    years = [int(match.group(1)) for period in periods if (match := re.fullmatch(r"(\d{4})-FY", period))]
    return max(years) if years else None


def _fcf_roe_not_down(criterion_id: str, company: CompanyData, as_of: date) -> CriterionResult:
    year = _latest_annual_year(company, as_of)
    if year is None:
        return _unknown(criterion_id, as_of, "latest annual FCF year unavailable")
    current, current_facts, current_reason = _annual_fcf_roe(company, year, as_of)
    prior, prior_facts, prior_reason = _annual_fcf_roe(company, year - 1, as_of)
    if current is None or prior is None:
        return _unknown(criterion_id, as_of, current_reason or prior_reason or "current and prior FCF ROE unavailable", facts=current_facts + prior_facts, period=f"{year:04d}-FY")
    return _result(criterion_id, Status.PASS if current >= prior else Status.FAIL, value=current, threshold=prior, period=f"{year:04d}-FY", as_of=as_of, facts=current_facts + prior_facts, details={"metric": "FCF ROE", "current_percent": current, "prior_percent": prior, "fcf_formula": "CFO - CapEx", "roe_formula": "FCF / average shareholders equity * 100"})


def _fcf_roe_top20(criterion_id: str, company: CompanyData, universe: Sequence[CompanyData], as_of: date, config: ScoreConfig) -> CriterionResult:
    if not _universe_complete(universe, config):
        return _unknown(criterion_id, as_of, "complete TWSE+TPEx ordinary-share universe required")
    rows: list[tuple[CompanyData, float, list[Fact]]] = []
    for item in universe:
        year = _latest_annual_year(item, as_of)
        if year is None:
            continue
        values: list[float] = []
        facts: list[Fact] = []
        complete = True
        for offset in (2, 1, 0):
            value, used, reason = _annual_fcf_roe(item, year - offset, as_of)
            if value is None:
                complete = False
                break
            values.append(value)
            facts.extend(fact for fact in used if fact is not None)
        if complete:
            rows.append((item, sum(values) / 3, facts))
    target = next((row for row in rows if row[0].company_code == company.company_code and row[0].market == company.market), None)
    if target is None or not rows:
        return _unknown(criterion_id, as_of, "three complete annual FCF ROE values for target and universe required")
    ordered = sorted(rows, key=lambda row: (-row[1], row[0].company_code))
    rank = next(index for index, row in enumerate(ordered, 1) if row[0].company_code == company.company_code and row[0].market == company.market)
    percentile = rank / len(rows)
    return _result(criterion_id, Status.PASS if percentile <= 0.20 else Status.FAIL, value=percentile, threshold=0.20, period="three-year-mean-fcf-roe", as_of=as_of, facts=target[2], details={"rank": rank, "universe_count": len(rows), "mean_fcf_roe_percent": target[1], "direction": "higher_is_better"})


def _operating_income_sum(criterion_id: str, company: CompanyData, as_of: date) -> CriterionResult:
    years = _annual_years(company, ("operating_income",), as_of, 3)
    rows = _annual_facts(company, ("operating_income",), years, as_of)
    if len(rows) != 3:
        return _unknown(criterion_id, as_of, "three complete annual operating-income rows required")
    total = sum(float(row["operating_income"].value) for row in rows)
    return _result(criterion_id, Status.PASS if total > 0 else Status.FAIL, value=total, threshold=0, period="three-complete-fiscal-years", as_of=as_of, facts=[row["operating_income"] for row in rows], details={"operating_income_by_year": {str(year): row["operating_income"].value for year, row in zip(years, rows)}})


def _current_cash_yield(company: CompanyData, as_of: date, config: ScoreConfig) -> tuple[float | None, list[Any], Fact | None]:
    return _trailing_yield(company, as_of, config)


def _combined_value_top50(criterion_id: str, company: CompanyData, universe: Sequence[CompanyData], as_of: date, config: ScoreConfig) -> CriterionResult:
    if not _universe_complete(universe, config):
        return _unknown(criterion_id, as_of, "complete TWSE+TPEx ordinary-share universe required")
    rows: list[tuple[CompanyData, float, list[Fact], list[Any]]] = []
    current_metrics: dict[str, list[tuple[CompanyData, Fact]]] = {field: _current_universe_values(universe, field, as_of) for field in ("pe", "pb")}
    yield_rows: list[tuple[CompanyData, float, list[Any], Fact | None]] = []
    for item in universe:
        yld, divs, price = _current_cash_yield(item, as_of, config)
        if yld is not None:
            yield_rows.append((item, yld, divs, price))
    pe_map = {item.company_code + ":" + item.market: fact for item, fact in current_metrics["pe"]}
    pb_map = {item.company_code + ":" + item.market: fact for item, fact in current_metrics["pb"]}
    yield_map = {item.company_code + ":" + item.market: (value, divs, price) for item, value, divs, price in yield_rows}
    if not pe_map or not pb_map or not yield_map:
        return _unknown(criterion_id, as_of, "current PE, PB, and cash-yield universe values required")
    pe_values = [_value(fact) for fact in pe_map.values()]
    pb_values = [_value(fact) for fact in pb_map.values()]
    yield_values = [item[0] for item in yield_map.values()]
    pe_values = [value for value in pe_values if value is not None]
    pb_values = [value for value in pb_values if value is not None]
    scores: list[tuple[CompanyData, float, list[Fact], list[Any]]] = []
    for item in universe:
        key = item.company_code + ":" + item.market
        pe_fact, pb_fact = pe_map.get(key), pb_map.get(key)
        yield_item = yield_map.get(key)
        if pe_fact is None or pb_fact is None or yield_item is None:
            continue
        pe_pct = _ascending_percentile(float(pe_fact.value), pe_values)
        pb_pct = _ascending_percentile(float(pb_fact.value), pb_values)
        yield_pct = sum(value <= yield_item[0] for value in yield_values) / len(yield_values)
        composite = (1 - pe_pct) + (1 - pb_pct) + yield_pct
        scores.append((item, composite, [pe_fact, pb_fact, yield_item[3]], yield_item[1]))
    if len(scores) < 50 and len(universe) >= 50:
        # A full universe can still have less than 50 valid composite rows;
        # ranking remains valid but the result reports its actual population.
        pass
    ordered = sorted(scores, key=lambda row: (-row[1], row[0].company_code))
    target = next((row for index, row in enumerate(ordered, 1) if row[0].company_code == company.company_code and row[0].market == company.market), None)
    if target is None:
        return _unknown(criterion_id, as_of, "target lacks one of PE, PB, or cash-yield metrics")
    rank = next(index for index, row in enumerate(ordered, 1) if row[0].company_code == company.company_code and row[0].market == company.market)
    return _result(criterion_id, Status.PASS if rank <= 50 else Status.FAIL, value=rank, threshold=50, period=as_of.isoformat(), as_of=as_of, facts=target[2], dividends=target[3], details={"formula_type": "transparent_proxy", "statementdog_exact": False, "composite": target[1], "components": "(1 - PE percentile) + (1 - PB percentile) + yield percentile", "valid_universe_count": len(ordered), "tie_break": "company_code"})


def _major_holder_ratio(company: CompanyData, period: str, as_of: date) -> tuple[float | None, list[Fact], bool, str | None]:
    direct = _available(company, "major_holder_ratio", period, as_of, period_type="monthly")
    if direct is not None and _value(direct) is not None:
        return float(direct.value), [direct], direct.proxy, None
    shares = _available(company, "major_holder_shares", period, as_of, period_type="monthly")
    denominator = _available(company, "major_holder_denominator", period, as_of, period_type="monthly")
    if shares is None or denominator is None or _value(shares) is None or _value(denominator) is None or float(denominator.value) <= 0:
        return None, [shares, denominator], False, "major-holder shares and denominator required"
    return float(shares.value) / float(denominator.value), [shares, denominator], shares.proxy or denominator.proxy, None


def _month_shift(period: str, months: int) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if not match:
        raise ValueError(f"monthly period required: {period}")
    year, month = int(match.group(1)), int(match.group(2))
    ordinal = year * 12 + month - 1 + months
    return f"{ordinal // 12:04d}-{ordinal % 12 + 1:02d}"


def _chip_ratio_up(criterion_id: str, company: CompanyData, as_of: date) -> CriterionResult:
    periods = sorted(set(company.periods("major_holder_ratio", period_type="monthly", as_of=as_of)) | set(company.periods("major_holder_shares", period_type="monthly", as_of=as_of)))
    periods = periods[-3:]
    if len(periods) != 3:
        return _unknown(criterion_id, as_of, "three chronological major-holder month-end observations required")
    ratios: list[float] = []
    facts: list[Fact] = []
    proxy = False
    for period in periods:
        ratio, used, is_proxy, reason = _major_holder_ratio(company, period, as_of)
        if ratio is None:
            return _unknown(criterion_id, as_of, reason or "major-holder ratio unavailable", facts=used, period=period)
        ratios.append(ratio)
        facts.extend(item for item in used if item is not None)
        proxy = proxy or is_proxy
    return _result(criterion_id, Status.PASS if ratios[0] < ratios[1] < ratios[2] else Status.FAIL, value=ratios, threshold="strict_increase", period=",".join(periods), as_of=as_of, facts=facts, proxy=proxy, details={"ratio_by_month": dict(zip(periods, ratios)), "ratio_formula": "major_holder_shares / major_holder_denominator"})


def _chip_director_not_down(criterion_id: str, company: CompanyData, as_of: date) -> CriterionResult:
    periods = company.periods("director_supervisor_aggregate_holdings", period_type="monthly", as_of=as_of)
    if not periods:
        return _unknown(criterion_id, as_of, "director/supervisor monthly holdings unavailable")
    latest_period = periods[-1]
    prior_period = _month_shift(latest_period, -12)
    latest = _available(company, "director_supervisor_aggregate_holdings", latest_period, as_of, period_type="monthly")
    prior = _available(company, "director_supervisor_aggregate_holdings", prior_period, as_of, period_type="monthly")
    if latest is None or prior is None:
        return _unknown(criterion_id, as_of, "latest and exact twelve-month-prior aggregate holdings required", facts=(latest, prior), period=latest_period)
    return _result(criterion_id, Status.PASS if float(latest.value) >= float(prior.value) else Status.FAIL, value=float(latest.value), threshold=float(prior.value), period=latest_period, as_of=as_of, facts=(latest, prior), details={"latest_period": latest_period, "prior_period": prior_period, "aggregate_scope": "director_supervisor_aggregate_holdings"})


def _chip_shareholder_down(criterion_id: str, company: CompanyData, as_of: date) -> CriterionResult:
    periods = company.periods("shareholder_count", period_type="monthly", as_of=as_of)[-3:]
    if len(periods) != 3:
        return _unknown(criterion_id, as_of, "three chronological TDCC month-end shareholder counts required")
    facts = [_available(company, "shareholder_count", period, as_of, period_type="monthly") for period in periods]
    if any(item is None for item in facts):
        return _unknown(criterion_id, as_of, "TDCC shareholder count missing", facts=facts, period=",".join(periods))
    values = [float(item.value) for item in facts if item is not None]
    return _result(criterion_id, Status.PASS if values[0] > values[1] > values[2] else Status.FAIL, value=values, threshold="strict_decrease", period=",".join(periods), as_of=as_of, facts=facts, details={"count_by_month": dict(zip(periods, values)), "source_rule": "latest available weekly observation normalized to month-end"})


def _dispatch(criterion_id: str, company: CompanyData, universe: Sequence[CompanyData], as_of: date, config: ScoreConfig) -> CriterionResult:
    if criterion_id == "safety.fcf_positive_3_of_5":
        return _fcf_rule(criterion_id, company, as_of, mean=False)
    if criterion_id == "safety.fcf_mean_positive":
        return _fcf_rule(criterion_id, company, as_of, mean=True)
    if criterion_id == "safety.cfo_ni_ratio_3_of_5":
        return _cfo_ni_rule(criterion_id, company, as_of, mean=False)
    if criterion_id == "safety.cfo_ni_ratio_mean":
        return _cfo_ni_rule(criterion_id, company, as_of, mean=True)
    if criterion_id == "safety.receivable_days_not_worse":
        return _turnover_rule(criterion_id, company, as_of, kind="receivables", config=config)
    if criterion_id == "safety.inventory_days_not_worse":
        return _turnover_rule(criterion_id, company, as_of, kind="inventory", config=config)
    if criterion_id == "dividend.trailing_yield_gt_6":
        return _yield_rule(criterion_id, company, as_of, config, average=False)
    if criterion_id == "dividend.avg_yield_5y_gt_6":
        return _yield_rule(criterion_id, company, as_of, config, average=True)
    if criterion_id == "dividend.consecutive_5y":
        return _dividend_consecutive(criterion_id, company, as_of, config)
    if criterion_id == "dividend.payout_gt_50_3_of_5":
        return _payout_rule(criterion_id, company, as_of, config, mean=False)
    if criterion_id == "dividend.payout_mean_gt_50":
        return _payout_rule(criterion_id, company, as_of, config, mean=True)
    if criterion_id == "growth.monthly_revenue_yoy_3_consecutive":
        return _monthly_revenue_rule(criterion_id, company, as_of)
    if criterion_id.startswith("growth."):
        field = {
            "growth.gross_profit_yoy_gt_0": "gross_profit",
            "growth.operating_income_yoy_gt_0": "operating_income",
            "growth.pretax_income_yoy_gt_0": "pretax_income",
            "growth.after_tax_income_yoy_gt_0": "after_tax_income",
        }[criterion_id]
        return _quarter_yoy(criterion_id, company, as_of, field)
    if criterion_id == "value.pe_lowest_20pct_5y":
        return _valuation_history_rule(criterion_id, company, as_of, "pe", config)
    if criterion_id == "value.pb_lowest_20pct_5y":
        return _valuation_history_rule(criterion_id, company, as_of, "pb", config)
    if criterion_id == "value.pe_below_50pct_universe":
        return _universe_percentile_rule(criterion_id, company, universe, as_of, "pe", config)
    if criterion_id == "value.pb_below_50pct_universe":
        return _universe_percentile_rule(criterion_id, company, universe, as_of, "pb", config)
    if criterion_id == "value.trailing_yield_gt_6":
        return _yield_rule(criterion_id, company, as_of, config, average=False)
    if criterion_id == "value.avg_yield_5y_gt_6":
        return _yield_rule(criterion_id, company, as_of, config, average=True)
    if criterion_id == "turnaround.pb_lt_3":
        fact = _current_daily(company, "pb", as_of, positive=True)
        if fact is None:
            return _unknown(criterion_id, as_of, "current positive PB unavailable")
        return _result(criterion_id, Status.PASS if float(fact.value) < 3 else Status.FAIL, value=float(fact.value), threshold=3, period=as_of.isoformat(), as_of=as_of, facts=(fact,))
    if criterion_id == "turnaround.f_score_ge_8":
        result = calculate_f_score(company, current_year=_latest_annual_year(company, as_of) or 0, as_of=as_of)
        if result.status == Status.NOT_APPLICABLE:
            return _not_applicable(criterion_id, as_of, result.reason or "not applicable")
        facts = [fact for field in ("net_income", "cfo", "total_assets", "current_assets", "current_liabilities", "long_term_debt", "shares", "gross_profit", "revenue") for fact in company.all_facts(field, period_type="annual")]
        return _result(criterion_id, result.status, value=result.score if result.status != Status.UNKNOWN else None, threshold=8, period=f"{result.current_year:04d}-FY" if result.current_year else None, as_of=as_of, facts=facts, reason=result.reason, details={"f_score": result.to_dict()})
    if criterion_id == "turnaround.pb_lowest_top50":
        return _rank_top50_rule(criterion_id, company, universe, as_of, "pb", config)
    if criterion_id == "continuity.listed_over_3y":
        return _listed_rule(criterion_id, company, as_of)
    if criterion_id == "continuity.croic_not_down":
        return _fcf_roe_not_down(criterion_id, company, as_of)
    if criterion_id == "continuity.croic_3y_top20":
        return _fcf_roe_top20(criterion_id, company, universe, as_of, config)
    if criterion_id == "continuity.operating_income_3y_sum_gt_0":
        return _operating_income_sum(criterion_id, company, as_of)
    if criterion_id == "continuity.combined_value_top50":
        return _combined_value_top50(criterion_id, company, universe, as_of, config)
    if criterion_id == "chip.major_holder_ratio_up_3m":
        return _chip_ratio_up(criterion_id, company, as_of)
    if criterion_id == "chip.director_holdings_not_down_12m":
        return _chip_director_not_down(criterion_id, company, as_of)
    if criterion_id == "chip.shareholder_count_down_3m":
        return _chip_shareholder_down(criterion_id, company, as_of)
    raise KeyError(f"unknown criterion: {criterion_id}")


def evaluate_criterion(
    criterion_id: str,
    company: CompanyData,
    universe: Sequence[CompanyData],
    *,
    as_of: date | str,
    config: ScoreConfig | None = None,
) -> CriterionResult:
    cutoff = _cutoff(as_of)
    config = config or ScoreConfig()
    if criterion_id not in {item for values in CATEGORY_CRITERIA.values() for item in values}:
        raise KeyError(f"unknown criterion: {criterion_id}")
    return _dispatch(criterion_id, company, tuple(universe), cutoff, config)


def evaluate_all(
    company: CompanyData,
    universe: Sequence[CompanyData],
    *,
    as_of: date | str,
    config: ScoreConfig | None = None,
) -> tuple[CriterionResult, ...]:
    return tuple(evaluate_criterion(criterion_id, company, universe, as_of=as_of, config=config) for category in CATEGORY_ORDER for criterion_id in CATEGORY_CRITERIA[category])


def build_categories(results: Sequence[CriterionResult], config: ScoreConfig) -> dict[str, CategoryScore]:
    by_id = {result.criterion_id: result for result in results}
    return {category: CategoryScore(category, tuple(by_id[criterion_id] for criterion_id in CATEGORY_CRITERIA[category]), float(config.category_thresholds[category])) for category in CATEGORY_ORDER}


def methodology() -> dict[str, Any]:
    return {
        "formula_version": FORMULA_VERSION,
        "fcf": "CFO - positive Capital Expenditure",
        "working_days": 365,
        "price_rule": "last trading close on or before target date",
        "rank_rule": "rank_min / n; deterministic company_code tie-break for top-N",
        "unknown_rule": "missing, stale, future-announced, zero-denominator, or incomplete history is unknown",
        "composite": "(1 - PE percentile) + (1 - PB percentile) + yield percentile; transparent_proxy; statementdog_exact=false",
        "statementdog_source": "external calibration only; never read by scorer",
        "criteria": {criterion_id: {"label": CRITERION_LABELS[criterion_id], "category": category} for category, ids in CATEGORY_CRITERIA.items() for criterion_id in ids},
    }
