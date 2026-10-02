import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HistoryPanel } from './HistoryPanel'

function historyIndex(revision: string) {
  return {
    schemaVersion: 'screening-history-index-v1', generatedAt: '2026-10-03T00:00:00Z', retentionDays: 365,
    earliestMarketDate: '2026-10-02', latestMarketDate: '2026-10-02',
    months: [{ month: '2026-10', path: `/data/archive/${revision}.json`, sha256: revision.repeat(64), bytes: 1,
      marketDateStart: '2026-10-02', marketDateEnd: '2026-10-02', marketDates: ['2026-10-02'], recordCount: 1 }],
  }
}

function historyMonth(revision: string, name: string) {
  return {
    schemaVersion: 'screening-history-month-v1', month: '2026-10', records: [{
      marketDate: '2026-10-02', generatedAt: '2026-10-02T10:00:00Z', runId: 'same-run', revision,
      freshness: 'current', statusMessage: '', formulaVersions: { ranking: 'ranking-v1' }, funnel: {},
      strategies: { trust: [], growth: [], lowPosition: [{ rank: 1, code: '2330', name, sector: '', value: null, valueLabel: '', status: 'pass', reason: 'adjusted-price-slope' }] },
    }],
  }
}

describe('HistoryPanel publication refresh', () => {
  afterEach(() => { window.history.replaceState({}, '', '/') })

  it('loads a same-date correction when publication identity changes and keeps the URL filters', async () => {
    const previousFetch = globalThis.fetch
    window.history.replaceState({}, '', '/?view=history&strategy=lowPosition&from=2026-10-02&to=2026-10-02&code=2330')
    const indexFetch = vi.fn()
    globalThis.fetch = vi.fn(async (input) => {
      const url = String(input)
      if (url.endsWith('/index.json')) {
        const revision = indexFetch.mock.calls.length === 0 ? 'r1' : 'r2'
        indexFetch()
        return { ok: true, json: async () => historyIndex(revision) } as Response
      }
      const revision = url.endsWith('/r1.json') ? 'r1' : 'r2'
      return { ok: true, json: async () => historyMonth(revision, revision === 'r1' ? '舊版名稱' : '更正後名稱') } as Response
    }) as unknown as typeof fetch
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    try {
      await act(async () => { root.render(<HistoryPanel refreshKey="same-run:a" />) })
      await vi.waitFor(() => expect(host.textContent).toContain('舊版名稱'))
      expect((host.querySelector('input') as HTMLInputElement | null)?.value).toBe('2330')
      expect(window.location.search).toContain('strategy=lowPosition')

      await act(async () => { root.render(<HistoryPanel refreshKey="same-run:b" />) })
      await vi.waitFor(() => expect(host.textContent).toContain('更正後名稱'))
      expect(host.textContent).not.toContain('舊版名稱')
      expect(window.location.search).toBe('?view=history&strategy=lowPosition&from=2026-10-02&to=2026-10-02&code=2330')
      expect(indexFetch).toHaveBeenCalledTimes(2)
    } finally {
      await act(async () => root.unmount())
      host.remove()
      globalThis.fetch = previousFetch
    }
  })
})
