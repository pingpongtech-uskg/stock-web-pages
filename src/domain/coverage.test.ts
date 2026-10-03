import { describe, expect, it } from 'vitest'
import type { HealthCategory, Release } from './types'
import { growthHealthOutcome, qualityStatusCounts, releaseCoverageFunnel } from './coverage'

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

describe('legacy financial and growth health diagnostics', () => {
  it('counts unknown financial states separately from failures and pass-only totals', () => {
    expect(qualityStatusCounts([
      { qualityStatus: 'pass' },
      { qualityStatus: 'fail' },
      { qualityStatus: 'unknown' },
      { qualityStatus: 'unknown' },
      { qualityStatus: 'not_applicable' },
      {} as { qualityStatus: 'unknown' },
    ])).toEqual({ pass: 1, fail: 1, unknown: 2, notApplicable: 1, unreported: 1 })
  })

  it.each([
    ['4 confirmed passes plus one fail qualifies', ['pass', 'pass', 'pass', 'pass', 'fail'], 'qualified'],
    ['4 confirmed passes plus one unknown qualifies', ['pass', 'pass', 'pass', 'pass', 'unknown'], 'qualified'],
    ['3 passes and 2 unknowns remain unknown', ['pass', 'pass', 'pass', 'unknown', 'unknown'], 'unknown'],
    ['3 passes and 2 known failures cannot qualify', ['pass', 'pass', 'pass', 'fail', 'fail'], 'not_qualified'],
  ] as const)('%s', (_label, statuses, expected) => {
    const labels = [
      '月營收 YOY 連續三個月大於 0',
      '近一季毛利年增率大於 0',
      '近一季營業利益年增率大於 0',
      '近一季稅前淨利年增率大於 0',
      '近一季稅後淨利年增率大於 0',
    ]
    const category = { checks: labels.map((label, index) => ({
      label, status: statuses[index], value: '—', period: '—', explanation: '', sourceRefs: [],
    })) }
    expect(growthHealthOutcome(category)).toBe(expected)
  })

  it('does not trust aggregate health flags without the exact five checks', () => {
    const aggregateOnly = { status: 'pass', passCount: 5, checks: [] } as unknown as Pick<HealthCategory, 'checks'>
    expect(growthHealthOutcome(aggregateOnly)).toBe('unknown')
    expect(growthHealthOutcome(undefined)).toBe('unreported')
  })
})
