#!/usr/bin/env python3
"""
Abnormal Volume Strategy Backtest — Main Orchestrator + CLI

Wires together all modules:
  data_loader → indicators → pattern detection (1/2/3) → performance tracking → report

Usage:
    python3 backtest_main.py                          # full backtest
    python3 backtest_main.py --type 1                 # only Type 1
    python3 backtest_main.py --start 2023-01-01       # custom date range
    python3 backtest_main.py --output results.json    # save JSON output
"""

import sys
import os
import json
import time
import argparse
import csv
from datetime import datetime
from collections import defaultdict

# Ensure current dir is in path so sibling modules can be imported
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backtest_types import StockData, Signal, PerformanceStats
from data_loader import load_stocks
from indicators import compute_indicators
from pattern_type1 import detect_type1
from pattern_type2 import detect_type2
from pattern_type3 import detect_type3
from performance import PerformanceTracker

DATA_DIR = os.path.join(BASE_DIR, 'data')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
OHLC_DIR = os.path.join(BASE_DIR, 'data', 'ohlc_cache')

TYPE_NAMES = {
    1: 'Type 1: 底部沉寂後爆量',
    2: 'Type 2: 連續溫和放量',
    3: 'Type 3: 突破爆量',
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Abnormal Volume Strategy Backtest',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  python3 backtest_main.py\n'
            '  python3 backtest_main.py --type 1\n'
            '  python3 backtest_main.py --start 2023-01-01 --end 2025-12-31\n'
            '  python3 backtest_main.py --output results.json\n'
        ),
    )
    parser.add_argument(
        '--type', type=int, choices=[1, 2, 3], default=None,
        help='Only run specific pattern type (1/2/3); default: all three',
    )
    parser.add_argument(
        '--start', type=str, default='2024-06-01',
        help='Start date (YYYY-MM-DD); default: 2024-06-01',
    )
    parser.add_argument(
        '--end', type=str, default='2026-05-22',
        help='End date (YYYY-MM-DD); default: 2026-05-22',
    )
    parser.add_argument(
        '--output', type=str, default=None,
        help='Write full JSON output to this file (relative to project root)',
    )
    parser.add_argument(
        '--ohlc-dir', type=str, default=OHLC_DIR,
        help=f'OHLC cache directory for Type 3; default: {OHLC_DIR}',
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    start_wall = time.time()

    # ── Setup FinMind availability for Type 3 ──
    _try_setup_finmind()

    # ── Phase 1: Load stocks ──
    print(f"Loading stocks from {DATA_DIR} ...")
    stocks = load_stocks(DATA_DIR, args.start, args.end)
    print(f"  ✅ {len(stocks)} stocks loaded (filtered {args.start} ~ {args.end})")

    if not stocks:
        print("  ⚠️  No stocks passed the date filter. Nothing to backtest.")
        return

    n_total = len(stocks)
    type_filter = [args.type] if args.type else [1, 2, 3]

    # ── Phase 2: Process each stock ──
    tracker = PerformanceTracker()

    for i, (symbol, stock) in enumerate(stocks.items()):
        if (i + 1) % 100 == 0:
            elapsed = time.time() - start_wall
            print(f"  Processing {i+1}/{n_total}... ({elapsed:.0f}s elapsed)", flush=True)

        # Compute indicators
        try:
            ind = compute_indicators(stock)
        except Exception as exc:
            print(f"  ⚠️  Indicators failed for {symbol}: {exc}", file=sys.stderr)
            continue

        # Detect signals
        sigs = []

        if 1 in type_filter:
            try:
                sigs.extend(detect_type1(stock, ind))
            except Exception as exc:
                print(f"  ⚠️  Type 1 failed for {symbol}: {exc}", file=sys.stderr)

        if 2 in type_filter:
            try:
                sigs.extend(detect_type2(stock, ind))
            except Exception as exc:
                print(f"  ⚠️  Type 2 failed for {symbol}: {exc}", file=sys.stderr)

        if 3 in type_filter:
            try:
                sigs.extend(
                    detect_type3(stock, ind, ohlc_cache_dir=args.ohlc_dir)
                )
            except Exception as exc:
                print(f"  ⚠️  Type 3 failed for {symbol}: {exc}", file=sys.stderr)

        for s in sigs:
            tracker.record_signal(s)

    # ── Phase 3: Forward returns & statistics ──
    print("Computing forward returns ...")
    try:
        tracker.compute_forward_returns(stocks)
    except Exception as exc:
        print(f"  ⚠️  Forward-return computation failed: {exc}", file=sys.stderr)

    print("Computing statistics ...")
    stats = {}
    try:
        stats = tracker.compute_stats()
    except Exception as exc:
        print(f"  ⚠️  Statistics computation failed: {exc}", file=sys.stderr)

    # ── Phase 4: Print formatted report ──
    elapsed = time.time() - start_wall
    report = _format_report(stats, args.start, args.end, n_total, tracker.signals, elapsed)
    print()
    print(report)

    # ── Phase 5: Save detailed output ──
    _save_output(
        report, tracker.signals, stats, stocks,
        args.start, args.end, n_total, elapsed, args,
    )

    print(f"Total runtime: {elapsed:.1f}s")


# ─────────────────────────────────────────────
#  Report formatting
# ─────────────────────────────────────────────

def _format_report(stats, start_date, end_date, n_stocks, signals, elapsed):
    lines = []

    # ── header box ──
    lines.append('╔' + '═' * 60 + '╗')
    lines.append(f'║{"Abnormal Volume Strategy Backtest Results":^60}║')
    lines.append(f'║{"":^60}║')
    lines.append(f'║{f"{start_date} ~ {end_date} | {n_stocks} stocks":^60}║')
    lines.append('╚' + '═' * 60 + '╝')
    lines.append('')

    # ── per-type sections ──
    for pt in (1, 2, 3):
        s = stats.get(pt)
        lines.append(TYPE_NAMES.get(pt, f'Type {pt}'))
        if s is None or s.total_signals == 0:
            lines.append('  Signals: 0')
            lines.append('')
            continue

        lines.append(f'  Signals: {s.total_signals}')
        lines.append(
            f'  5d  Win: {s.win_rate_5d * 100:.1f}%  '
            f'Avg: {s.avg_return_5d:+.1f}%  '
            f'Best: {s.best_return_20d:+.1f}%  '
            f'Worst: {s.worst_return_20d:+.1f}%'
        )
        lines.append(
            f'  10d Win: {s.win_rate_10d * 100:.1f}%  '
            f'Avg: {s.avg_return_10d:+.1f}%'
        )
        lines.append(
            f'  20d Win: {s.win_rate_20d * 100:.1f}%  '
            f'Avg: {s.avg_return_20d:+.1f}%  '
            f'Best: {s.best_return_20d:+.1f}%  '
            f'Worst: {s.worst_return_20d:+.1f}%'
        )
        lines.append(
            f'  60d Win: {s.win_rate_60d * 100:.1f}%  '
            f'Avg: {s.avg_return_60d:+.1f}%'
        )
        lines.append(
            f'  Max Drawdown: {s.max_drawdown:.1%}  '
            f'Sharpe: {s.sharpe_ratio:.2f}'
        )
        lines.append('')

    # ── Combined ──
    s0 = stats.get(0)
    if s0 is not None and s0.total_signals > 0:
        lines.append('Combined (All Types)')
        lines.append(f'  Total Signals: {s0.total_signals}')
        lines.append(
            f'  5d  Win: {s0.win_rate_5d * 100:.1f}%  '
            f'Avg: {s0.avg_return_5d:+.1f}%'
        )
        lines.append(
            f'  10d Win: {s0.win_rate_10d * 100:.1f}%  '
            f'Avg: {s0.avg_return_10d:+.1f}%'
        )
        lines.append(
            f'  20d Win: {s0.win_rate_20d * 100:.1f}%  '
            f'Avg: {s0.avg_return_20d:+.1f}%  '
            f'Best: {s0.best_return_20d:+.1f}%  '
            f'Worst: {s0.worst_return_20d:+.1f}%'
        )
        lines.append(
            f'  60d Win: {s0.win_rate_60d * 100:.1f}%  '
            f'Avg: {s0.avg_return_60d:+.1f}%'
        )
        lines.append(
            f'  Max Drawdown: {s0.max_drawdown:.1%}  '
            f'Sharpe: {s0.sharpe_ratio:.2f}'
        )
        lines.append('')

    # ── summary footer ──
    total_sigs = s0.total_signals if s0 else sum(
        s.total_signals for s in stats.values()
        if s is not None and s.pattern_type != 0
    )
    lines.append(f'Runtime: {elapsed:.1f}s')
    lines.append(f'Total Signals: {total_sigs}')

    return '\n'.join(lines)


# ─────────────────────────────────────────────
#  Output file writing
# ─────────────────────────────────────────────

def _save_output(report, signals, stats, stocks, start_date, end_date,
                 n_stocks, elapsed, args):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_dir = os.path.join(OUTPUT_DIR, f'backtest_{timestamp}')
    os.makedirs(out_dir, exist_ok=True)

    # 1. summary.txt — same as console output
    with open(os.path.join(out_dir, 'summary.txt'), 'w', encoding='utf-8') as f:
        f.write(report)

    # 2. signals.json — list of all signals
    signals_json = [_signal_to_dict(s) for s in signals]
    with open(os.path.join(out_dir, 'signals.json'), 'w') as f:
        json.dump(signals_json, f, ensure_ascii=False, indent=2)

    # 3. stats.json — all PerformanceStats as dict
    stats_json = {}
    for pt, s in stats.items():
        stats_json[str(pt)] = _stats_to_dict(s)
    with open(os.path.join(out_dir, 'stats.json'), 'w') as f:
        json.dump(stats_json, f, ensure_ascii=False, indent=2)

    # 4. by_stock.csv — per-stock signal count & avg 20d return
    _write_by_stock_csv(out_dir, signals, stocks)

    print(f"Results saved to {out_dir}/")

    # 5. Optional single-JSON output (--output flag)
    if args.output:
        out_data = {
            'meta': {
                'start_date': start_date,
                'end_date': end_date,
                'total_stocks': n_stocks,
                'total_signals': len(signals),
                'runtime_seconds': round(elapsed, 1),
                'type_filter': args.type,
            },
            'stats': stats_json,
            'signals': signals_json,
        }
        out_path = args.output if os.path.isabs(args.output) else \
            os.path.join(BASE_DIR, args.output)
        with open(out_path, 'w') as f:
            json.dump(out_data, f, ensure_ascii=False, indent=2)
        print(f"JSON output saved to {out_path}")


def _signal_to_dict(sig):
    return {
        'symbol': sig.symbol,
        'name': sig.name,
        'signal_date': sig.signal_date,
        'pattern_type': sig.pattern_type,
        'entry_price': sig.entry_price,
        'volume_ratio': sig.volume_ratio,
        'metadata': dict(sig.metadata) if sig.metadata else {},
    }


def _stats_to_dict(s):
    if s is None:
        return {}
    return {
        'pattern_type': s.pattern_type,
        'total_signals': s.total_signals,
        'win_rate_5d': s.win_rate_5d,
        'win_rate_10d': s.win_rate_10d,
        'win_rate_20d': s.win_rate_20d,
        'win_rate_60d': s.win_rate_60d,
        'avg_return_5d': s.avg_return_5d,
        'avg_return_10d': s.avg_return_10d,
        'avg_return_20d': s.avg_return_20d,
        'avg_return_60d': s.avg_return_60d,
        'max_drawdown': s.max_drawdown,
        'sharpe_ratio': s.sharpe_ratio,
        'avg_holding_days': s.avg_holding_days,
        'return_std_20d': s.return_std_20d,
        'best_return_20d': s.best_return_20d,
        'worst_return_20d': s.worst_return_20d,
    }


def _write_by_stock_csv(out_dir, signals, stocks):
    """Aggregate signals by stock and write CSV."""
    stock_info = defaultdict(lambda: {'count': 0, 'returns_20d': []})

    for sig in signals:
        info = stock_info[sig.symbol]
        info['count'] += 1
        stock = stocks.get(sig.symbol)
        if stock is None:
            continue
        idx = stock.date_index(sig.signal_date)
        if idx >= 0 and idx + 20 < len(stock.closes):
            ret_20d = (stock.closes[idx + 20] / stock.closes[idx] - 1) * 100
            info['returns_20d'].append(ret_20d)

    path = os.path.join(out_dir, 'by_stock.csv')
    with open(path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['symbol', 'name', 'market', 'signal_count', 'avg_return_20d'])
        for symbol in sorted(stock_info):
            info = stock_info[symbol]
            stock = stocks.get(symbol)
            name = stock.name if stock else ''
            market = stock.market if stock else ''
            avg_ret = (
                sum(info['returns_20d']) / len(info['returns_20d'])
                if info['returns_20d'] else 0.0
            )
            w.writerow([symbol, name, market, info['count'], round(avg_ret, 2)])


# ─────────────────────────────────────────────
#  FinMind bootstrap (for Type 3 OHLC)
# ─────────────────────────────────────────────

def _try_setup_finmind():
    """Attempt to load FinMind credentials so Type 3 can fetch OHLC if needed.
    Non-fatal — Type 3 falls back to approximation mode if this fails."""
    try:
        token_path = os.path.join(BASE_DIR, 'scripts', 'download_otc_prices.py')
        if not os.path.exists(token_path):
            return
        import re
        with open(token_path) as f:
            content = f.read()
        for match in re.finditer(
            r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+', content
        ):
            token = match.group()
            try:
                from FinMind.data import DataLoader
                api = DataLoader()
                api.login_by_token(api_token=token)
                # Set a module-level flag that pattern_type3 can check
                import backtest_types as bt
                bt._FINMIND_API = api
                bt._FINMIND_TOKEN = token
            except Exception:
                pass
            break
    except Exception:
        pass


if __name__ == '__main__':
    main()
