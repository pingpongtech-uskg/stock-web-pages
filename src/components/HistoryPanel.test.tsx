import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HistoryPanel } from './HistoryPanel'

function historyIndex(revision: string) {
  return {
    schemaVersion: 'screening-history-index-v1' as const, generatedAt: '2026-10-03T00:00:00Z', retentionDays: 365,
    earliestMarketDate: '2026-10-02', latestMarketDate: '2026-10-03',
    months: [{ month: '2026-10', path: `/data/archive/${revision}.json`, sha256: revision.repeat(64), bytes: 1,
      marketDateStart: '2026-10-02', marketDateEnd: '2026-10-03', marketDates: ['2026-10-02', '2026-10-03'], recordCount: 2 }],
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

  it('does not rewrite the URL when browser Back leaves history view', async () => {
    window.history.replaceState({}, '', '/?view=history&strategy=lowPosition&from=2026-10-02&to=2026-10-03')
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    try {
      await act(async () => { root.render(<HistoryPanel index={historyIndex('interactive')} />) })
      window.history.pushState({}, '', '/?strategy=lowPosition')
      await act(async () => { window.dispatchEvent(new PopStateEvent('popstate')) })
      expect(window.location.search).toBe('?strategy=lowPosition')
    } finally {
      await act(async () => root.unmount())
      host.remove()
    }
  })

  it('keeps interactive date fields, URL, and invalid-range feedback in sync', async () => {
    const previousFetch = globalThis.fetch
    window.history.replaceState({}, '', '/?view=history&strategy=lowPosition&from=2026-10-02&to=2026-10-03&code=2330')
    globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => historyMonth('interactive', '台積電') }) as Response) as unknown as typeof fetch
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    const changeDate = (input: HTMLInputElement, value: string) => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(input, value)
      input.dispatchEvent(new Event('input', { bubbles: true }))
      input.dispatchEvent(new Event('change', { bubbles: true }))
    }

    try {
      await act(async () => { root.render(<HistoryPanel index={historyIndex('interactive')} />) })
      await vi.waitFor(() => expect(host.textContent).toContain('台積電'))

      const from = host.querySelector('[aria-label="選擇歷史起始交易日"]') as HTMLInputElement
      const to = host.querySelector('[aria-label="選擇歷史結束交易日"]') as HTMLInputElement
      await act(async () => { changeDate(from, '2026-10-03') })
      expect(window.location.search).toContain('from=2026-10-03')
      expect(from.min).toBe('2026-10-02')
      expect(from.max).toBe('2026-10-03')

      await act(async () => { changeDate(to, '2026-10-02') })
      expect(window.location.search).toContain('to=2026-10-02')
      expect(host.textContent).toContain('起始日不可晚於結束日')
      expect(from.getAttribute('aria-invalid')).toBe('true')
    } finally {
      await act(async () => root.unmount())
      host.remove()
      globalThis.fetch = previousFetch
    }
  })

  it('preserves the clamp notice while canonicalizing an out-of-range URL', async () => {
    const previousFetch = globalThis.fetch
    window.history.replaceState({}, '', '/?view=history&strategy=lowPosition&from=2026-10-04&to=2026-10-03&code=2330')
    globalThis.fetch = vi.fn(async (input) => {
      const url = String(input)
      if (url.endsWith('/index.json')) return { ok: true, json: async () => historyIndex('clamp') } as Response
      return { ok: true, json: async () => historyMonth('clamp', '台積電') } as Response
    }) as unknown as typeof fetch
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    try {
      await act(async () => { root.render(<HistoryPanel />) })
      await vi.waitFor(() => expect(host.textContent).toContain('已限制在可查詢期間'))
      expect(window.location.search).toContain('from=2026-10-03')
      expect(window.location.search).toContain('to=2026-10-03')
      expect(host.textContent).toContain('休市／沒有發布')
    } finally {
      await act(async () => root.unmount())
      host.remove()
      globalThis.fetch = previousFetch
    }
  })

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
