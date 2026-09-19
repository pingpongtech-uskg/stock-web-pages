import { describe, expect, it } from 'vitest'
import { linearRegression, trustMetrics, revenueGrowth } from './indicators'

describe('lohas-linear-3.5y-research-v1 math', () => {
  it('matches the golden OLS fixture with population residual variance', () => {
    const result = linearRegression([10, 12, 11, 15])

    expect(result.intercept).toBeCloseTo(9.9, 8)
    expect(result.slope).toBeCloseTo(1.4, 8)
    expect(result.lastMid).toBeCloseTo(14.1, 8)
    expect(result.residualSumSquares).toBeCloseTo(4.2, 8)
    expect(result.sigmaSquared).toBeCloseTo(1.05, 8)
    expect(result.z).toBeCloseTo(0.9 / Math.sqrt(1.05), 8)
    expect(result.bands.map((band) => band.k)).toEqual([-2, -1, 0, 1, 2])
  })

  it('returns unknown z for zero residual variance', () => {
    const result = linearRegression([10, 10, 10, 10])
    expect(result.z).toBeNull()
    expect(result.reason).toBe('zero_residual_variance')
  })
})

describe('institutional 10-session math', () => {
  it('uses all ten market sessions and the stock volume denominator', () => {
    const result = trustMetrics(
      [100, -50, 0, 200, 0, -100, 50, 0, 100, 200],
      [1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000],
    )
    expect(result.netShares10).toBe(500)
    expect(result.positiveDays10).toBe(5)
    expect(result.participation10).toBeCloseTo(0.05, 8)
  })

  it('does not turn a missing session into zero', () => {
    const result = trustMetrics([100, 200], [1000, 1000])
    expect(result.status).toBe('unknown')
    expect(result.netShares10).toBeNull()
  })
})

describe('three-month revenue growth', () => {
  it('sums the months before dividing', () => {
    expect(revenueGrowth([110, 120, 130], [100, 100, 100])).toBeCloseTo(0.2, 8)
  })

  it('returns unknown for a non-positive comparison period', () => {
    expect(revenueGrowth([100, 100, 100], [0, 0, 0])).toBeNull()
  })
})
