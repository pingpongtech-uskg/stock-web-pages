import { describe, expect, it } from 'vitest'
import type { Release } from '../domain/types'
import { validateRelease } from './api'

function validRelease(): Release {
  return {
    schemaVersion: '1.1',
    strategyVersion: 'strategy-v1',
    formulaVersion: 'lohas-linear-3.5y-research-v1',
    runId: 'run-1',
    marketDate: '2026-09-18',
    generatedAt: '2026-09-18T00:00:00Z',
    nextExpectedUpdateAt: '2026-09-19T00:00:00Z',
    freshness: 'current',
    statusMessage: 'ok',
    sourceRefs: [],
    coverage: {
      universeCount: 100,
      databaseCount: 100,
      candidateCount: 2,
      pendingCount: 0,
      financialCompleteCount: 2,
      priceCompleteCount: 7,
      completenessPct: 100,
      finmindRequests: null,
      queueStatus: 'ok',
    },
    funnel: {
      version: 'funnel-v1',
      universe: 100,
      priceComplete: 7,
      valuationComplete: 6,
      pegCandidates: 5,
      strategyCandidates: { trust: 5, growth: 5, lowPosition: 2 },
      formalValuations: 0,
      proxyValuations: 6,
      instrumentPolicy: 'peg-strategies-exclude-non-common-codes-v1',
      instrumentExcluded: 4,
    },
    summary: {
      watchCount: 0,
      lowPositionCount: 0,
      candidateRouteCounts: { trust: 0, growth: 0, lowPosition: 0 },
      addedToday: 0,
      improvedToday: 0,
      removedToday: 0,
    },
    stocks: [],
    rankings: {
      trust: [], growth: [], lowPosition: [], lowBase: [], lowBaseGrowth: [], lowBaseQuality: [],
    },
    research: { status: 'not_evaluable', reason: 'test', cagr: null, maxDrawdown: null, periods: [] },
  }
}

describe('validateRelease', () => {
  it('accepts a complete release contract', () => {
    const release = validRelease()
    expect(validateRelease(release)).toBe(release)
  })

  it('rejects a payload without ranking arrays instead of allowing a white screen', () => {
    const invalid = validRelease() as unknown as Record<string, unknown>
    invalid.rankings = { trust: [] }
    expect(() => validateRelease(invalid)).toThrow('發布快照格式錯誤')
  })

  it('rejects malformed freshness and coverage values', () => {
    const invalid = validRelease() as unknown as Record<string, unknown>
    invalid.freshness = 'current-but-old'
    expect(() => validateRelease(invalid)).toThrow('發布快照格式錯誤')
  })

  it('rejects a stringy completenessPct (the v2 white-screen fixture)', () => {
    const invalid = validRelease() as unknown as Record<string, unknown>
    ;(invalid.coverage as Record<string, unknown>).completenessPct = 'broken'
    expect(() => validateRelease(invalid)).toThrow('發布快照格式錯誤')
  })

  it('rejects a missing or non-conserving funnel', () => {
    const missingFunnel = validRelease() as unknown as Record<string, unknown>
    delete missingFunnel.funnel
    expect(() => validateRelease(missingFunnel)).toThrow('發布快照格式錯誤')

    const nonConserving = validRelease() as unknown as Record<string, unknown>
    ;(nonConserving.funnel as Record<string, unknown>).pegCandidates = 7
    expect(() => validateRelease(nonConserving)).toThrow('發布快照格式錯誤')
  })

  it('rejects NaN or wrong-typed values inside a ranking row', () => {
    const invalid = validRelease() as unknown as Record<string, unknown>
    invalid.rankings = {
      trust: [{
        rank: 1, code: '2330', name: '台積電', sector: '', value: 1, valueLabel: '%',
        status: 'pass', reason: 'x', currentPeg: Number.NaN, currentPrice: 100, fairPrice: 200,
      }],
      growth: [], lowPosition: [], lowBase: [], lowBaseGrowth: [], lowBaseQuality: [],
    }
    expect(() => validateRelease(invalid)).toThrow('發布快照格式錯誤')

    const wrongReason = validRelease() as unknown as Record<string, unknown>
    wrongReason.rankings = {
      trust: [{
        rank: 1, code: '2330', name: '台積電', sector: '', value: 1, valueLabel: '%',
        status: 'pass', reason: 42,
      }],
      growth: [], lowPosition: [], lowBase: [], lowBaseGrowth: [], lowBaseQuality: [],
    }
    expect(() => validateRelease(wrongReason)).toThrow('發布快照格式錯誤')
  })
})
