import { describe, expect, it } from 'vitest'
import type { Release } from './types'
import { releaseCoverageFunnel } from './coverage'

describe('releaseCoverageFunnel', () => {
  it('reads the producer-published stage counts instead of guessing from rankings', () => {
    const release = {
      funnel: {
        version: 'funnel-v1',
        universe: 100,
        priceComplete: 7,
        valuationComplete: 6,
        growthValuationComplete: 4,
        pegCandidates: 5,
        strategyCandidates: { trust: 5, growth: 5, lowPosition: 2 },
        formalValuations: 0,
        proxyValuations: 6,
        instrumentPolicy: 'peg-strategies-exclude-non-common-codes-v1',
        instrumentExcluded: 4,
      },
    } as unknown as Pick<Release, 'funnel'>

    expect(releaseCoverageFunnel(release, 'lowPosition')).toMatchObject({
      universe: 100,
      priceComplete: 7,
      valuationComplete: 6,
      growthValuationComplete: 4,
      pegCandidates: 5,
      strategyCandidates: 2,
      formalValuations: 0,
      proxyValuations: 6,
    })
  })

  it('keeps growth stages distinct and does not turn absent coverage into zero', () => {
    const release = { funnel: {
      universe: 100, priceComplete: 40, valuationComplete: 20,
      growthInputComplete: 12, growthValuationComplete: 9, growthThresholdCandidates: 7,
      growthHealthCandidates: 5, growthMissingReasons: [{ reason: 'dividend', count: 18 }],
      pegCandidates: 2, strategyCandidates: { trust: 1, growth: 4, lowPosition: 3 },
      formalValuations: 2, proxyValuations: 18,
    } } as unknown as Pick<Release, 'funnel'>
    expect(releaseCoverageFunnel(release, 'growth')).toMatchObject({
      growthInputComplete: 12,
      growthValuationComplete: 9,
      growthThresholdCandidates: 7,
      growthHealthCandidates: 5,
      strategyCandidates: 4,
      growthMissingReasons: [{ reason: 'dividend', count: 18 }],
    })
    const legacy = { funnel: { universe: 0, priceComplete: 0, valuationComplete: 0, pegCandidates: 0, strategyCandidates: { trust: 0, growth: 0, lowPosition: 0 }, formalValuations: 0, proxyValuations: 0 } } as unknown as Pick<Release, 'funnel'>
    expect(releaseCoverageFunnel(legacy, 'growth').growthInputComplete).toBeNull()
  })
})
