export type MetricStatus = 'pass' | 'fail' | 'unknown' | 'not_applicable'

export interface RegressionBand {
  k: -2 | -1 | 0 | 1 | 2
  value: number
}

export interface RegressionResult {
  intercept: number
  slope: number
  lastMid: number
  residualSumSquares: number
  sigmaSquared: number
  sigma: number
  z: number | null
  bands: RegressionBand[]
  reason: 'ok' | 'insufficient_observations' | 'zero_residual_variance'
}

export interface TrustResult {
  status: MetricStatus
  netShares10: number | null
  positiveDays10: number | null
  participation10: number | null
}

/**
 * lohas-linear-3.5y-research-v1 OLS over already validated, date-sorted prices.
 * The caller is responsible for enforcing the fixed 3.5-year window
 * and 95% coverage rule before treating this as a formal signal.
 */
export function linearRegression(prices: number[]): RegressionResult {
  if (prices.length < 2 || prices.some((price) => !Number.isFinite(price))) {
    return {
      intercept: 0,
      slope: 0,
      lastMid: 0,
      residualSumSquares: 0,
      sigmaSquared: 0,
      sigma: 0,
      z: null,
      bands: [],
      reason: 'insufficient_observations',
    }
  }

  const n = prices.length
  const meanX = (n - 1) / 2
  const meanY = prices.reduce((sum, value) => sum + value, 0) / n
  const denominator = prices.reduce((sum, _value, index) => sum + (index - meanX) ** 2, 0)
  const numerator = prices.reduce((sum, value, index) => sum + (index - meanX) * (value - meanY), 0)
  const slope = denominator === 0 ? 0 : numerator / denominator
  const intercept = meanY - slope * meanX
  const lastMid = intercept + slope * (n - 1)
  const residualSumSquares = prices.reduce((sum, value, index) => {
    const residual = value - (intercept + slope * index)
    return sum + residual ** 2
  }, 0)
  const sigmaSquared = residualSumSquares / n
  const sigma = Math.sqrt(sigmaSquared)
  const epsilon = 1e-10 * Math.max(1, Math.abs(meanY))
  const reason = sigma <= epsilon ? 'zero_residual_variance' : 'ok'
  const z = reason === 'ok' ? (prices[n - 1] - lastMid) / sigma : null

  return {
    intercept,
    slope,
    lastMid,
    residualSumSquares,
    sigmaSquared,
    sigma,
    z,
    bands: ([-2, -1, 0, 1, 2] as const).map((k) => ({
      k,
      value: lastMid + k * sigma,
    })),
    reason,
  }
}

/** Calculate the ten actual market-session trust window. */
export function trustMetrics(
  netShares: Array<number | null>,
  stockVolumes: Array<number | null>,
): TrustResult {
  if (
    netShares.length !== 10 ||
    stockVolumes.length !== 10 ||
    netShares.some((value) => value === null || !Number.isFinite(value)) ||
    stockVolumes.some((value) => value === null || !Number.isFinite(value) || value <= 0)
  ) {
    return { status: 'unknown', netShares10: null, positiveDays10: null, participation10: null }
  }

  const netShares10 = (netShares as number[]).reduce((sum, value) => sum + value, 0)
  const positiveDays10 = (netShares as number[]).filter((value) => value > 0).length
  const totalVolume = (stockVolumes as number[]).reduce((sum, value) => sum + value, 0)

  if (totalVolume <= 0) {
    return { status: 'unknown', netShares10: null, positiveDays10: null, participation10: null }
  }

  return {
    status: 'pass',
    netShares10,
    positiveDays10,
    participation10: netShares10 / totalVolume,
  }
}

/** Sum the three months before dividing; never average monthly growth rates. */
export function revenueGrowth(latestThreeMonths: number[], priorYearThreeMonths: number[]): number | null {
  if (
    latestThreeMonths.length !== 3 ||
    priorYearThreeMonths.length !== 3 ||
    latestThreeMonths.some((value) => !Number.isFinite(value)) ||
    priorYearThreeMonths.some((value) => !Number.isFinite(value))
  ) {
    return null
  }

  const latest = latestThreeMonths.reduce((sum, value) => sum + value, 0)
  const prior = priorYearThreeMonths.reduce((sum, value) => sum + value, 0)
  return prior > 0 ? (latest - prior) / prior : null
}
