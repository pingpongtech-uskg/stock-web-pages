"""Tests for sector_analysis.py — market/sector breakdown analysis."""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sector_analysis import (
    classify_sector,
    get_market,
    analyze_by_segment,
    compute_returns_20d,
    CATEGORIES,
)


# ═══════════════════════════════════════════════
# classify_sector tests
# ═══════════════════════════════════════════════

class TestClassifySector:
    def test_semiconductor_electronics(self):
        """2330 (台積電) → 半導體, 電子"""
        name, cat = classify_sector("2330")
        assert name == "半導體"
        assert cat == "電子"

    def test_computer_peripheral_electronics(self):
        """2382 (廣達) → 電腦週邊, 電子"""
        name, cat = classify_sector("2382")
        assert name == "電腦週邊"
        assert cat == "電子"

    def test_optics_electronics(self):
        """3008 (大立光) → 光電, 電子"""
        name, cat = classify_sector("3008")
        assert name == "光電"
        assert cat == "電子"

    def test_elec_components_electronics(self):
        """3231 (緯創) → 電子零組件, 電子"""
        name, cat = classify_sector("3231")
        assert name == "電子零組件"
        assert cat == "電子"

    def test_elec_channel_electronics(self):
        """3702 (大聯大) → 電子通路, 電子"""
        name, cat = classify_sector("3702")
        assert name == "電子通路"
        assert cat == "電子"

    def test_other_elec_electronics(self):
        """8046 (南電) → 其他電子, 電子"""
        name, cat = classify_sector("8046")
        assert name == "其他電子"
        assert cat == "電子"

    def test_it_service_electronics(self):
        """6112 (聚碩) → 資訊服務, 電子"""
        name, cat = classify_sector("6112")
        assert name == "資訊服務"
        assert cat == "電子"

    def test_financial_finance(self):
        """2881 (富邦金) → 金融保險, 金融"""
        name, cat = classify_sector("2881")
        assert name == "金融保險"
        assert cat == "金融"

    def test_cement_traditional(self):
        """1101 (台泥) → 水泥, 傳產"""
        name, cat = classify_sector("1101")
        assert name == "水泥"
        assert cat == "傳產"

    def test_food_traditional(self):
        """1216 (統一) → 食品, 傳產"""
        name, cat = classify_sector("1216")
        assert name == "食品"
        assert cat == "傳產"

    def test_steel_traditional(self):
        """2002 (中鋼) → 鋼鐵, 傳產"""
        name, cat = classify_sector("2002")
        assert name == "鋼鐵"
        assert cat == "傳產"

    def test_shipping_traditional(self):
        """2603 (長榮) → 航運, 傳產"""
        name, cat = classify_sector("2603")
        assert name == "航運"
        assert cat == "傳產"

    def test_construction_traditional(self):
        """2501 (國建) → 營建, 傳產"""
        name, cat = classify_sector("2501")
        assert name == "營建"
        assert cat == "傳產"

    def test_biotech_traditional(self):
        """1730 (杏一) → 生技醫療, 傳產"""
        name, cat = classify_sector("1730")
        assert name == "生技醫療"
        assert cat == "傳產"

    def test_chemical_traditional(self):
        """1711 (永光) → 化學, 傳產"""
        name, cat = classify_sector("1711")
        assert name == "化學"
        assert cat == "傳產"

    def test_textile_traditional(self):
        """1402 (遠東新) → 紡織, 傳產"""
        name, cat = classify_sector("1402")
        assert name == "紡織"
        assert cat == "傳產"

    def test_machinery_traditional(self):
        """1504 (東元) → 電機機械, 傳產"""
        name, cat = classify_sector("1504")
        assert name == "電機機械"
        assert cat == "傳產"

    def test_electric_cable_traditional(self):
        """1605 (華新) → 電器電纜, 傳產"""
        name, cat = classify_sector("1605")
        assert name == "電器電纜"
        assert cat == "傳產"

    def test_plastic_traditional(self):
        """1301 (台塑) → 塑膠, 傳產"""
        name, cat = classify_sector("1301")
        assert name == "塑膠"
        assert cat == "傳產"

    def test_automotive_traditional(self):
        """2201 (裕隆) → 汽車, 傳產"""
        name, cat = classify_sector("2201")
        assert name == "汽車"
        assert cat == "傳產"

    def test_glass_traditional(self):
        """1802 (台玻) → 玻璃陶瓷, 傳產"""
        name, cat = classify_sector("1802")
        assert name == "玻璃陶瓷"
        assert cat == "傳產"

    def test_paper_traditional(self):
        """1902 (台紙) → 造紙, 傳產"""
        name, cat = classify_sector("1902")
        assert name == "造紙"
        assert cat == "傳產"

    def test_rubber_traditional(self):
        """2101 (南港) → 橡膠, 傳產"""
        name, cat = classify_sector("2101")
        assert name == "橡膠"
        assert cat == "傳產"

    def test_tourism_traditional(self):
        """2701 (萬企) → 觀光, 傳產"""
        name, cat = classify_sector("2701")
        assert name == "觀光"
        assert cat == "傳產"

    def test_department_store_traditional(self):
        """2903 (遠百) → 貿易百貨, 傳產"""
        name, cat = classify_sector("2903")
        assert name == "貿易百貨"
        assert cat == "傳產"

    def test_leisure_traditional(self):
        """8464 (軒郁) → 運動休閒, 傳產"""
        name, cat = classify_sector("8464")
        assert name == "運動休閒"
        assert cat == "傳產"

    def test_other_traditional(self):
        """9904 (寶成) → 其他, 傳產"""
        name, cat = classify_sector("9904")
        assert name == "其他"
        assert cat == "傳產"

    def test_communication_network_non_elec(self):
        """33xx is NOT in the electronics prefix list → 傳產"""
        name, cat = classify_sector("3311")
        assert name == "通信網路"
        assert cat == "傳產"

    def test_otc_code_input(self):
        """Stock code with .TWO suffix"""
        name, cat = classify_sector("8927.TWO")
        assert cat == "傳產"

    def test_twse_code_input(self):
        """Stock code with .TW suffix"""
        name, cat = classify_sector("2330.TW")
        assert name == "半導體"
        assert cat == "電子"

    def test_unknown_short_code(self):
        """Less than 4 digits → '其他', '傳產'"""
        name, cat = classify_sector("999")
        assert cat == "傳產"

    def test_unknown_empty(self):
        """Empty string → '其他', '傳產'"""
        name, cat = classify_sector("")
        assert cat == "傳產"

    def test_50xx_electronics(self):
        """50xx is in the electronics prefix list"""
        name, cat = classify_sector("5007")
        assert cat == "電子"

    def test_51xx_traditional(self):
        """51xx is NOT in the electronics prefix list → 傳產"""
        name, cat = classify_sector("5102")
        assert cat == "傳產"

    def test_810x_not_elec(self):
        """81xx is NOT in the electronics prefix list → 傳產"""
        name, cat = classify_sector("8101")
        assert cat == "傳產"

    def test_has_at_least_30_sectors(self):
        """check that we have at least 30 distinct sector names"""
        tested = set()
        for prefix in [f"{i:02d}" for i in range(10, 100)]:
            code = prefix + "01"
            name, _ = classify_sector(code)
            tested.add(name)
        assert len(tested) >= 30, f"Only {len(tested)} unique sectors, need ≥30"


# ═══════════════════════════════════════════════
# get_market tests
# ═══════════════════════════════════════════════

class TestGetMarket:
    def test_twse_explicit(self):
        assert get_market("2330.TW") == "TWSE"

    def test_otc_explicit(self):
        assert get_market("8927.TWO") == "OTC"

    def test_bare_code_default_twse(self):
        assert get_market("2330") == "TWSE"

    def test_6xxx_default_twse(self):
        """6xxx codes (like 6112) default to TWSE"""
        assert get_market("6112") == "TWSE"

    def test_1xxx_default_twse(self):
        assert get_market("1101") == "TWSE"

    def test_8xxx_default_otc(self):
        """8xxx codes default to OTC for bare codes"""
        assert get_market("8927") == "OTC"

    def test_5xxx_default_twse(self):
        assert get_market("5007") == "TWSE"


# ═══════════════════════════════════════════════
# compute_returns_20d tests
# ═══════════════════════════════════════════════

class TestComputeReturns20d:
    def test_basic_computation(self):
        """Compute 20d returns from stock data"""
        stock_data = {
            "2330.TW": {"close": [100.0] * 100 + [110.0]}
        }
        returns = compute_returns_20d(stock_data)
        # 100 * 80 → close[-21] is 100.0, close[-1] is 110.0 → (110-100)/100 = 10%
        assert "2330.TW" in returns
        assert returns["2330.TW"] == pytest.approx(10.0, abs=0.01)

    def test_not_enough_data(self):
        """Less than 21 days → None"""
        stock_data = {
            "2330.TW": {"close": [100.0] * 5}
        }
        returns = compute_returns_20d(stock_data)
        assert "2330.TW" not in returns

    def test_negative_return(self):
        """Negative return case"""
        stock_data = {
            "5007.TWO": {"close": [100.0] * 100 + [90.0]}
        }
        returns = compute_returns_20d(stock_data)
        assert returns["5007.TWO"] == pytest.approx(-10.0, abs=0.01)

    def test_empty_input(self):
        assert compute_returns_20d({}) == {}


# ═══════════════════════════════════════════════
# analyze_by_segment tests
# ═══════════════════════════════════════════════

class TestAnalyzeBySegment:
    def test_empty_signals(self):
        result = analyze_by_segment([], {}, {})
        assert result == {"market": {}, "category": {}}

    def test_basic_market_breakdown(self):
        signals = [
            {"code": "2330", "score": 80},
            {"code": "8927.TWO", "score": 70},
            {"code": "1101", "score": 60},
        ]
        all_stocks = {"2330.TW": {"close": [100] * 200}, "8927.TWO": {"close": [100] * 200}, "1101.TW": {"close": [100] * 200}}
        returns_20d = {"2330.TW": 5.0, "8927.TWO": 3.0, "1101.TW": -2.0}

        result = analyze_by_segment(signals, all_stocks, returns_20d)
        mkt = result["market"]
        assert "TWSE" in mkt
        assert "OTC" in mkt
        assert mkt["TWSE"]["count"] == 2
        assert mkt["OTC"]["count"] == 1

    def test_basic_category_breakdown(self):
        signals = [
            {"code": "2330"},  # 半導體, 電子
            {"code": "1101"},  # 水泥, 傳產
            {"code": "2881"},  # 金融保險, 金融
        ]
        all_stocks = {"2330.TW": {"close": [100] * 200}, "1101.TW": {"close": [100] * 200}, "2881.TW": {"close": [100] * 200}}
        returns_20d = {"2330.TW": 5.0, "1101.TW": -2.0, "2881.TW": 3.0}

        result = analyze_by_segment(signals, all_stocks, returns_20d)
        cat = result["category"]
        assert "電子" in cat
        assert "傳產" in cat
        assert "金融" in cat
        assert cat["電子"]["count"] == 1
        assert cat["傳產"]["count"] == 1
        assert cat["金融"]["count"] == 1

    def test_win_rate_20d(self):
        """win_rate_20d = fraction of stocks with positive 20d return"""
        signals = [
            {"code": "2330"},
            {"code": "1101"},
            {"code": "2002"},
            {"code": "2881"},
        ]
        all_stocks = {f"{c}.TW": {"close": [100] * 200} for c in ["2330", "1101", "2002", "2881"]}
        # 2330 up, 1101 down, 2002 up, 2881 up → 75% win
        returns_20d = {"2330.TW": 3.0, "1101.TW": -1.0, "2002.TW": 2.0, "2881.TW": 5.0}

        result = analyze_by_segment(signals, all_stocks, returns_20d)
        mkt = result["market"]
        assert mkt["TWSE"]["win_rate_20d"] == pytest.approx(75.0, abs=0.1)

    def test_avg_return_20d(self):
        signals = [
            {"code": "2330"},
            {"code": "1101"},
        ]
        all_stocks = {"2330.TW": {"close": [100] * 200}, "1101.TW": {"close": [100] * 200}}
        returns_20d = {"2330.TW": 10.0, "1101.TW": 4.0}

        result = analyze_by_segment(signals, all_stocks, returns_20d)
        mkt = result["market"]
        assert mkt["TWSE"]["avg_return_20d"] == pytest.approx(7.0, abs=0.1)

    def test_signal_with_explicit_suffix(self):
        """Signal codes with .TW/.TWO suffix are parsed correctly"""
        signals = [
            {"code": "2330.TW"},
            {"code": "8927.TWO"},
        ]
        all_stocks = {"2330.TW": {"close": [100] * 200}, "8927.TWO": {"close": [100] * 200}}
        returns_20d = {"2330.TW": 5.0, "8927.TWO": 3.0}

        result = analyze_by_segment(signals, all_stocks, returns_20d)
        assert result["market"]["TWSE"]["count"] == 1
        assert result["market"]["OTC"]["count"] == 1

    def test_signals_with_missing_returns(self):
        """Stocks without 20d return data are counted but skipped in avg"""
        signals = [{"code": "2330"}, {"code": "9999"}]
        all_stocks = {"2330.TW": {"close": [100] * 200}}
        returns_20d = {"2330.TW": 5.0}

        result = analyze_by_segment(signals, all_stocks, returns_20d)
        assert result["market"]["TWSE"]["count"] == 2
        assert result["market"]["TWSE"]["returns_available"] == 1


# ═══════════════════════════════════════════════
# Standalone output tests
# ═══════════════════════════════════════════════

class TestStandaloneOutput:
    def test_format_line(self):
        """Verify the output format matches the spec"""
        from sector_analysis import format_segment_line
        line = format_segment_line("TWSE", 85, 65.2, 4.8)
        assert "TWSE" in line
        assert "85" in line
        assert "65.2%" in line or "65.2" in line
        assert "4.8%" in line or "4.8" in line

    def test_categories_constants(self):
        """Verify CATEGORIES dict exists"""
        assert isinstance(CATEGORIES, dict)
        assert "電子" in CATEGORIES
        assert "傳產" in CATEGORIES
        assert "金融" in CATEGORIES
