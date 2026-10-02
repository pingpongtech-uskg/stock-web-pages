import { describe, expect, it } from 'vitest'
import type { Release } from '../domain/types'
import { loadLatestRelease, validateRelease } from './api'

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
  it('uses the last valid browser release when the latest fetch fails', async () => {
    const originalFetch = globalThis.fetch
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => validRelease(),
    })) as unknown as typeof fetch
    await loadLatestRelease()

    globalThis.fetch = vi.fn(async () => {
      throw new Error('network unavailable')
    }) as unknown as typeof fetch
    const cached = await loadLatestRelease()

    expect(cached.release.runId).toBe('run-1')
    expect(cached.source).toBe('cache')
    window.localStorage.clear()
    globalThis.fetch = originalFetch
  })

  it('marks online release as network sourced', async () => {
    const originalFetch = globalThis.fetch
    globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => validRelease() })) as unknown as typeof fetch
    const loaded = await loadLatestRelease()
    expect(loaded.source).toBe('network')
    expect(loaded.release.runId).toBe('run-1')
    window.localStorage.clear()
    globalThis.fetch = originalFetch
  })

  it('accepts a complete release contract', () => {
    const release = validRelease()
    expect(validateRelease(release)).toBe(release)
  })

  it('accepts a display-only chip reference with optional raw values', () => {
    const release = validRelease() as unknown as Record<string, unknown>
    ;(release.rankings as Record<string, unknown>).trust = [{
      rank: 1, code: '2330', name: '聯電', sector: '', value: 1, valueLabel: '%', status: 'pass', reason: 'official',
      chipReference: {
        schemaVersion: 'chip-reference-v1', status: 'pass', displayOnly: true, formulaVersion: 'chip-reference-v1', dataFreshness: 'current',
        largeHolderTrend: { status: 'pass', value: '1 → 2 → 3', period: '2026-06..2026-08', rawValues: [1, 2, 3], sourceRefs: ['TDCC'] },
        directorSupervisor12m: { status: 'pass', value: '2 vs 1', period: '2026-08 vs 2025-08', rawValues: { latest: 2, prior12m: 1 }, sourceRefs: ['TWSE'] },
        shareholderCountTrend: { status: 'fail', value: '3 → 2 → 1', period: '2026-06..2026-08', sourceRefs: ['TDCC'] },
        sourceRefs: ['TDCC', 'TWSE'], availableAt: '2026-09-04',
      },
    }]
    expect(validateRelease(release)).toBe(release)
  })

  it('accepts an older unknown chip indicator with null raw values', () => {
    const release = validRelease() as unknown as Record<string, unknown>
    ;(release.rankings as Record<string, unknown>).trust = [{
      rank: 1, code: '2330', name: '聯電', sector: '', value: 1, valueLabel: '%', status: 'unknown', reason: 'official',
      chipReference: {
        schemaVersion: 'chip-reference-v1', status: 'unknown', displayOnly: true, formulaVersion: 'chip-reference-v1', dataFreshness: 'stale',
        largeHolderTrend: { status: 'unknown', value: '—', period: '—', rawValues: null, sourceRefs: [] },
        directorSupervisor12m: { status: 'unknown', value: '—', period: '—', rawValues: null, sourceRefs: [] },
        shareholderCountTrend: { status: 'unknown', value: '—', period: '—', rawValues: null, sourceRefs: [] },
        sourceRefs: [], availableAt: null,
      },
    }]
    expect(validateRelease(release)).toBe(release)
  })

  it('rejects a chip reference that is not explicitly display-only', () => {
    const release = validRelease() as unknown as Record<string, unknown>
    ;(release.rankings as Record<string, unknown>).trust = [{
      rank: 1, code: '2330', name: '聯電', sector: '', value: 1, valueLabel: '%', status: 'pass', reason: 'official',
      chipReference: { displayOnly: false },
    }]
    expect(() => validateRelease(release)).toThrow('發布快照格式錯誤')
  })

  it('accepts official and low-position rows without PEG while constraining only growth', () => {
    const release = validRelease() as unknown as Record<string, unknown>
    ;(release.funnel as Record<string, unknown>).strategyCandidates = { trust: 10, growth: 0, lowPosition: 8 }
    ;(release.rankings as Record<string, unknown>).trust = [{
      rank: 1, code: '2330', name: '聯電', sector: '', value: 1, valueLabel: '股',
      status: 'pass', reason: 'official', valuationEvidenceLevel: 'unavailable',
      currentPeg: null, currentPrice: null, fairPrice: null, valuePrice075: null, valuePrice066: null,
    }]
    ;(release.rankings as Record<string, unknown>).lowPosition = [{
      rank: 1, code: '2330', name: '聯電', sector: '', value: -1, valueLabel: '',
      status: 'unknown', reason: 'price observation', valuationEvidenceLevel: 'unavailable',
      currentPeg: null, currentPrice: null, fairPrice: null, valuePrice075: null, valuePrice066: null,
      zScore: -1, slope: 0.1,
    }]
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
