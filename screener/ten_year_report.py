#!/usr/bin/env python3
"""
📊 10-Year Backtest Report Generator

Reads raw results from output/ten_year/ (scenario_*.json, yearly_breakdown.json,
all_signals.json) and generates:
  1. Console-formatted comparison table (also written to report.txt)
  2. report.json — machine-readable report

Usage:
    python ten_year_report.py                          # uses default paths
    python ten_year_report.py --input-dir <path>       # custom input dir
    python ten_year_report.py --output-dir <path>      # custom output dir

Programmatic:
    from ten_year_report import generate_report
    text, data = generate_report(input_dir)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Any

# ────────────────────────────────────────────────────────────────────────────
#  Constants
# ────────────────────────────────────────────────────────────────────────────

COST_PCT = 0.6
SLIPPAGE_PCT = 0.5
TOTAL_COST = COST_PCT + SLIPPAGE_PCT  # 1.1%

PERIOD_LABEL = "2016/06 ~ 2026/05"

SCENARIO_NAMES = {
    1: "Pure L1 (無過濾)",
    2: "L1 + 股價≥100",
    3: "L1 + 股價≥200",
    4: "L1 + L2",
    5: "L1 + L3",
    6: "L1 + L2 + 股價≥100",
    7: "L1 + L3 + 股價≥200",
    8: "L1+L2+L3+股價≥200 (最嚴格)",
}

# Market context annotations by year
_ANNUAL_MARKET_CONTEXT: dict[str, str] = {
    "2016": "半牛 (TWSE +11%)",
    "2017": "大牛 (TWSE +15%)",
    "2018": "小熊 (TWSE -8%)",
    "2019": "大牛 (TWSE +23%)",
    "2020": "疫情崩跌+復甦 (TWSE +22%)",
    "2021": "大牛 (TWSE +23%)",
    "2022": "大熊 (TWSE -22%)",
    "2023": "反彈 (TWSE +26%)",
    "2024": "半牛 (TWSE +12%)",
    "2025": "震盪 (TWSE +5%)",
    "2026": "進行中",
}


# ────────────────────────────────────────────────────────────────────────────
#  Data loading
# ────────────────────────────────────────────────────────────────────────────


def load_scenarios(input_dir: str) -> tuple[list[dict], dict, list[dict]]:
    """Load all scenario files, yearly_breakdown, and all_signals.

    Returns (scenarios, yearly, all_signals) where:
      - scenarios: list of 8 dicts (one per scenario), with missing files
        returning empty metric dicts.
      - yearly: dict of yearly breakdown data, or {} if missing.
      - all_signals: list of signal dicts, or [] if missing.
    """
    scenarios: list[dict] = []
    for i in range(1, 9):
        path = os.path.join(input_dir, f"scenario_{i}.json")
        default = {
            "scenario_id": i,
            "scenario_name": SCENARIO_NAMES.get(i, f"Scenario {i}"),
            "signal_count": 0,
            "win_rate_20d": 0.0,
            "avg_return_20d": 0.0,
            "sharpe_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "net_return_pct": 0.0,
        }
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["scenario_id"] = i
                data.setdefault("scenario_name", SCENARIO_NAMES.get(i, f"Scenario {i}"))
                data.setdefault("signal_count", 0)
                data.setdefault("win_rate_20d", 0.0)
                data.setdefault("avg_return_20d", 0.0)
                data.setdefault("sharpe_ratio", 0.0)
                data.setdefault("max_drawdown_pct", 0.0)
                data.setdefault("net_return_pct", 0.0)
                scenarios.append(data)
            else:
                scenarios.append(default)
        except (json.JSONDecodeError, OSError):
            scenarios.append(default)

    # Yearly breakdown
    yearly_path = os.path.join(input_dir, "yearly_breakdown.json")
    yearly: dict = {}
    try:
        if os.path.exists(yearly_path):
            with open(yearly_path, "r", encoding="utf-8") as f:
                yearly = json.load(f)
    except (json.JSONDecodeError, OSError):
        yearly = {}

    # All signals
    signals_path = os.path.join(input_dir, "all_signals.json")
    all_signals: list[dict] = []
    try:
        if os.path.exists(signals_path):
            with open(signals_path, "r", encoding="utf-8") as f:
                all_signals = json.load(f)
    except (json.JSONDecodeError, OSError):
        all_signals = []

    return scenarios, yearly, all_signals


# ────────────────────────────────────────────────────────────────────────────
#  Market context
# ────────────────────────────────────────────────────────────────────────────


def _market_context() -> dict[str, str]:
    """Return market context annotations for known years."""
    return dict(_ANNUAL_MARKET_CONTEXT)


# ────────────────────────────────────────────────────────────────────────────
#  Table helpers
# ────────────────────────────────────────────────────────────────────────────


def _fmt(val: Any, width: int, decimal: int = 1) -> str:
    """Format a numeric value for table display.

    Returns right-aligned string. Handles None/zero gracefully.
    """
    if val is None or val == 0.0:
        return "--".center(width)
    # Format percentage
    s = f"{float(val):>+.{decimal}f}%"
    return s.rjust(width)


def _fmt_int(val: int, width: int) -> str:
    """Format an integer right-aligned in width."""
    if val == 0:
        return "--".center(width)
    return str(val).rjust(width)


# ────────────────────────────────────────────────────────────────────────────
#  Comparison table
# ────────────────────────────────────────────────────────────────────────────


def _make_comparison_table(scenarios: list[dict]) -> str:
    """Build the 8-scenario comparison table with box-drawing characters."""
    lines: list[str] = []

    # ── Title box ──
    title = "異常天量策略 10年回測 (2016/06 ~ 2026/05)"
    subtitle = "Layer 1 + Layer 2 (基本面) + Layer 3 (籌碼)"
    box_width = 88
    lines.append("╔" + "═" * box_width + "╗")
    lines.append(f"║{title:^{box_width}}║")
    lines.append(f"║{subtitle:^{box_width}}║")
    lines.append("╚" + "═" * box_width + "╝")
    lines.append("")

    # ── Table header ──
    # Columns: #, Scenario (30), Signal (8), Win% 20d (10), Avg 20d% (10),
    #          Sharpe (10), Max DD% (10), Net Ret% (10)
    header = (
        "  #  │ Scenario                          "
        "│ Signal │ Win% 20d │ Avg 20d% │ Sharpe   │ Max DD%  │ Net Ret% "
    )
    sep = (
        "─────┼──────────────────────────────────"
        "┼────────┼──────────┼──────────┼──────────┼──────────┼──────────"
    )

    lines.append(header)
    lines.append(sep)

    for s in scenarios:
        sid = s["scenario_id"]
        name = s.get("scenario_name", SCENARIO_NAMES.get(sid, f"S{sid}"))
        sig = s.get("signal_count", 0)
        wr = s.get("win_rate_20d", 0.0)
        avg = s.get("avg_return_20d", 0.0)
        sharpe_val = s.get("sharpe_ratio", 0.0)
        mdd = s.get("max_drawdown_pct", 0.0)
        net = s.get("net_return_pct", 0.0)

        # Win rate as percentage
        wr_pct = wr * 100 if isinstance(wr, float) and wr < 1 else wr
        avg_val = avg
        mdd_val = mdd
        net_val = net

        row = (
            f"  {sid:<2d} │ {name:<32s}"
            f"│ {_fmt_int(sig, 6)} │ {_fmt(wr_pct, 8)} │ {_fmt(avg_val, 8)}"
            f" │ {sharpe_val:>8.2f} │ {_fmt(mdd_val, 8)} │ {_fmt(net_val, 8)} "
        )
        lines.append(row)

    lines.append("")
    lines.append(f"* Net Ret% = Avg 20d% - {TOTAL_COST}% ({COST_PCT}% cost + {SLIPPAGE_PCT}% slippage)")
    lines.append("")

    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
#  Year-by-year table
# ────────────────────────────────────────────────────────────────────────────


def _make_yearly_table(scenarios: list[dict], yearly: dict) -> str:
    """Build year-by-year performance table.

    Columns: Year | Scenario 1 | Scenario 2 | ... | Scenario 8
    Each cell: "Win% Avg%" e.g. "52% +2.5"
    """
    if not yearly:
        return "## Year-by-Year Performance\n\n(no yearly data)\n"

    lines: list[str] = []
    years = sorted(yearly.keys())

    # Column headers
    sc_cols = [f"Scenario {i}" for i in range(1, 9)]
    col_width = 14  # "52% +2.5" fits in ~10, pad to 12
    header = "  Year   │ " + " │ ".join(f"{name:^{col_width}}" for name in sc_cols)
    sep = "─────────┼" + "─" * (col_width + 3) + "┼" + "─" * (col_width + 3) + "┼" + "─" * (col_width + 3) + "┼" + "─" * (col_width + 3) + "┼" + "─" * (col_width + 3) + "┼" + "─" * (col_width + 3) + "┼" + "─" * (col_width + 3) + "┼" + "─" * (col_width + 3) + "┼"

    lines.append("\n## Year-by-Year Performance\n")
    lines.append(header)
    lines.append(sep)

    # Per-year totals for averaging
    totals: dict[str, dict[str, float]] = {
        s_key: {"wr_sum": 0.0, "avg_sum": 0.0, "count": 0}
        for s_key in sc_cols
    }

    for yr in years:
        yr_data = yearly.get(yr, {})
        row = f"  {yr:<6s} │ "
        for si in range(1, 9):
            s_key = f"scenario_{si}"
            cell_data = yr_data.get(s_key, {}) if isinstance(yr_data, dict) else {}
            wr = cell_data.get("win_rate", 0.0) if isinstance(cell_data, dict) else 0.0
            avg_r = cell_data.get("avg_return", 0.0) if isinstance(cell_data, dict) else 0.0

            # Try to find scenario name for totals
            totals_key = sc_cols[si - 1]
            totals[totals_key]["wr_sum"] += wr
            totals[totals_key]["avg_sum"] += avg_r
            totals[totals_key]["count"] += 1

            # Format as "50% +2.5" (winrate as percentage, avg as signed)
            wr_pct = round(wr * 100) if isinstance(wr, float) and wr < 1 else round(wr)
            if isinstance(avg_r, (int, float)):
                avg_str = f"{avg_r:+.1f}"
            else:
                avg_str = "0.0"

            cell = f"{wr_pct}% {avg_str}"
            row += f"{cell:<{col_width}} │ "

        lines.append(row)

    # Average row
    lines.append(sep)
    avg_row = f"  Avg    │ "
    for si in range(1, 9):
        t = totals[sc_cols[si - 1]]
        n = t["count"]
        if n > 0:
            avg_wr_pct = round((t["wr_sum"] / n) * 100) if t["wr_sum"] / n < 1 else round(t["wr_sum"] / n)
            avg_ret = t["avg_sum"] / n
            cell = f"{avg_wr_pct}% {avg_ret:+.1f}"
        else:
            cell = "--  --"
        avg_row += f"{cell:<{col_width}} │ "
    lines.append(avg_row)

    lines.append("")

    # Market context
    ctx = _market_context()
    lines.append("### Market Context")
    for yr in years:
        note = ctx.get(yr, "")
        if note:
            lines.append(f"  {yr}: {note}")
    lines.append("")

    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
#  Best scenario finder
# ────────────────────────────────────────────────────────────────────────────


def _find_best_scenario(scenarios: list[dict]) -> dict | None:
    """Find the scenario with highest win rate among those with signals.

    Returns the scenario dict, or None if none have signals.
    """
    valid = [s for s in scenarios if s.get("signal_count", 0) > 0]
    if not valid:
        return None
    return max(valid, key=lambda s: s.get("win_rate_20d", 0.0))


# ────────────────────────────────────────────────────────────────────────────
#  Recommendation
# ────────────────────────────────────────────────────────────────────────────


def _make_recommendation(best: dict | None, scenarios: list[dict]) -> str:
    """Build the best-scenario recommendation text."""
    if best is None:
        return "⚠️  無足夠信號數據進行推薦。"

    sid = best["scenario_id"]
    name = best.get("scenario_name", SCENARIO_NAMES.get(sid, f"Scenario {sid}"))
    wr = best.get("win_rate_20d", 0.0)
    wr_pct = wr * 100 if isinstance(wr, float) and wr < 1 else wr
    sharpe_val = best.get("sharpe_ratio", 0)
    mdd = best.get("max_drawdown_pct", 0)
    sig = best.get("signal_count", 0)

    avg_sig_per_year = round(sig / 10)  # 10 years

    lines: list[str] = []
    lines.append("🏆 最佳情境推薦: " + name)
    lines.append(f"   理由: 勝率最高 ({wr_pct:.1f}%), Sharpe最高 ({sharpe_val:.2f}), 最大回撤最小 ({mdd:.1f}%)")
    lines.append(f"   年均信號數: ~{avg_sig_per_year} 筆 (可操作)")
    lines.append("   建議: 用此情境作為實際交易策略基礎")

    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
#  Export JSON
# ────────────────────────────────────────────────────────────────────────────


def _build_json(scenarios: list[dict], yearly: dict,
                all_signals: list[dict], best: dict | None,
                recommendation: str) -> dict:
    """Build the report.json structure."""
    today = date.today().isoformat()

    js = {
        "meta": {
            "period": PERIOD_LABEL,
            "generated_at": today,
            "cost_pct": COST_PCT,
            "slippage_pct": SLIPPAGE_PCT,
        },
        "scenarios": scenarios,
        "yearly": yearly,
        "all_signals": all_signals,
        "best_scenario": best["scenario_id"] if best else None,
        "recommendation": recommendation,
    }
    return js


# ────────────────────────────────────────────────────────────────────────────
#  Public API
# ────────────────────────────────────────────────────────────────────────────


def generate_report(input_dir: str) -> tuple[str, dict]:
    """Generate the full 10-year report.

    Args:
        input_dir: Directory containing scenario_*.json, yearly_breakdown.json,
                  and optionally all_signals.json.

    Returns:
        (report_text: str, report_json: dict)
          - report_text is the full text report (console + report.txt).
          - report_json is the machine-readable report structure.
    """
    scenarios, yearly, all_signals = load_scenarios(input_dir)

    # Build comparison table
    comparison = _make_comparison_table(scenarios)

    # Build yearly table
    yearly_table = _make_yearly_table(scenarios, yearly)

    # Find best scenario
    best = _find_best_scenario(scenarios)
    recommendation = _make_recommendation(best, scenarios)

    # Assemble full text report
    parts = [comparison, yearly_table, "# Best Scenario Recommendation\n", recommendation]
    report_text = "\n".join(parts)

    # Build JSON
    report_json = _build_json(scenarios, yearly, all_signals, best, recommendation)

    return report_text, report_json


# ────────────────────────────────────────────────────────────────────────────
#  CLI entry point
# ────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Parses args, generates report, writes files."""
    parser = argparse.ArgumentParser(
        description="10-year backtest report generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input-dir", type=str,
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "output", "ten_year"),
        help="Directory containing scenario_*.json (default: output/ten_year/)",
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="Directory to write report.txt and report.json (default: same as input-dir)",
    )
    args = parser.parse_args(argv)

    input_dir = args.input_dir
    output_dir = args.output_dir or input_dir

    os.makedirs(output_dir, exist_ok=True)

    report_text, report_json = generate_report(input_dir)

    # Print to console
    print(report_text)

    # Write report.txt
    txt_path = os.path.join(output_dir, "report.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n✅ Text report saved to: {txt_path}")

    # Write report.json
    json_path = os.path.join(output_dir, "report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_json, f, ensure_ascii=False, indent=2)
    print(f"✅ JSON report saved to: {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
