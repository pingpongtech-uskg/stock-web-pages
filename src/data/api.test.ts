import publishedSnapshot from '../../public/data/latest.json'
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

function validGrowthStock() {
  const evidence = { origin: 'unavailable', sourcePeriod: null, method: null, source: null, reason: '資料尚未取得' }
  return {
    code: '2330', name: '台積電',
    growthValuation: {
      status: 'unavailable', reason: '缺少輸入', inputsComplete: false, missingReasons: ['dividendYield'],
      inputAudit: { price: evidence, pe: evidence, ttmEps: evidence, earningsGrowth: evidence, dividendYield: evidence },
    },
    growthHealthEligible: false,
    healthCategories: [{ key: 'growth', label: '成長健康', passCount: 0, total: 5, threshold: 4, status: 'unknown', checks: Array.from({ length: 5 }, (_, index) => ({ label: `檢查 ${index}`, status: 'unknown', value: '—', period: '—', explanation: '資料不足', sourceRefs: [] })) }],
  }
}

describe('validateRelease', () => {
  it('uses the last valid browser release when the latest fetch fails', async () => {
    const originalFetch = globalThis.fetch
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      text: async () => JSON.stringify(validRelease()),
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
    globalThis.fetch = vi.fn(async () => ({ ok: true, text: async () => JSON.stringify(validRelease()) })) as unknown as typeof fetch
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

  it('accepts the versioned growth coverage contract when every stage and terminal outcome is present', () => {
    const release = validRelease() as unknown as Record<string, unknown>
    const funnel = release.funnel as Record<string, unknown>
    Object.assign(funnel, {
      growthCoverageVersion: 'growth-coverage-v1',
      growthEvaluationState: 'partial',
      growthInputComplete: 12,
      growthValuationComplete: 9,
      growthThresholdCandidates: 7,
      growthHealthCandidates: 4,
      growthCandidates: 4,
      growthMissingReasons: [{ reason: 'dividendYield', count: 20 }],
      growthTerminalOutcomes: { universe: 96, missing: 76, knownInvalid: 10, extreme: 1, belowThreshold: 2, healthBlocked: 3, selected: 4 },
    })
    funnel.strategyCandidates = { trust: 1, growth: 4, lowPosition: 0 }
    release.stocks = [validGrowthStock()]

    expect(validateRelease(release)).toBe(release)
  })

  it('rejects a declared growth v1 release when a required stage is missing or terminal counts do not conserve', () => {
    const missingStage = validRelease() as unknown as Record<string, unknown>
    const missingFunnel = missingStage.funnel as Record<string, unknown>
    Object.assign(missingFunnel, {
      growthCoverageVersion: 'growth-coverage-v1', growthEvaluationState: 'not_evaluable',
      growthInputComplete: 0, growthValuationComplete: 0, growthThresholdCandidates: 0,
      growthHealthCandidates: 0, growthCandidates: 0, growthMissingReasons: [],
      growthTerminalOutcomes: { universe: 0, missing: 0, knownInvalid: 0, extreme: 0, belowThreshold: 0, healthBlocked: 0, selected: 0 },
    })
    delete missingFunnel.growthHealthCandidates
    expect(() => validateRelease(missingStage)).toThrow('發布快照格式錯誤')

    const nonConserving = validRelease() as unknown as Record<string, unknown>
    const funnel = nonConserving.funnel as Record<string, unknown>
    Object.assign(funnel, {
      growthCoverageVersion: 'growth-coverage-v1', growthEvaluationState: 'evaluated',
      growthInputComplete: 1, growthValuationComplete: 1, growthThresholdCandidates: 1,
      growthHealthCandidates: 1, growthCandidates: 1, growthMissingReasons: [],
      growthTerminalOutcomes: { universe: 2, missing: 0, knownInvalid: 0, extreme: 0, belowThreshold: 0, healthBlocked: 0, selected: 1 },
    })
    funnel.strategyCandidates = { trust: 0, growth: 1, lowPosition: 0 }
    expect(() => validateRelease(nonConserving)).toThrow('發布快照格式錯誤')
  })

  it('rejects a v1 release that omits per-stock source audit needed to explain the aggregate', () => {
    const release = validRelease() as unknown as Record<string, unknown>
    const funnel = release.funnel as Record<string, unknown>
    Object.assign(funnel, {
      growthCoverageVersion: 'growth-coverage-v1', growthEvaluationState: 'not_evaluable',
      growthInputComplete: 0, growthValuationComplete: 0, growthThresholdCandidates: 0,
      growthHealthCandidates: 0, growthCandidates: 0, growthMissingReasons: [],
      growthTerminalOutcomes: { universe: 1, missing: 1, knownInvalid: 0, extreme: 0, belowThreshold: 0, healthBlocked: 0, selected: 0 },
    })
    const stock = validGrowthStock() as unknown as Record<string, unknown>
    delete (stock.growthValuation as Record<string, unknown>).inputAudit
    release.stocks = [stock]
    expect(() => validateRelease(release)).toThrow('發布快照格式錯誤')
  })

  it('rejects growth v1 fields without the independent coverage-version marker', () => {
    const release = validRelease() as unknown as Record<string, unknown>
    ;(release.funnel as Record<string, unknown>).growthInputComplete = 0
    expect(() => validateRelease(release)).toThrow('發布快照格式錯誤')
  })

  it('rejects new diagnostic fields without the marker while accepting known legacy fields', () => {
    const legacy = validRelease() as unknown as Record<string, unknown>
    const funnel = legacy.funnel as Record<string, unknown>
    funnel.growthValuationComplete = 3
    funnel.growthCandidates = 5
    expect(validateRelease(legacy)).toBe(legacy)

    funnel.growthMissingReasons = []
    expect(() => validateRelease(legacy)).toThrow('發布快照格式錯誤')
  })

  it('requires growth terminal outcomes to match the eligible common-share universe', () => {
    const release = validRelease() as unknown as Record<string, unknown>
    const funnel = release.funnel as Record<string, unknown>
    Object.assign(funnel, {
      growthCoverageVersion: 'growth-coverage-v1', growthEvaluationState: 'partial',
      growthInputComplete: 12, growthValuationComplete: 9, growthThresholdCandidates: 7,
      growthHealthCandidates: 4, growthCandidates: 4, growthMissingReasons: [],
      growthTerminalOutcomes: { universe: 60, missing: 40, knownInvalid: 10, extreme: 1, belowThreshold: 2, healthBlocked: 3, selected: 4 },
    })
    funnel.strategyCandidates = { trust: 1, growth: 4, lowPosition: 0 }
    release.stocks = [validGrowthStock()]
    expect(() => validateRelease(release)).toThrow('發布快照格式錯誤')
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

  it.each([{ sourceDates: [42] }, { sourceDates: ['invalid'] }, { retrievedAt: 'invalid' }, { historicalBackfill: 'true' }])('rejects malformed optional chip provenance: %j', (metadata) => {
    const release = validRelease() as unknown as Record<string, unknown>
    const indicator = { status: 'unknown', value: '—', period: '—', sourceRefs: [] }
    ;(release.rankings as Record<string, unknown>).trust = [{
      rank: 1, code: '2330', name: '台積電', sector: '', value: 1, valueLabel: '%', status: 'pass', reason: 'official',
      chipReference: {
        schemaVersion: 'chip-reference-v1', status: 'unknown', displayOnly: true, formulaVersion: 'chip-reference-v1', dataFreshness: 'current',
        largeHolderTrend: { ...indicator, ...metadata }, directorSupervisor12m: indicator, shareholderCountTrend: indicator, sourceRefs: [], availableAt: null,
      },
    }]
    expect(() => validateRelease(release)).toThrow('發布快照格式錯誤')
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


function releaseWithGrowthValue(value: unknown) {
  const stock = validGrowthStock()
  return {
    ...validRelease(),
    funnel: {
      ...validRelease().funnel, growthCoverageVersion: 'growth-coverage-v1', growthEvaluationState: 'not_evaluable',
      growthInputComplete: 0, growthValuationComplete: 0, growthThresholdCandidates: 0,
      growthHealthCandidates: 0, growthCandidates: 0, growthMissingReasons: [],
      universe: 1, instrumentExcluded: 0, strategyCandidates: { trust: 0, growth: 0, lowPosition: 0 },
      growthTerminalOutcomes: { universe: 1, missing: 1, knownInvalid: 0, extreme: 0, belowThreshold: 0, healthBlocked: 0, selected: 0 },
    },
    stocks: [{ ...stock, healthCategories: stock.healthCategories.map(category => ({
      ...category, checks: category.checks.map((check, index) => index === 0 ? { ...check, value } : check),
    })) }],
  }
}

describe('published growth health evidence', () => {
  it.each([0, -0.25, null, [0.04, 0.03, 0.06], '—'].map(value => ({ value })))('accepts a producer numeric, three-month or unavailable health value: $value', ({ value }) => {
    const release = releaseWithGrowthValue(value)
    expect(validateRelease(release)).toBe(release)
  })

  it.each([undefined, true, {}, Number.NaN, Number.POSITIVE_INFINITY, [], [0.1], [0.1, 0.2], [0.1, 'bad', 0.2], [0.1, null, 0.2], [[0.1], 0.2, 0.3], [0.1, 0.2, Number.NaN], [0, 1, 2, 3]].map(value => ({ value })))('rejects malformed health evidence rather than relaxing the release boundary: $value', ({ value }) => {
    expect(() => validateRelease(releaseWithGrowthValue(value))).toThrow('發布快照格式錯誤')
  })

  it('loads the published producer snapshot from the network instead of silently returning an older browser release', async () => {
    const body = JSON.stringify(publishedSnapshot)
    const published = JSON.parse(body)
    const key = 'taiwan-stock-research:last-valid-release:v1'
    const previous = window.localStorage.getItem(key)
    window.localStorage.setItem(key, JSON.stringify(validRelease()))
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, text: async () => body })))
    try {
      expect(validateRelease(published)).toBe(published)
      const loaded = await loadLatestRelease()
      expect(loaded.source).toBe('network')
      expect(loaded.release.marketDate).toBe(published.marketDate)
      expect(loaded.release.runId).toBe(published.runId)
      expect(JSON.parse(window.localStorage.getItem(key)!).runId).toBe(published.runId)
    } finally {
      vi.unstubAllGlobals()
      if (previous === null) window.localStorage.removeItem(key)
      else window.localStorage.setItem(key, previous)
    }
  })
})
