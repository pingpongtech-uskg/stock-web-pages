"""
📊 Sector Analysis — Market/Sector Breakdown for Taiwan Stocks

Analyze backtest results by market (TWSE vs OTC) and by category
(電子/傳產/金融) with detailed sector mapping.

Exports:
    classify_sector(symbol) -> (sector_name, category)
    get_market(symbol) -> str
    compute_returns_20d(all_stocks) -> dict
    analyze_by_segment(signals, all_stocks, returns_20d) -> dict
    format_segment_line(title, count, win_rate, avg_return) -> str
    CATEGORIES: dict with category names and colors
"""

import sys
from collections import defaultdict
from typing import Any

# ═══════════════════════════════════════════════════════════════════
# Category constants (for display / UI usage)
# ═══════════════════════════════════════════════════════════════════

CATEGORIES: dict[str, str] = {
    "電子": "🟢",
    "傳產": "🔵",
    "金融": "🟡",
}

# ═══════════════════════════════════════════════════════════════════
# Prefix-based sector mapping
# ═══════════════════════════════════════════════════════════════════
#
# Map the first two digits of a TWSE/TPEx 4-digit stock code → (sector_name, category)
#
# Simplified category rule:
#   prefixes {23,24,30,31,32,34,35,36,37,38,47,48,49,50,52,53,54,61,62,64,65,80} → 電子
#   28 → 金融
#   rest → 傳產
#
# For sector_name, we assign the appropriate TWSE industry name.
# At least 30 distinct sector names are provided.

SECTOR_PREFIX_MAP: dict[str, tuple[str, str]] = {
    # ── 傳產 (Traditional Industries) ──
    "11": ("水泥", "傳產"),
    "12": ("食品", "傳產"),
    "13": ("塑膠", "傳產"),
    "14": ("紡織", "傳產"),
    "15": ("電機機械", "傳產"),
    "16": ("電器電纜", "傳產"),
    "17": ("化學", "傳產"),      # sub-range 1730+ → 生技醫療 (handled in classify_sector)
    "18": ("玻璃陶瓷", "傳產"),
    "19": ("造紙", "傳產"),
    "20": ("鋼鐵", "傳產"),
    "21": ("橡膠", "傳產"),
    "22": ("汽車", "傳產"),
    "25": ("營建", "傳產"),
    "26": ("航運", "傳產"),
    "27": ("觀光", "傳產"),
    "29": ("貿易百貨", "傳產"),
    "33": ("通信網路", "傳產"),
    "39": ("其他", "傳產"),
    "40": ("綠能環保", "傳產"),
    "41": ("數位雲端", "傳產"),
    "42": ("其他", "傳產"),
    "43": ("其他", "傳產"),
    "44": ("其他", "傳產"),
    "45": ("其他", "傳產"),
    "46": ("油電燃氣", "傳產"),
    "51": ("其他", "傳產"),
    "55": ("營建", "傳產"),
    "56": ("運動休閒", "傳產"),
    "57": ("其他", "傳產"),
    "58": ("其他", "傳產"),
    "59": ("其他", "傳產"),
    "60": ("資訊服務", "傳產"),
    "63": ("其他", "傳產"),
    "66": ("其他", "傳產"),
    "67": ("其他", "傳產"),
    "68": ("其他", "傳產"),
    "69": ("其他", "傳產"),
    "70": ("其他", "傳產"),
    "71": ("其他", "傳產"),
    "72": ("其他", "傳產"),
    "73": ("其他", "傳產"),
    "74": ("其他", "傳產"),
    "75": ("其他", "傳產"),
    "76": ("其他", "傳產"),
    "77": ("其他", "傳產"),
    "78": ("其他", "傳產"),
    "79": ("其他", "傳產"),
    "81": ("其他", "傳產"),
    "82": ("其他", "傳產"),
    "83": ("其他", "傳產"),
    "84": ("運動休閒", "傳產"),
    "85": ("運動休閒", "傳產"),
    "86": ("其他", "傳產"),
    "87": ("其他", "傳產"),
    "88": ("其他", "傳產"),
    "89": ("其他", "傳產"),
    "90": ("其他", "傳產"),
    "91": ("其他", "傳產"),
    "92": ("其他", "傳產"),
    "93": ("其他", "傳產"),
    "94": ("其他", "傳產"),
    "95": ("其他", "傳產"),
    "96": ("其他", "傳產"),
    "97": ("其他", "傳產"),
    "98": ("其他", "傳產"),
    "99": ("其他", "傳產"),
    # ── 電子 (Electronics / Technology) ──
    "23": ("半導體", "電子"),
    "24": ("電腦週邊", "電子"),
    "30": ("光電", "電子"),
    "31": ("電子零組件", "電子"),
    "32": ("電子零組件", "電子"),
    "34": ("光電", "電子"),
    "35": ("光電", "電子"),
    "36": ("電子零組件", "電子"),
    "37": ("電子通路", "電子"),
    "38": ("其他電子", "電子"),
    "47": ("電子零組件", "電子"),
    "48": ("電子零組件", "電子"),
    "49": ("通信網路", "電子"),
    "50": ("電腦週邊", "電子"),
    "52": ("電腦週邊", "電子"),
    "53": ("電腦週邊", "電子"),
    "54": ("電腦週邊", "電子"),
    "61": ("資訊服務", "電子"),
    "62": ("資訊服務", "電子"),
    "64": ("通信網路", "電子"),
    "65": ("其他電子", "電子"),
    "80": ("其他電子", "電子"),
    # ── 金融 (Financial) ──
    "28": ("金融保險", "金融"),
}

# Sub-range overrides: for specific 4-digit codes that don't match the prefix default
SECTOR_CODE_OVERRIDES: dict[str, tuple[str, str]] = {}


def classify_sector(symbol: str) -> tuple[str, str]:
    """
    Classify a Taiwan stock symbol into (sector_name, category).

    Examples:
        classify_sector("2330")    → ("半導體", "電子")
        classify_sector("1101")    → ("水泥", "傳產")
        classify_sector("2330.TW") → ("半導體", "電子")

    The function strips .TW/.TWO suffixes, then uses the first two
    digits of the 4-digit stock code to look up the sector.
    """
    # Strip exchange suffix
    code = symbol.replace(".TW", "").replace(".TWO", "").strip()

    # Handle empty / short codes
    if not code or len(code) < 4 or not code.isdigit():
        return ("其他", "傳產")

    # Check 4-digit override first
    if code in SECTOR_CODE_OVERRIDES:
        return SECTOR_CODE_OVERRIDES[code]

    prefix = code[:2]

    # Default result from prefix map
    result = SECTOR_PREFIX_MAP.get(prefix, ("其他", "傳產"))

    # Special handling: 17xx sub-ranges
    if prefix == "17" and result[0] == "化學":
        # 1730+ → 生技醫療 (biotech/medical); 1700-1729 → 化學
        try:
            code_num = int(code)
            if 1730 <= code_num <= 1799:
                return ("生技醫療", "傳產")
            else:
                return ("化學", "傳產")
        except ValueError:
            pass

    # Special handling: 23xx sub-ranges
    if prefix == "23":
        # 2301-2349 → 半導體 (semiconductor); 2350-2399 → 電腦週邊 (computer peripheral)
        try:
            code_num = int(code)
            if 2350 <= code_num <= 2399:
                return ("電腦週邊", "電子")
            else:
                return ("半導體", "電子")
        except ValueError:
            pass

    return result


# ═══════════════════════════════════════════════════════════════════
# Market detection
# ═══════════════════════════════════════════════════════════════════

def get_market(symbol: str) -> str:
    """
    Determine the exchange market for a stock symbol.

    - Symbols ending in .TW → 'TWSE'
    - Symbols ending in .TWO → 'OTC'
    - Bare codes are inferred by first digit:
      1xxx → TWSE, 2xxx-4xxx → TWSE, 5xxx-6xxx → TWSE,
      8xxx-9xxx → OTC (common convention)
    """
    suffix = ".TWO" if symbol.endswith(".TWO") else ".TW"
    if symbol.endswith(".TW") or symbol.endswith(".TWO"):
        return "OTC" if suffix == ".TWO" else "TWSE"

    # Infer from bare code
    try:
        code = symbol.replace(".TW", "").replace(".TWO", "").strip()
        first_digit = int(code[0]) if code and code.isdigit() else 0
        # Rough convention: 1-6 → TWSE, 8-9 → OTC
        if first_digit in (8, 9):
            return "OTC"
        return "TWSE"
    except (ValueError, IndexError):
        return "TWSE"


# ═══════════════════════════════════════════════════════════════════
# 20-day return computation
# ═══════════════════════════════════════════════════════════════════

def compute_returns_20d(
    all_stocks: dict[str, dict[str, Any]]
) -> dict[str, float]:
    """
    Compute 20-trading-day return for each stock.

    Returns dict of {symbol: return_pct} where
    return_pct = (close[-1] - close[-21]) / close[-21] * 100

    Only includes stocks with at least 21 price points.
    """
    returns: dict[str, float] = {}
    for sym, data in all_stocks.items():
        close = data.get("close", [])
        if len(close) < 21:
            continue
        old = close[-21]
        new = close[-1]
        if old and old > 0:
            returns[sym] = (new - old) / old * 100.0
    return returns


# ═══════════════════════════════════════════════════════════════════
# Analysis
# ═══════════════════════════════════════════════════════════════════

def _resolve_symbol(signal: dict) -> str:
    """Extract the full symbol (code + .TW/.TWO suffix) from a signal dict."""
    raw = signal.get("code", "")
    if raw.endswith(".TW") or raw.endswith(".TWO"):
        return raw
    # Add exchange suffix from signal dict if present
    ex = signal.get("exchange", "")
    if ex in ("OTC", "櫃"):
        return f"{raw}.TWO"
    return f"{raw}.TW"


def analyze_by_segment(
    signals: list[dict],
    all_stocks: dict[str, dict[str, Any]],
    returns_20d: dict[str, float],
) -> dict:
    """
    Group signals by market (TWSE/OTC) and category (電子/傳產/金融).

    For each segment computes:
        count              — number of signals
        win_20d            — count with positive 20d return
        win_rate_20d       — win_20d / count * 100
        avg_return_20d     — mean 20d return
        returns_available  — count of stocks with 20d return data

    Returns:
        {
            "market": {
                "TWSE": {"count": N, "win_rate_20d": P, "avg_return_20d": R, ...},
                "OTC": {...}
            },
            "category": {
                "電子": {...},
                "傳產": {...},
                "金融": {...},
            }
        }
    """
    # Group by market
    market_groups: dict[str, list[str]] = defaultdict(list)
    category_groups: dict[str, list[str]] = defaultdict(list)

    for sig in signals:
        sym = _resolve_symbol(sig)
        mkt = get_market(sym)
        market_groups[mkt].append(sym)

        # Get code without suffix for sector classification
        code = sig.get("code", sym)
        _, cat = classify_sector(code)
        category_groups[cat].append(sym)

    def _stats(symbols: list[str]) -> dict:
        """Compute stats for a group of symbols."""
        total = len(symbols)
        if total == 0:
            return {"count": 0, "win_rate_20d": 0.0, "avg_return_20d": 0.0, "returns_available": 0}

        rets = []
        for sym in symbols:
            r = returns_20d.get(sym)
            if r is not None:
                rets.append(r)

        wins = sum(1 for r in rets if r > 0)
        n_ret = len(rets)
        win_rate = (wins / n_ret * 100.0) if n_ret > 0 else 0.0
        avg_ret = (sum(rets) / n_ret) if n_ret > 0 else 0.0

        return {
            "count": total,
            "win_20d": wins,
            "win_rate_20d": round(win_rate, 1),
            "avg_return_20d": round(avg_ret, 1),
            "returns_available": n_ret,
        }

    return {
        "market": {k: _stats(v) for k, v in sorted(market_groups.items())},
        "category": {k: _stats(v) for k, v in sorted(category_groups.items())},
    }


# ═══════════════════════════════════════════════════════════════════
# Formatting
# ═══════════════════════════════════════════════════════════════════

def format_segment_line(
    title: str, count: int, win_rate: float, avg_return: float
) -> str:
    """Format a single segment line for display."""
    ret_sign = "+" if avg_return >= 0 else ""
    return f"  {title}: {count} signals, Win 20d: {win_rate:.1f}%, Avg 20d: {ret_sign}{avg_return:.1f}%"


def print_analysis(result: dict) -> None:
    """Pretty-print the analysis result."""
    print("\nMarket Analysis:" if result["market"] else "\nMarket Analysis: (no data)")
    for mkt, stats in result.get("market", {}).items():
        if stats["count"] > 0:
            print(format_segment_line(mkt, stats["count"], stats["win_rate_20d"], stats["avg_return_20d"]))

    print("\nCategory Analysis:" if result["category"] else "\nCategory Analysis: (no data)")
    for cat, stats in result.get("category", {}).items():
        if stats["count"] > 0:
            print(format_segment_line(cat, stats["count"], stats["win_rate_20d"], stats["avg_return_20d"]))


# ═══════════════════════════════════════════════════════════════════
# Standalone entry point
# ═══════════════════════════════════════════════════════════════════

def main() -> None:
    """
    Standalone usage:
        python sector_analysis.py [signals_json] [stocks_json]

    If no arguments given, runs a demo with hardcoded sample data.
    """
    if len(sys.argv) >= 3:
        import json
        with open(sys.argv[1]) as f:
            signals = json.load(f)
        with open(sys.argv[2]) as f:
            all_stocks = json.load(f)
        returns_20d = compute_returns_20d(all_stocks)
        result = analyze_by_segment(signals, all_stocks, returns_20d)
        print_analysis(result)
    else:
        # Demo with sample data
        demo_signals = [
            {"code": "2330", "exchange": "TSE", "score": 85},
            {"code": "2454", "exchange": "TSE", "score": 72},
            {"code": "3008", "exchange": "TSE", "score": 68},
            {"code": "2881", "exchange": "TSE", "score": 90},
            {"code": "2882", "exchange": "TSE", "score": 78},
            {"code": "1101", "exchange": "TSE", "score": 65},
            {"code": "2002", "exchange": "TSE", "score": 55},
            {"code": "2603", "exchange": "TSE", "score": 60},
            {"code": "8927", "exchange": "OTC", "score": 85},
            {"code": "6488", "exchange": "OTC", "score": 70},
            {"code": "5278", "exchange": "OTC", "score": 62},
            {"code": "6186", "exchange": "OTC", "score": 58},
            {"code": "1795", "exchange": "TSE", "score": 69},
            {"code": "3040", "exchange": "TSE", "score": 61},
            {"code": "5521", "exchange": "TSE", "score": 72},
        ]

        # Generate mock price data and returns
        import random
        random.seed(42)
        all_stocks: dict[str, dict] = {}
        returns_20d: dict[str, float] = {}
        for sig in demo_signals:
            code = sig["code"]
            suf = ".TWO" if sig["exchange"] == "OTC" else ".TW"
            sym = f"{code}{suf}"
            base = 100.0
            prices = [base + random.uniform(-5, 5) for _ in range(100)]
            prices.append(base + random.uniform(-10, 15))  # latest
            all_stocks[sym] = {"close": prices, "dates": [], "volume": []}
            ret_pct = (prices[-1] - prices[-21]) / prices[-21] * 100 if len(prices) >= 21 else 0
            returns_20d[sym] = round(ret_pct, 1)

        result = analyze_by_segment(demo_signals, all_stocks, returns_20d)
        print_analysis(result)
        print()


if __name__ == "__main__":
    main()
