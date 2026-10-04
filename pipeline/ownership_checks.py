"""Pure evaluators for reference-only ownership/chip indicators."""

from __future__ import annotations

from datetime import date
import math
from typing import Any, Iterable

FORMULA_VERSION = "chip-reference-v1"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _month(value: Any) -> str | None:
    text = str(value or "")[:7].replace("/", "-")
    try:
        date.fromisoformat(f"{text}-01")
    except ValueError:
        return None
    return text


def _consecutive(months: list[str]) -> bool:
    parsed = [date.fromisoformat(f"{month}-01") for month in months]
    return all((current.year * 12 + current.month) == (previous.year * 12 + previous.month + 1) for previous, current in zip(parsed, parsed[1:]))


def _source_refs(rows: Iterable[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for row in rows:
        values = row.get("sourceRefs") if isinstance(row, dict) else None
        if isinstance(values, str):
            values = [values]
        for value in values or []:
            if value and value not in refs:
                refs.append(str(value))
    return refs


def _check(status: str, *, value: Any = "—", period: str | None = "—", raw_values: Any = None, explanation: str = "") -> dict[str, Any]:
    result = {"status": status, "value": value, "period": period, "sourceRefs": []}
    if raw_values is not None:
        result["rawValues"] = raw_values
    if explanation:
        result["explanation"] = explanation
    return result


def _has_field(row: dict[str, Any], field: str) -> bool:
    observed = row.get("observedFields")
    return field in observed if isinstance(observed, list) else field in row


def _monthly_observations(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    months = sorted({_month(row.get("period")) for row in rows if _month(row.get("period")) and _has_field(row, field)})
    result = {}
    for month in months:
        candidates = [row for row in rows if _month(row.get("period")) == month and _has_field(row, field)]
        observation_date = lambda row: str(row.get("sourceDate") or row.get("asOf") or month)
        latest_date = max(observation_date(row) for row in candidates)
        selected = [row for row in candidates if observation_date(row) == latest_date]
        numeric_fields = [field] + (["directorDenominator", "directorSupervisorShares", "officialDirectorSupervisorShares"] if field == "directorSupervisorPct" else [])
        fingerprints = {tuple(_number(row.get(key)) for key in numeric_fields) for row in selected}
        scope_fingerprints = {tuple(sorted(row.get("directorScope") or [])) for row in selected} if field == "directorSupervisorPct" else {()}
        conflict = len(fingerprints) > 1 or len(scope_fingerprints) > 1
        chosen = sorted(selected, key=lambda row: repr(sorted(row.items())))[0]
        flags = {key: False for key in ("directorIdentityConsistent", "directorTotalMatches", "directorTotalConsistent") if any(row.get(key) is False for row in selected)}
        unsafe = any(row.get("comparabilityStatus") in {"unsafe", "invalid", "ambiguous", "unknown", "not_comparable"} for row in selected)
        result[month] = {**chosen, **flags, **({"comparabilityStatus": "unsafe"} if unsafe else {}),
                         "_conflict": conflict, "_conflictValues": "／".join(_format(value) for value in sorted({_number(row.get(field)) for row in selected}, key=lambda value: float("inf") if value is None else value)), "_evidenceRows": selected}
    return result


def _trend(rows: list[dict[str, Any]], field: str, *, increasing: bool, label: str, evaluation_date: date | None = None) -> dict[str, Any]:
    by_month = _monthly_observations(rows, field)
    if evaluation_date:
        index = evaluation_date.year * 12 + evaluation_date.month - 1
        months = [f"{(index - offset) // 12:04d}-{(index - offset) % 12 + 1:02d}" for offset in (3, 2, 1)]
    else:
        months = sorted(by_month)[-3:]
    if not months:
        return _check("unknown", explanation=f"{label}缺少三個有效且連續月份。")
    used = [row for month in months if month in by_month for row in by_month[month]["_evidenceRows"]]
    values = [_number(by_month.get(month, {}).get(field)) for month in months]
    conflicts = any(by_month.get(month, {}).get("_conflict") for month in months)
    complete = len(months) == 3 and _consecutive(months) and all(value is not None for value in values) and not conflicts
    passed = complete and all((left < right if increasing else left > right) for left, right in zip(values, values[1:]))
    result = _check("pass" if passed else "fail" if complete else "unknown", value=" → ".join(f"{by_month[month]['_conflictValues']}（資料衝突）" if by_month.get(month, {}).get("_conflict") else _format(value) for month, value in zip(months, values)), period=f"{months[0]}..{months[-1]}", raw_values=values if all(value is not None for value in values) and not conflicts else None, explanation=f"{label}三個完整月份觀察值逐期符合嚴格趨勢。" if passed else f"{label}未符合嚴格逐期趨勢。" if complete else f"{label}缺少三個有效且連續的完整月份。")
    return {**result, "sourceRefs": _source_refs(used), "_usedRows": used}


def _format(value: float | None) -> str:
    return f"{value:g}" if value is not None else "?"


def _director_check(rows: list[dict[str, Any]], *, evaluation_date: date | None = None) -> dict[str, Any]:
    eligible = [row for row in rows if evaluation_date is None or (_month(row.get("period")) or "9999-99") < evaluation_date.strftime("%Y-%m")]
    by_month = _monthly_observations(eligible, "directorSupervisorPct")
    if not by_month:
        return _check("unknown", explanation="缺少董監持股有效月份或分母。")
    latest_month = max(by_month)
    latest_date = date.fromisoformat(f"{latest_month}-01")
    prior_month = f"{latest_date.year - 1:04d}-{latest_date.month:02d}"
    latest, prior = by_month[latest_month], by_month.get(prior_month, {})
    latest_value, prior_value = _number(latest.get("directorSupervisorPct")), _number(prior.get("directorSupervisorPct"))
    latest_denominator, prior_denominator = _number(latest.get("directorDenominator")), _number(prior.get("directorDenominator"))
    valid_latest = latest_value is not None and latest_denominator is not None and latest_denominator > 0
    valid_prior = prior_value is not None and prior_denominator is not None and prior_denominator > 0
    conflict = any(row.get("_conflict") for row in (latest, prior))
    unsafe = conflict or any(row.get(key) is False for row in (latest, prior) for key in ("directorIdentityConsistent", "directorTotalMatches", "directorTotalConsistent"))
    unsafe = unsafe or any(row.get("comparabilityStatus") in {"unsafe", "invalid", "ambiguous", "unknown", "not_comparable"} for row in (latest, prior))
    scopes = [row.get("directorScope") for row in (latest, prior)]
    scope_matches = not any(scopes) or all(isinstance(scope, list) and scope for scope in scopes) and set(scopes[0]) == set(scopes[1])
    comparable = valid_latest and valid_prior and latest_denominator == prior_denominator and not unsafe and scope_matches
    if not valid_latest:
        explanation = "最新董監持股資料無效或缺少分母。"
    elif not valid_prior:
        explanation = "缺少恰好十二個月前的有效董監持股或分母。"
    elif unsafe or not scope_matches:
        explanation = "董監身份、官方合計或統計範圍無法確認可比。"
    elif not comparable:
        explanation = "最新與十二個月前分母不一致。"
    else:
        explanation = "董監持股較去年同月持平或增加。" if latest_value >= prior_value else "董監持股低於去年同月。"
    official_shares = _number(latest.get("officialDirectorSupervisorShares"))
    verified_shares = _number(latest.get("directorSupervisorShares")) if latest.get("directorIdentityConsistent") is True and latest.get("directorTotalMatches") is not False else None
    shares = official_shares if official_shares is not None else verified_shares
    value = f"{_format(latest_value)}% vs {_format(prior_value)}%"
    if conflict:
        conflicting = latest if latest.get("_conflict") else prior
        value = f"{conflicting['_conflictValues']}%（資料衝突）；比較待確認"
    elif latest_value is None and shares is not None and shares >= 0:
        value = f"{'官方合計 ' if official_shares is not None else ''}{shares:.0f}股；比例待補"
    result = _check("pass" if comparable and latest_value >= prior_value else "fail" if comparable else "unknown", value=value, period=f"{latest_month} vs {prior_month}", raw_values={"latest": latest_value, "prior12m": prior_value} if latest_value is not None and prior_value is not None and not conflict else None, explanation=explanation)
    used = latest.get("_evidenceRows", []) + prior.get("_evidenceRows", [])
    return {**result, "sourceRefs": _source_refs(used), "_usedRows": used}


def _publication(row: dict[str, Any]) -> str | None:
    timestamps = []
    for key in ("availableAt", "publishedAt"):
        value = row.get(key)
        if value:
            try:
                date.fromisoformat(str(value)[:10])
            except ValueError:
                continue
            timestamps.append(str(value))
    return max(timestamps, default=None)


def _with_observation_metadata(check: dict[str, Any]) -> dict[str, Any]:
    used = check.get("_usedRows", [])
    source_dates = list(dict.fromkeys(str(row["sourceDate"]) for row in used if row.get("sourceDate")))
    retrieved = [str(row["retrievedAt"]) for row in used if row.get("retrievedAt")]
    backfill = any(row.get("historicalBackfill") is True and _publication(row) is None for row in used)
    result = {key: value for key, value in check.items() if key != "_usedRows"}
    return {**result, "sourceDates": source_dates, "retrievedAt": max(retrieved, default=None), "historicalBackfill": backfill}


def evaluate_chip_reference(
    ownership_rows: Iterable[dict[str, Any]], *, data_freshness: str = "current",
    institutional_daily: Iterable[dict[str, Any]] | None = None,
    evaluation_date: date | str | None = None,
) -> dict[str, Any]:
    """Evaluate the three frozen indicators; institutional flow is intentionally ignored."""
    cutoff = date.fromisoformat(evaluation_date[:10]) if isinstance(evaluation_date, str) else evaluation_date
    observations = [observation for row in ownership_rows if isinstance(row, dict)
                    for observation in (row.get("sourceObservations") or [row]) if isinstance(observation, dict)]
    rows = [row for row in observations
            if (cutoff is None or _publication(row) is None or date.fromisoformat(_publication(row)[:10]) <= cutoff)]
    large = _trend(rows, "largeHolderPct", increasing=True, label="大股東持股比重", evaluation_date=cutoff)
    director = _director_check(rows, evaluation_date=cutoff)
    shareholders = _trend(rows, "shareholderCount", increasing=False, label="總股東人數", evaluation_date=cutoff)
    checks = (large, director, shareholders)
    used_rows = [row for row in rows if any(row is used for check in checks for used in check.get("_usedRows", []))]
    refs = _source_refs(used_rows)
    publications = [_publication(row) for row in used_rows]
    large, director, shareholders = (_with_observation_metadata(check) for check in checks)
    statuses = [large["status"], director["status"], shareholders["status"]]
    return {
        "schemaVersion": FORMULA_VERSION,
        "status": "fail" if "fail" in statuses else "unknown" if "unknown" in statuses else "pass",
        "displayOnly": True,
        "formulaVersion": FORMULA_VERSION,
        "dataFreshness": data_freshness if data_freshness in {"current", "stale", "unavailable"} else "unknown",
        "largeHolderTrend": large,
        "directorSupervisor12m": director,
        "shareholderCountTrend": shareholders,
        "sourceRefs": refs,
        "availableAt": max(publications) if publications and all(publications) else None,
    }


# Alternate name for callers using the indicator's domain terminology.
evaluate_ownership_chip_reference = evaluate_chip_reference
