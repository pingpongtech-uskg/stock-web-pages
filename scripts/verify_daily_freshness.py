#!/usr/bin/env python3
"""Fail closed when a daily release did not reach the current market session."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object expected: {path}")
    return value


def save(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def latest_market_date(config: dict[str, Any]) -> str | None:
    universe = config.get("universe")
    dates = universe.get("marketDates") if isinstance(universe, dict) else []
    valid: list[str] = []
    for value in dates if isinstance(dates, list) else []:
        text = str(value or "")[:10]
        try:
            date.fromisoformat(text)
        except ValueError:
            continue
        valid.append(text)
    return max(valid) if valid else None


def freshness_errors(data_dir: Path, config_path: Path, requested_market_date: str | None = None) -> list[str]:
    release = load(data_dir / "latest.json")
    config = load(config_path)
    expected = latest_market_date(config)
    errors: list[str] = []
    if requested_market_date:
        try:
            if date.fromisoformat(requested_market_date).isoformat() != requested_market_date:
                raise ValueError('exact ISO date required')
        except ValueError:
            return ['requested_market_date_invalid']
        if expected != requested_market_date:
            errors.append(f'official_market_date:{expected}!={requested_market_date}')
        expected = requested_market_date
    if (config.get('universe') or {}).get('stale') or (release.get('coverage') or {}).get('universeStale'):
        errors.append('official_universe_stale')
    if expected is None:
        return ["official_universe_market_date_missing"]
    if str(release.get("marketDate") or "") != expected:
        errors.append(f"release_market_date:{release.get('marketDate')}!={expected}")

    indicator = (release.get("marketIndicators") or {}).get("volumeMultiple00631L")
    if not isinstance(indicator, dict):
        errors.append("00631L_indicator_missing")
    elif str(indicator.get("marketDate") or "") != expected:
        errors.append(f"00631L_market_date:{indicator.get('marketDate')}!={expected}")

    run_id = str(release.get("runId") or "")
    if not run_id:
        return [*errors, "release_run_id_missing"]
    for summary in release.get("stocks", []):
        if not isinstance(summary, dict):
            continue
        code = str(summary.get("code") or "")
        if not code:
            continue
        detail_path = data_dir / "releases" / run_id / "stocks" / f"{code}.json"
        try:
            detail = load(detail_path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append(f"detail_missing:{code}")
            continue
        if str(detail.get("asOf") or "") != expected:
            errors.append(f"price_date:{code}:{detail.get('asOf')}!={expected}")
        regression = detail.get("regression")
        if not isinstance(regression, dict):
            errors.append(f"regression_missing:{code}")
        else:
            if str(regression.get("historyEnd") or "") != expected:
                errors.append(f"regression_date:{code}:{regression.get('historyEnd')}!={expected}")
            if regression.get("priceBasis") != "adjusted":
                errors.append(f"regression_not_adjusted:{code}")
        if str(detail.get("institutionDataAsOf") or "") != expected:
            errors.append(f"institution_date:{code}:{detail.get('institutionDataAsOf')}!={expected}")
        daily = detail.get("institutionalDaily")
        if (
            not isinstance(daily, list)
            or len(daily) != 10
            or any(not isinstance(row, dict) or row.get("status") != "pass" for row in daily)
        ):
            errors.append(f"institution_window_incomplete:{code}")
    return errors


def _warning_message(error: str) -> tuple[str, str | None, str | None, str | None]:
    """Return a stable code, optional stock code, observed date, and reader-facing note."""
    if error == "official_universe_stale":
        return error, None, None, "官方追蹤名單資料未更新"
    if error == "00631L_indicator_missing":
        return error, None, None, "00631L 市場指標尚未取得"
    if error.startswith("00631L_market_date:"):
        observed = error.split(":", 1)[1].split("!=", 1)[0] or None
        return "00631L_market_date", None, observed, f"00631L 市場指標截至 {observed or '未知日期'}"
    if error.startswith("official_market_date:"):
        observed = error.split(":", 1)[1].split("!=", 1)[0] or None
        return "official_market_date", None, observed, f"官方市場日程截至 {observed or '未知日期'}"
    if error.startswith("release_market_date:"):
        observed = error.split(":", 1)[1].split("!=", 1)[0] or None
        return "release_market_date", None, observed, f"發布資料日為 {observed or '未知日期'}"
    match = re.match(r"^([a-zA-Z0-9_]+):([A-Z0-9]{4,6})(?::(.*))?$", error)
    if match:
        code, stock_code, detail = match.groups()
        detail = detail or ""
        if code == "price_date":
            observed = detail.split("!=", 1)[0] or None
            return code, stock_code, observed, f"股價資料截至 {observed or '未知日期'}"
        if code == "regression_date":
            observed = detail.split("!=", 1)[0] or None
            return code, stock_code, observed, f"回歸價格資料截至 {observed or '未知日期'}"
        if code == "institution_date":
            observed = detail.split("!=", 1)[0] or None
            return code, stock_code, observed, f"法人資料截至 {observed or '未知日期'}"
        if code == "institution_window_incomplete":
            return code, stock_code, None, "投信十日資料不完整"
        if code == "detail_missing":
            return code, stock_code, None, "個股詳細資料尚未取得"
        if code == "regression_missing":
            return code, stock_code, None, "回歸資料尚未取得"
        if code == "regression_not_adjusted":
            return code, stock_code, None, "回歸使用的價格尚未確認為還原價"
    return error.split(":", 1)[0], None, None, error


def annotate_publish_advisory(data_dir: Path, config_path: Path, requested_market_date: str | None = None) -> list[str]:
    """Persist data gaps as visible degraded-release metadata instead of blocking publication."""
    latest_path = data_dir / "latest.json"
    release = load(latest_path)
    if requested_market_date:
        try:
            if date.fromisoformat(requested_market_date).isoformat() != requested_market_date:
                raise ValueError("exact ISO date required")
        except ValueError as exc:
            raise ValueError("requested_market_date_invalid") from exc
    errors = freshness_errors(data_dir, config_path, requested_market_date)
    expected = requested_market_date or latest_market_date(load(config_path)) or str(release.get("marketDate") or "")
    warnings: list[dict[str, Any]] = []
    by_stock: dict[str, list[str]] = {}
    stock_messages: dict[str, list[str]] = {}
    for error in errors:
        code, stock_code, observed, message = _warning_message(error)
        if stock_code and observed and observed != expected:
            message = f"{message}（目標 {expected}）"
        warnings.append({"code": code, "stockCode": stock_code, "observedDate": observed, "expectedDate": expected, "message": message})
        if stock_code:
            by_stock.setdefault(stock_code, []).append(error)
            stock_messages.setdefault(stock_code, []).append(message)

    quality = {
        "status": "degraded" if warnings else "current",
        "expectedMarketDate": expected,
        "warningCount": len(warnings),
        "affectedStockCount": len(by_stock),
        "warnings": warnings,
    }
    release["dataQuality"] = quality
    if warnings:
        release["freshness"] = "degraded"
        affected = sorted(by_stock)
        summary = f"資料已照常發布；{len(affected)} 檔個股有資料提醒（{', '.join(affected[:8])}{'…' if len(affected) > 8 else ''}），請看個股標示。"
        if affected:
            sample_warnings = stock_messages[affected[0]]
            summary = f"資料已照常發布；{len(affected)} 檔個股有資料提醒（{', '.join(affected[:8])}{'…' if len(affected) > 8 else ''}），例如 {affected[0]}：{'；'.join(sample_warnings[:2])}。請看個股標示。"
        if not affected:
            details = '；'.join(str(warning['message']) for warning in warnings[:3])
            summary = f"資料已照常發布；有 {len(warnings)} 項資料提醒：{details}。"
        base_message = str(release.get("statusMessage") or "").split("資料提醒：", 1)[0].rstrip()
        release["statusMessage"] = f"{base_message} 資料提醒：{summary}".strip()

    for stock in release.get("stocks", []):
        if not isinstance(stock, dict):
            continue
        stock_code = str(stock.get("code") or "")
        if stock_code not in by_stock:
            continue
        stock["dataFreshness"] = "stale"
        stock["freshnessWarnings"] = stock_messages[stock_code]
    for rows in (release.get("rankings") or {}).values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            stock_code = str(row.get("code") or "")
            if stock_code not in by_stock:
                continue
            row["dataFreshness"] = "stale"
            row["freshnessWarnings"] = stock_messages[stock_code]
    for stock_code, messages in stock_messages.items():
        detail_path = data_dir / "releases" / str(release.get("runId") or "") / "stocks" / f"{stock_code}.json"
        if not detail_path.exists():
            continue
        detail = load(detail_path)
        detail["dataFreshness"] = "stale"
        detail["freshnessWarnings"] = messages
        save(detail_path, detail)
    save(latest_path, release)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--market-date")
    parser.add_argument("--universe-only", action="store_true")
    parser.add_argument("--publish-advisory", action="store_true", help="publish data freshness gaps as warnings instead of failing the release")
    args = parser.parse_args()
    try:
        if args.universe_only:
            expected = latest_market_date(load(Path(args.config)))
            if not args.market_date or date.fromisoformat(args.market_date).isoformat() != args.market_date:
                raise ValueError('exact requested market date required')
            errors = [] if expected == args.market_date else [f'official_market_date:{expected}!={args.market_date}']
            if (load(Path(args.config)).get('universe') or {}).get('stale'):
                errors.append('official_universe_stale')
        elif args.publish_advisory:
            errors = annotate_publish_advisory(Path(args.data_dir), Path(args.config), args.market_date)
        else:
            errors = freshness_errors(Path(args.data_dir), Path(args.config), args.market_date)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"daily_freshness_failed={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if errors and not args.publish_advisory:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, sort_keys=True))
        return 1
    if args.publish_advisory:
        print(json.dumps({"valid": True, "freshness": "degraded" if errors else "current", "warnings": errors}, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps({"valid": True}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
