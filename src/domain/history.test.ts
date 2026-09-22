import { describe, expect, it } from 'vitest'
import { normalizeHistoryQuery, filterHistoryRows, defaultHistoryRange, validateHistoryIndex, validateHistoryMonth } from './history'

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
})

describe('history schemas', () => {
  it('fails closed for malformed index and month', () => {
    expect(() => validateHistoryIndex({ schemaVersion: 'wrong' })).toThrow()
    expect(() => validateHistoryMonth({ schemaVersion: 'screening-history-month-v1', month: '2026-09', records: [] })).not.toThrow()
  })
})
