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

    expect(releaseCoverageFunnel(release, 'lowPosition')).toEqual({
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
})
