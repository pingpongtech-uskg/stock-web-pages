"""Pure calculations mirrored by the browser's published-data contract."""

from __future__ import annotations

import math
from typing import Iterable


def linear_regression(prices: Iterable[float]) -> dict[str, float | None | str]:
    values = [float(value) for value in prices]
    if len(values) < 2 or any(not math.isfinite(value) for value in values):
        return {
            'intercept': None, 'slope': None, 'last_mid': None,
            'residual_sum_squares': None, 'sigma_squared': None,
            'sigma': None, 'z': None, 'reason': 'insufficient_observations',
        }
    n = len(values)
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n
    denominator = sum((index - mean_x) ** 2 for index in range(n))
    numerator = sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values))
    slope = numerator / denominator if denominator else 0.0
    intercept = mean_y - slope * mean_x
    last_mid = intercept + slope * (n - 1)
    residual_sum_squares = sum((value - (intercept + slope * index)) ** 2 for index, value in enumerate(values))
    sigma_squared = residual_sum_squares / n
    sigma = math.sqrt(sigma_squared)
    epsilon = 1e-10 * max(1.0, abs(mean_y))
    reason = 'zero_residual_variance' if sigma <= epsilon else 'ok'
    return {
        'intercept': intercept,
        'slope': slope,
        'last_mid': last_mid,
        'residual_sum_squares': residual_sum_squares,
        'sigma_squared': sigma_squared,
        'sigma': sigma,
        'z': None if reason != 'ok' else (values[-1] - last_mid) / sigma,
        'reason': reason,
    }


def trust_metrics(net_shares: list[float | None], stock_volumes: list[float | None]) -> dict[str, float | int | None | str]:
    if len(net_shares) != 10 or len(stock_volumes) != 10:
        return {'status': 'unknown', 'net_shares_10': None, 'positive_days_10': None, 'participation_10': None}
    if any(value is None or not math.isfinite(value) for value in net_shares):
        return {'status': 'unknown', 'net_shares_10': None, 'positive_days_10': None, 'participation_10': None}
    if any(value is None or not math.isfinite(value) or value <= 0 for value in stock_volumes):
        return {'status': 'unknown', 'net_shares_10': None, 'positive_days_10': None, 'participation_10': None}
    net = sum(value for value in net_shares if value is not None)
    volume = sum(value for value in stock_volumes if value is not None)
    if volume <= 0:
        return {'status': 'unknown', 'net_shares_10': None, 'positive_days_10': None, 'participation_10': None}
    return {
        'status': 'pass',
        'net_shares_10': net,
        'positive_days_10': sum(value > 0 for value in net_shares if value is not None),
        'participation_10': net / volume,
    }


def revenue_growth(latest_three: list[float], prior_year_three: list[float]) -> float | None:
    if len(latest_three) != 3 or len(prior_year_three) != 3:
        return None
    if any(not math.isfinite(value) for value in latest_three + prior_year_three):
        return None
    latest = sum(latest_three)
    prior = sum(prior_year_three)
    return None if prior <= 0 else (latest - prior) / prior
