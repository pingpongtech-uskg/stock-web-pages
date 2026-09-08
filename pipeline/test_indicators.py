from pipeline.indicators import linear_regression, revenue_growth, trust_metrics


def test_python_ols_matches_golden_fixture():
    result = linear_regression([10, 12, 11, 15])
    assert abs(result['intercept'] - 9.9) < 1e-8
    assert abs(result['slope'] - 1.4) < 1e-8
    assert abs(result['last_mid'] - 14.1) < 1e-8
    assert abs(result['residual_sum_squares'] - 4.2) < 1e-8
    assert abs(result['sigma_squared'] - 1.05) < 1e-8
    assert abs(result['z'] - (0.9 / 1.05**0.5)) < 1e-8


def test_python_trust_window_uses_stock_volume():
    result = trust_metrics([100, -50, 0, 200, 0, -100, 50, 0, 100, 200], [1000] * 10)
    assert result == {'status': 'pass', 'net_shares_10': 500, 'positive_days_10': 5, 'participation_10': 0.05}


def test_python_revenue_growth_sums_before_dividing():
    assert abs(revenue_growth([110, 120, 130], [100, 100, 100]) - 0.2) < 1e-8
