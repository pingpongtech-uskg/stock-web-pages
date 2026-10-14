import { describe, expect, it } from 'vitest'
import { normalizeHistoryQuery, patchHistoryQuery, filterHistoryRows, defaultHistoryRange, validateHistoryIndex, validateHistoryMonth, loadHistoryMonth, historyGrowthCoverageSummary } from './history'

describe('history query', () => {
  it('normalizes dates, full-width digits, strategy, and clamps range', () => {
    const index = { earliestMarketDate: '2025-09-22', latestMarketDate: '2026-09-22' }
    expect(normalizeHistoryQuery(new URLSearchParams('view=history&strategy=nope&from=２０２５-０１-０１&to=2027-01-01&code=%20２３８２%20'), index)).toMatchObject({ strategy: 'all', from: '2025-09-22', to: '2026-09-22', code: '2382', clamped: true })
  })
  it('defaults to the latest thirty available market dates', () => {
    const dates = Array.from({ length: 35 }, (_, i) => `2026-09-${String(i + 1).padStart(2, '0')}`)
    expect(defaultHistoryRange(dates)).toEqual({ from: dates[5], to: dates[34] })
  })
  it('rejects reversed ranges without requesting data and filters prefix/name', () => {
    const q = normalizeHistoryQuery(new URLSearchParams('from=2026-09-20&to=2026-09-01'), { earliestMarketDate: '2026-01-01', latestMarketDate: '2026-09-30' })
    expect(q.invalidRange).toBe(true)
    expect(filterHistoryRows([{ rank: 1, code: '2382', name: '廣達', sector: '', value: null, valueLabel: '', status: 'pass', reason: '' }], '238')).toHaveLength(1)
    expect(filterHistoryRows([{ rank: 1, code: '2382', name: '廣達', sector: '', value: null, valueLabel: '', status: 'pass', reason: '' }], '廣')).toHaveLength(1)
  })

  it('normalizes interactive date changes against both archive bounds', () => {
    const bounds = { earliestMarketDate: '2026-09-08', latestMarketDate: '2026-10-13' }
    const current = normalizeHistoryQuery(new URLSearchParams('strategy=lowPosition&from=2026-09-08&to=2026-10-13&code=2382'), bounds)

    expect(patchHistoryQuery(current, { from: '2026-10-21' }, bounds)).toMatchObject({
      from: '2026-10-13', to: '2026-10-13', clamped: true, invalidRange: false,
    })
    expect(patchHistoryQuery(current, { to: '2026-09-01' }, bounds)).toMatchObject({
      from: '2026-09-08', to: '2026-09-08', clamped: true, invalidRange: false,
    })
    const previouslyClamped = normalizeHistoryQuery(new URLSearchParams('from=2026-10-21&to=2026-10-13'), bounds)
    expect(patchHistoryQuery(previouslyClamped, { code: '2382' }, bounds).clamped).toBe(true)
    expect(patchHistoryQuery(previouslyClamped, { from: '2026-10-12' }, bounds).clamped).toBe(false)
  })

  it('recomputes invalidRange after a user reverses the date range', () => {
    const bounds = { earliestMarketDate: '2026-09-08', latestMarketDate: '2026-10-13' }
    const current = normalizeHistoryQuery(new URLSearchParams('from=2026-09-08&to=2026-10-13'), bounds)

    expect(patchHistoryQuery(current, { from: '2026-10-12' }, bounds)).toMatchObject({
      from: '2026-10-12', to: '2026-10-13', clamped: false, invalidRange: false,
    })
    expect(patchHistoryQuery(current, { to: '2026-09-12' }, bounds)).toMatchObject({
      from: '2026-09-08', to: '2026-09-12', clamped: false, invalidRange: false,
    })
    const reversed = patchHistoryQuery(current, { from: '2026-10-14' }, bounds)
    expect(reversed).toMatchObject({ from: '2026-10-13', to: '2026-10-13', clamped: true, invalidRange: false })
    expect(patchHistoryQuery(current, { to: '2026-10-01' }, bounds)).toMatchObject({
      from: '2026-09-08', to: '2026-10-01', clamped: false, invalidRange: false,
    })
    const invalid = patchHistoryQuery(current, { from: '2026-10-13', to: '2026-09-12' }, bounds)
    expect(invalid.invalidRange).toBe(true)
  })
})

describe('history schemas', () => {
  it('fails closed for malformed index and month', () => {
    expect(() => validateHistoryIndex({ schemaVersion: 'wrong' })).toThrow()
    expect(() => validateHistoryMonth({ schemaVersion: 'screening-history-month-v1', month: '2026-09', records: [] })).not.toThrow()
  })

  it('keeps legacy history coverage unavailable and shows the typed new coverage projection', () => {
    const terminalOutcomes = { universe: 2, missing: 1, knownInvalid: 0, extreme: 0, belowThreshold: 0, healthBlocked: 0, selected: 1 }
    const record = {
      marketDate: '2050-04-01', generatedAt: '2050-04-01T01:00:00Z', runId: 'history-v1', revision: 'r1',
      freshness: 'current', statusMessage: '', formulaVersions: {}, funnel: {}, strategies: { trust: [], growth: [], lowPosition: [] },
      legacy: false,
      growthCoverage: {
        version: 'growth-coverage-v1' as const, evaluationState: 'partial' as const, inputComplete: 1,
        valuationComplete: 1, thresholdCandidates: 1, healthCandidates: 1, candidates: 1,
        missingReasons: [{ reason: 'dividendYield', count: 1 }], terminalOutcomes,
      },
    }
    expect(validateHistoryMonth({ schemaVersion: 'screening-history-month-v1', month: '2050-04', records: [record] })).toMatchObject({ records: [{ growthCoverage: record.growthCoverage }] })
    expect(historyGrowthCoverageSummary(record)).toContain('可計算 1 檔')
    expect(historyGrowthCoverageSummary(record)).toContain('缺少輸入 1')

    const legacy = { ...record, legacy: true, growthCoverage: undefined }
    expect(historyGrowthCoverageSummary(legacy)).toContain('舊版歷史發布未提供成長覆蓋診斷')

    expect(() => validateHistoryMonth({
      schemaVersion: 'screening-history-month-v1', month: '2050-04',
      records: [{ ...legacy, legacy: false }],
    })).toThrow('歷史資料格式錯誤')
  })

  it('keys month requests by content path and retries after a failed request', async () => {
    const originalFetch = globalThis.fetch
    const month = (path: string) => ({ schemaVersion: 'screening-history-month-v1', month: '2040-01', records: [{ marketDate: '2040-01-02', runId: path, revision: 'v1', strategies: {} }] })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => month('/archive/first.json') })
      .mockResolvedValueOnce({ ok: true, json: async () => month('/archive/second.json') })
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ ok: true, json: async () => month('/archive/retry.json') })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    await expect(loadHistoryMonth({ month: '2040-01', path: '/archive/first.json' })).resolves.toMatchObject({ records: [{ runId: '/archive/first.json' }] })
    await expect(loadHistoryMonth({ month: '2040-01', path: '/archive/second.json' })).resolves.toMatchObject({ records: [{ runId: '/archive/second.json' }] })
    await expect(loadHistoryMonth({ month: '2040-01', path: '/archive/retry.json' })).rejects.toThrow('offline')
    await expect(loadHistoryMonth({ month: '2040-01', path: '/archive/retry.json' })).resolves.toMatchObject({ records: [{ runId: '/archive/retry.json' }] })
    expect(fetchMock).toHaveBeenCalledTimes(4)
    globalThis.fetch = originalFetch
  })
})
