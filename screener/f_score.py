"""Pure Piotroski F-score calculation over normalized annual facts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from .public_data_models import CompanyData, Fact, Status, as_date, previous_year_period

F_SCORE_ITEM_IDS = (
    "roa_positive",
    "cfo_positive",
    "cfo_gt_net_income",
    "debt_decrease",
    "current_ratio_increase",
    "no_new_shares",
    "roa_increase",
    "gross_margin_increase",
    "asset_turnover_increase",
)


@dataclass(frozen=True)
class FScoreItem:
    item_id: str
    status: Status
    value: float | bool | None = None
    reason: str | None = None
    source_snapshot: tuple[str, ...] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        status = self.status if isinstance(self.status, Status) else Status(str(self.status))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source_snapshot", tuple(sorted(self.source_snapshot)))
        object.__setattr__(self, "details", dict(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "status": self.status.value,
            "value": self.value,
            "reason": self.reason,
            "source_snapshot": list(self.source_snapshot),
            "details": self.details,
        }


@dataclass(frozen=True)
class FScoreResult:
    score: int | None
    status: Status
    items: Mapping[str, FScoreItem]
    current_year: int
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "status": self.status.value,
            "current_year": self.current_year,
            "reason": self.reason,
            "items": {key: self.items[key].to_dict() for key in F_SCORE_ITEM_IDS},
        }


def _annual_fact(company: CompanyData, field: str, year: int, as_of: date) -> Fact | None:
    return company.get_fact(field, f"{year:04d}-FY", as_of=as_of)


def _numeric_facts(company: CompanyData, fields: tuple[str, ...], years: tuple[int, ...], as_of: date) -> dict[tuple[str, int], Fact]:
    result: dict[tuple[str, int], Fact] = {}
    for field in fields:
        for year in years:
            fact = _annual_fact(company, field, year, as_of)
            if fact is not None:
                result[(field, year)] = fact
    return result


def _sources(*facts: Fact | None) -> tuple[str, ...]:
    return tuple(sorted({fact.content_sha256 for fact in facts if fact is not None}))


def _unknown(item_id: str, reason: str, *facts: Fact | None, details: Mapping[str, Any] | None = None) -> FScoreItem:
    return FScoreItem(item_id, Status.UNKNOWN, reason=reason, source_snapshot=_sources(*facts), details=details or {})


def _boolean_item(item_id: str, condition: bool, value: float | bool, *facts: Fact | None, details: Mapping[str, Any] | None = None) -> FScoreItem:
    return FScoreItem(
        item_id,
        Status.PASS if condition else Status.FAIL,
        value=value,
        source_snapshot=_sources(*facts),
        details=details or {},
    )


def _ratio(numerator: Fact | None, denominator: float | None) -> float | None:
    if numerator is None or numerator.value is None or denominator is None or denominator == 0:
        return None
    return float(numerator.value) / denominator


def _is_financial(company: CompanyData) -> bool:
    return bool(company.metadata.get("is_financial")) or str(company.metadata.get("industry_group", "")).lower() in {"financial", "finance", "banking"}


def calculate_f_score(company: CompanyData, *, current_year: int, as_of: date | str) -> FScoreResult:
    cutoff = as_date(as_of)
    if cutoff is None:
        raise ValueError("as_of is required")
    if _is_financial(company):
        items = {item_id: FScoreItem(item_id, Status.NOT_APPLICABLE, reason="financial industry: Piotroski accounting fields are not applicable") for item_id in F_SCORE_ITEM_IDS}
        return FScoreResult(None, Status.NOT_APPLICABLE, items, current_year, reason="financial industry")

    y = current_year
    p = current_year - 1
    pp = current_year - 2
    values = _numeric_facts(
        company,
        ("net_income", "cfo", "total_assets", "current_assets", "current_liabilities", "long_term_debt", "shares", "gross_profit", "revenue"),
        (pp, p, y),
        cutoff,
    )
    ni_y, ni_p = values.get(("net_income", y)), values.get(("net_income", p))
    cfo_y, cfo_p = values.get(("cfo", y)), values.get(("cfo", p))
    assets_y, assets_p, assets_pp = values.get(("total_assets", y)), values.get(("total_assets", p)), values.get(("total_assets", pp))
    ca_y, ca_p = values.get(("current_assets", y)), values.get(("current_assets", p))
    cl_y, cl_p = values.get(("current_liabilities", y)), values.get(("current_liabilities", p))
    debt_y, debt_p = values.get(("long_term_debt", y)), values.get(("long_term_debt", p))
    shares_y, shares_p = values.get(("shares", y)), values.get(("shares", p))
    gp_y, gp_p = values.get(("gross_profit", y)), values.get(("gross_profit", p))
    rev_y, rev_p = values.get(("revenue", y)), values.get(("revenue", p))

    avg_assets_y = ((float(assets_y.value) + float(assets_p.value)) / 2) if assets_y and assets_p else None
    avg_assets_p = ((float(assets_p.value) + float(assets_pp.value)) / 2) if assets_p and assets_pp else None
    roa_y = _ratio(ni_y, avg_assets_y)
    roa_p = _ratio(ni_p, avg_assets_p)
    current_ratio_y = _ratio(ca_y, float(cl_y.value) if cl_y else None)
    current_ratio_p = _ratio(ca_p, float(cl_p.value) if cl_p else None)
    gross_margin_y = _ratio(gp_y, float(rev_y.value) if rev_y else None)
    gross_margin_p = _ratio(gp_p, float(rev_p.value) if rev_p else None)
    turnover_y = _ratio(rev_y, avg_assets_y)
    turnover_p = _ratio(rev_p, avg_assets_p)

    items: dict[str, FScoreItem] = {}
    if ni_y is None or avg_assets_y is None or avg_assets_y <= 0:
        items["roa_positive"] = _unknown("roa_positive", "current ROA denominator unavailable or non-positive", ni_y, assets_y, assets_p)
    else:
        items["roa_positive"] = _boolean_item("roa_positive", roa_y > 0, roa_y, ni_y, assets_y, assets_p, details={"roa": roa_y})
    if cfo_y is None:
        items["cfo_positive"] = _unknown("cfo_positive", "current CFO unavailable", cfo_y)
    else:
        items["cfo_positive"] = _boolean_item("cfo_positive", float(cfo_y.value) > 0, float(cfo_y.value), cfo_y)
    if cfo_y is None or ni_y is None:
        items["cfo_gt_net_income"] = _unknown("cfo_gt_net_income", "current CFO or net income unavailable", cfo_y, ni_y)
    else:
        items["cfo_gt_net_income"] = _boolean_item("cfo_gt_net_income", float(cfo_y.value) > float(ni_y.value), float(cfo_y.value) - float(ni_y.value), cfo_y, ni_y, details={"cfo": cfo_y.value, "net_income": ni_y.value})
    if debt_y is None or debt_p is None:
        items["debt_decrease"] = _unknown("debt_decrease", "long-term debt comparison unavailable", debt_y, debt_p)
    else:
        items["debt_decrease"] = _boolean_item("debt_decrease", float(debt_y.value) < float(debt_p.value), float(debt_p.value) - float(debt_y.value), debt_y, debt_p)
    if current_ratio_y is None or current_ratio_p is None:
        items["current_ratio_increase"] = _unknown("current_ratio_increase", "current ratio denominator unavailable or zero", ca_y, cl_y, ca_p, cl_p)
    else:
        items["current_ratio_increase"] = _boolean_item("current_ratio_increase", current_ratio_y > current_ratio_p, current_ratio_y - current_ratio_p, ca_y, cl_y, ca_p, cl_p, details={"current": current_ratio_y, "prior": current_ratio_p})
    if shares_y is None or shares_p is None:
        items["no_new_shares"] = _unknown("no_new_shares", "shares outstanding comparison unavailable", shares_y, shares_p)
    else:
        items["no_new_shares"] = _boolean_item("no_new_shares", float(shares_y.value) <= float(shares_p.value), float(shares_p.value) - float(shares_y.value), shares_y, shares_p)
    if roa_y is None or roa_p is None:
        items["roa_increase"] = _unknown("roa_increase", "ROA comparison requires three annual asset observations", ni_y, ni_p, assets_y, assets_p, assets_pp)
    else:
        items["roa_increase"] = _boolean_item("roa_increase", roa_y > roa_p, roa_y - roa_p, ni_y, ni_p, assets_y, assets_p, assets_pp, details={"current": roa_y, "prior": roa_p})
    if gross_margin_y is None or gross_margin_p is None:
        items["gross_margin_increase"] = _unknown("gross_margin_increase", "gross margin denominator unavailable or zero", gp_y, gp_p, rev_y, rev_p)
    else:
        items["gross_margin_increase"] = _boolean_item("gross_margin_increase", gross_margin_y > gross_margin_p, gross_margin_y - gross_margin_p, gp_y, gp_p, rev_y, rev_p, details={"current": gross_margin_y, "prior": gross_margin_p})
    if turnover_y is None or turnover_p is None:
        items["asset_turnover_increase"] = _unknown("asset_turnover_increase", "asset turnover requires three annual asset observations", rev_y, rev_p, assets_y, assets_p, assets_pp)
    else:
        items["asset_turnover_increase"] = _boolean_item("asset_turnover_increase", turnover_y > turnover_p, turnover_y - turnover_p, rev_y, rev_p, assets_y, assets_p, assets_pp, details={"current": turnover_y, "prior": turnover_p})

    score = sum(item.status == Status.PASS for item in items.values())
    status = Status.UNKNOWN if any(item.status == Status.UNKNOWN for item in items.values()) else (Status.PASS if score >= 8 else Status.FAIL)
    return FScoreResult(score, status, items, current_year)
