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
      growthValuationComplete: null,
      pegCandidates: 5,
      strategyCandidates: 2,
      formalValuations: 0,
      proxyValuations: 6,
    })
  })

  it('keeps growth stages distinct and does not turn absent coverage into zero', () => {
    const release = { funnel: {
      version: 'funnel-v2-independent-trust-low-position', growthCoverageVersion: 'growth-coverage-v1',
      growthEvaluationState: 'partial', universe: 100, priceComplete: 40, valuationComplete: 20,
      growthInputComplete: 12, growthValuationComplete: 9, growthThresholdCandidates: 7,
      growthHealthCandidates: 4, growthMissingReasons: [{ reason: 'dividend', count: 18 }],
      growthTerminalOutcomes: { universe: 60, missing: 40, knownInvalid: 10, extreme: 1, belowThreshold: 2, healthBlocked: 3, selected: 4 },
      growthCandidates: 4,
      pegCandidates: 2, strategyCandidates: { trust: 1, growth: 4, lowPosition: 3 },
      formalValuations: 2, proxyValuations: 18,
    } } as unknown as Pick<Release, 'funnel'>
    expect(releaseCoverageFunnel(release, 'growth')).toMatchObject({
      growthInputComplete: 12,
      growthValuationComplete: 9,
      growthThresholdCandidates: 7,
      growthHealthCandidates: 4,
      strategyCandidates: 4,
      growthEvaluationState: 'partial',
      growthTerminalOutcomes: { universe: 60, missing: 40, knownInvalid: 10, extreme: 1, belowThreshold: 2, healthBlocked: 3, selected: 4 },
      growthMissingReasons: [{ reason: 'dividend', count: 18 }],
    })
    const legacy = { funnel: { universe: 0, priceComplete: 0, valuationComplete: 0, pegCandidates: 0, strategyCandidates: { trust: 0, growth: 0, lowPosition: 0 }, formalValuations: 0, proxyValuations: 0 } } as unknown as Pick<Release, 'funnel'>
    expect(releaseCoverageFunnel(legacy, 'growth').growthInputComplete).toBeNull()
  })

  it('does not mix legacy zero counts into a versioned growth diagnostic group', () => {
    const legacy = { funnel: {
      version: 'funnel-v2-independent-trust-low-position', universe: 100, priceComplete: 100, valuationComplete: 50,
      growthInputComplete: 0, growthValuationComplete: 0, growthThresholdCandidates: 0,
      growthHealthCandidates: 0, growthMissingReasons: [], pegCandidates: 2,
      strategyCandidates: { trust: 3, growth: 0, lowPosition: 4 }, formalValuations: 5, proxyValuations: 45,
    } } as unknown as Pick<Release, 'funnel'>

    expect(releaseCoverageFunnel(legacy, 'growth')).toMatchObject({
      growthInputComplete: null,
      growthValuationComplete: null,
      growthThresholdCandidates: null,
      growthHealthCandidates: null,
      growthMissingReasons: null,
      growthEvaluationState: null,
      growthTerminalOutcomes: null,
    })
  })
})
