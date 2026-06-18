"""Tests for data_loader.py — loading batch JSON files."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from data_loader import load_stocks


def _make_batch(dirpath: str, batch_num: int, stocks: dict) -> str:
    """Helper: write a batch_XXX.json file."""
    path = os.path.join(dirpath, f"batch_{batch_num:03d}.json")
    with open(path, "w") as f:
        json.dump(stocks, f)
    return path


def _gen_stock(
    symbol: str,
    name: str,
    num_days: int = 130,
    start_date: str = "2024-06-01",
    close_base: float = 100.0,
) -> dict:
    """Generate a synthetic stock entry with *num_days* of data."""
    from datetime import datetime, timedelta

    start = datetime.strptime(start_date, "%Y-%m-%d")
    dates: list[str] = []
    closes: list[float] = []
    volumes: list[int] = []
    for i in range(num_days):
        dt = start + timedelta(days=i)
        date_str = dt.strftime("%Y-%m-%d")
        dates.append(date_str)
        closes.append(round(close_base + i * 0.1, 2))
        volumes.append(1000 + i * 10)
    end_date = dates[-1]
    return {
        "dates": dates,
        "close": closes,
        "volume": volumes,
        "start": dates[0],
        "end": end_date,
        "days": num_days,
        "name": name,
    }


class TestLoadStocks:
    """load_stocks() — core functionality."""

    # ── Happy path ──────────────────────────────────────

    def test_basic_load_single_batch(self):
        """Single batch with one stock >= 120 days returns that stock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_batch(tmpdir, 1, {
                "2330.TW": _gen_stock("2330.TW", "台積電", num_days=130),
            })
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert "2330.TW" in result
            sd = result["2330.TW"]
            assert sd.symbol == "2330.TW"
            assert sd.name == "台積電"
            assert sd.market == "TWSE"
            assert len(sd.dates) >= 120
            assert len(sd.dates) == len(sd.closes) == len(sd.volumes)

    def test_otc_market_detected(self):
        """Stock ending in .TWO gets market='OTC'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_batch(tmpdir, 1, {
                "6488.TWO": _gen_stock("6488.TWO", "環球晶圓", num_days=130),
            })
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert result["6488.TWO"].market == "OTC"

    def test_multiple_batches_combined(self):
        """Stocks from across multiple batch files are merged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_batch(tmpdir, 1, {
                "2330.TW": _gen_stock("2330.TW", "台積電", num_days=130),
            })
            _make_batch(tmpdir, 2, {
                "6488.TWO": _gen_stock("6488.TWO", "環球晶圓", num_days=130),
            })
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert len(result) == 2
            assert "2330.TW" in result
            assert "6488.TWO" in result

    def test_batch_files_sorted_loaded(self):
        """Batch files are loaded in sorted order (reproducibility)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_batch(tmpdir, 5, {
                "Z.TW": _gen_stock("Z.TW", "Z", num_days=130),
            })
            _make_batch(tmpdir, 1, {
                "A.TW": _gen_stock("A.TW", "A", num_days=130),
            })
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            # Both should be present regardless of order
            assert "A.TW" in result
            assert "Z.TW" in result

    # ── Date filtering ─────────────────────────────────

    def test_date_filtering_slice(self):
        """Data outside [start_date, end_date] is sliced out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Stock has data from 2020-01-01 with 2000 days (spans past 2024-12-31)
            stock = _gen_stock("2330.TW", "台積電", num_days=2000, start_date="2020-01-01")
            _make_batch(tmpdir, 1, {"2330.TW": stock})
            result = load_stocks(tmpdir, "2024-06-01", "2024-12-31")
            sd = result["2330.TW"]
            # All dates should be within range
            assert sd.dates[0] >= "2024-06-01"
            assert sd.dates[-1] <= "2024-12-31"
            assert len(sd.dates) >= 120

    # ── Minimum days threshold ──────────────────────────

    def test_skip_less_than_120_days(self):
        """Stock with < 120 days in range is excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_batch(tmpdir, 1, {
                "2330.TW": _gen_stock("2330.TW", "台積電", num_days=50),
            })
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert "2330.TW" not in result

    def test_exactly_120_days_kept(self):
        """Stock with exactly 120 days in range is kept."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_batch(tmpdir, 1, {
                "2330.TW": _gen_stock("2330.TW", "台積電", num_days=120),
            })
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert "2330.TW" in result
            assert len(result["2330.TW"].dates) == 120

    def test_119_days_skipped(self):
        """Stock with exactly 119 days in range is excluded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _make_batch(tmpdir, 1, {
                "2330.TW": _gen_stock("2330.TW", "台積電", num_days=119),
            })
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert "2330.TW" not in result

    # ── Edge cases: file issues ─────────────────────────

    def test_empty_batch_file_skipped(self):
        """An empty batch file is skipped with a warning (no crash)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "batch_001.json")
            with open(path, "w") as f:
                f.write("")
            _make_batch(tmpdir, 2, {
                "2330.TW": _gen_stock("2330.TW", "台積電", num_days=130),
            })
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert "2330.TW" in result

    def test_invalid_json_skipped(self):
        """A non-JSON batch file is skipped with a warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "batch_001.json")
            with open(path, "w") as f:
                f.write("{invalid json!!!}")
            _make_batch(tmpdir, 2, {
                "2330.TW": _gen_stock("2330.TW", "台積電", num_days=130),
            })
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert "2330.TW" in result

    def test_no_batch_files_returns_empty(self):
        """Directory with no batch_*.json returns empty dict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert result == {}

    # ── Edge cases: data format ─────────────────────────

    def test_missing_name_field_uses_symbol(self):
        """When 'name' field is missing, fall back to symbol as name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stock = _gen_stock("2330.TW", "台積電", num_days=130)
            del stock["name"]
            _make_batch(tmpdir, 1, {"2330.TW": stock})
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert result["2330.TW"].name == "2330.TW"

    def test_string_close_converted_to_float(self):
        """Close values that are strings are converted to float."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stock = _gen_stock("2330.TW", "台積電", num_days=130)
            stock["close"] = [str(v) for v in stock["close"]]
            _make_batch(tmpdir, 1, {"2330.TW": stock})
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            for c in result["2330.TW"].closes[:5]:
                assert isinstance(c, float)

    def test_string_volume_converted_to_int(self):
        """Volume values that are strings are converted to int."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stock = _gen_stock("2330.TW", "台積電", num_days=130)
            stock["volume"] = [str(v) for v in stock["volume"]]
            _make_batch(tmpdir, 1, {"2330.TW": stock})
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            for v in result["2330.TW"].volumes[:5]:
                assert isinstance(v, int)

    def test_zero_volume_days_kept(self):
        """Stocks with zero-volume days should still be included."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stock = _gen_stock("2330.TW", "台積電", num_days=130)
            stock["volume"][0] = 0
            stock["volume"][10] = 0
            _make_batch(tmpdir, 1, {"2330.TW": stock})
            result = load_stocks(tmpdir, "2024-06-01", "2025-01-01")
            assert "2330.TW" in result

    # ── Full smoke (real data) ──────────────────────────

    def test_load_real_data(self):
        """Load from the actual data dir — verify counts, shape, and range."""
        result = load_stocks(
            "/root/tw-stock-monitor/data",
            "2024-06-01",
            "2026-05-22",
        )
        assert len(result) > 0, "Should load at least one stock"
        # Spot-check a known stock
        assert "2330.TW" in result, "TSMC (2330.TW) should be present"
        sd = result["2330.TW"]
        assert sd.name != "", "Stock name should not be empty"
        assert sd.market == "TWSE"
        assert len(sd.dates) >= 120
        assert sd.dates[0] >= "2024-06-01"
        assert sd.dates[-1] <= "2026-05-22"

        # Check TWSE vs OTC detection
        twse = sum(1 for s in result.values() if s.market == "TWSE")
        otc = sum(1 for s in result.values() if s.market == "OTC")
        assert twse > 0, "Should have TWSE stocks"
        assert otc > 0, "Should have OTC stocks"
