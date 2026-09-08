import unittest

from screener.official_sources import normalize_tdcc_rows


class TDCCNormalizationTests(unittest.TestCase):
    def test_normalizes_bom_month_and_numeric_fields(self):
        rows = [{"\ufeff資料年月": "11507", "股票代號": " 1101 ", "集保股東戶數": "1,234", "本月底保管千股數": "5,678"}]
        result = normalize_tdcc_rows(rows, market="listed")
        self.assertEqual(result, [{"code": "1101", "month": "2026-07", "shareholder_count": 1234.0, "held_thousand_shares": 5678.0, "market": "listed"}])

    def test_rejects_etf_code(self):
        rows = [{"資料年月": "11507", "股票代號": "0050", "集保股東戶數": "10"}]
        with self.assertRaisesRegex(ValueError, "ordinary share"):
            normalize_tdcc_rows(rows, market="listed")

    def test_rejects_invalid_numeric_and_shape(self):
        with self.assertRaisesRegex(ValueError, "rows"):
            normalize_tdcc_rows({"資料年月": "11507"}, market="listed")
        rows = [{"資料年月": "11507", "股票代號": "1101", "集保股東戶數": "bad"}]
        with self.assertRaisesRegex(ValueError, "shareholder_count"):
            normalize_tdcc_rows(rows, market="listed")


if __name__ == "__main__":
    unittest.main()
