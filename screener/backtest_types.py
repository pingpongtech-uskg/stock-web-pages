"""🧩 Shared dataclasses for Taiwan stock backtesting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class StockData:
    """Single stock's time-series data.

    Fields:
        symbol:  e.g. "2330.TW" or "6488.TWO"
        name:    Chinese company name (e.g. "台積電")
        market:  Automatically set from suffix — "TWSE" for .TW, "OTC" for .TWO
        dates:   List of trading dates as "YYYY-MM-DD"
        closes:  List of closing prices (float)
        volumes: List of trading volumes (int)
    """

    symbol: str
    name: str
    market: str = ""
    dates: List[str] = field(default_factory=list)
    closes: List[float] = field(default_factory=list)
    volumes: List[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Auto-detect market from symbol suffix; validate array lengths."""
        # Override market based on suffix
        if self.symbol.endswith(".TWO"):
            self.market = "OTC"
        else:
            self.market = "TWSE"

        # Validate lengths
        assert len(self.dates) == len(self.closes), (
            f"dates ({len(self.dates)}) / closes ({len(self.closes)}) length mismatch"
        )
        assert len(self.dates) == len(self.volumes), (
            f"dates ({len(self.dates)}) / volumes ({len(self.volumes)}) length mismatch"
        )

    def date_index(self, date_str: str) -> int:
        """Return the index of *date_str* in ``self.dates``, or -1 if not found."""
        try:
            return self.dates.index(date_str)
        except ValueError:
            return -1

    def __repr__(self) -> str:
        cls = type(self).__name__
        fields = []
        for f in ("symbol", "name", "market", "dates", "closes", "volumes"):
            val = getattr(self, f)
            if isinstance(val, list):
                if not val:
                    fields.append(f"{f}=[]")
                elif f == "dates":
                    fields.append(f"dates=[{val[0]!r}, ...] ({len(val)} days)")
                elif f == "closes":
                    fields.append(f"closes=[{round(val[0], 4)}, ...] ({len(val)} days)")
                elif f == "volumes":
                    fields.append(f"volumes=[{val[0]}, ...] ({len(val)} days)")
            else:
                fields.append(f"{f}={val!r}")
        return f"{cls}({', '.join(fields)})"


@dataclass
class Signal:
    """A pattern signal — metadata about a detected opportunity."""

    symbol: str
    name: str
    signal_date: str
    pattern_type: int
    entry_price: float
    volume_ratio: float
    metadata: Dict = field(default_factory=dict)

    # Layer scoring fields (default None = not yet scored)
    l1_score: float | None = None   # Layer 1: technical score (0-100)
    l2_score: float | None = None   # Layer 2: fundamental score (0-100)
    l3_score: float | None = None   # Layer 3: chip score (0-60)
    total_score: float | None = None  # Weighted total: L1×0.3 + L2×0.5 + L3×0.2

    def compute_total_score(self) -> float | None:
        """Weighted total: L1×0.3 + L2×0.5 + L3×0.2.
        Returns None if any layer score is None."""
        if self.l1_score is None or self.l2_score is None or self.l3_score is None:
            return None
        return self.l1_score * 0.3 + self.l2_score * 0.5 + self.l3_score * 0.2


@dataclass
class PerformanceStats:
    """Performance metrics aggregated for a pattern type."""

    pattern_type: int
    total_signals: int
    win_rate_5d: float
    win_rate_10d: float
    win_rate_20d: float
    win_rate_60d: float
    avg_return_5d: float
    avg_return_10d: float
    avg_return_20d: float
    avg_return_60d: float
    max_drawdown: float
    sharpe_ratio: float
    avg_holding_days: float
    return_std_20d: float
    best_return_20d: float
    worst_return_20d: float

    def __repr__(self) -> str:
        cls = type(self).__name__
        parts: list[str] = []
        for f in (
            "pattern_type", "total_signals",
            "win_rate_5d", "win_rate_10d", "win_rate_20d", "win_rate_60d",
            "avg_return_5d", "avg_return_10d", "avg_return_20d", "avg_return_60d",
            "max_drawdown", "sharpe_ratio", "avg_holding_days",
            "return_std_20d", "best_return_20d", "worst_return_20d",
        ):
            val = getattr(self, f)
            if isinstance(val, float):
                parts.append(f"{f}={round(val, 4)}")
            else:
                parts.append(f"{f}={val}")
        return f"{cls}({', '.join(parts)})"


@dataclass
class SectorInfo:
    """Sector classification for a stock."""

    symbol: str
    sector: str
    category: str
