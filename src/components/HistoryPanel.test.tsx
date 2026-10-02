import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { HistoryPanel } from './HistoryPanel'

describe('HistoryPanel', () => {
  it('renders accessible filters and neutral valuation labels', () => {
    const html = renderToStaticMarkup(<HistoryPanel index={null} />)
    expect(html).toContain('歷史篩選')
    expect(html).toContain('aria-label="選擇歷史起始交易日"')
    expect(html).toContain('aria-label="選擇歷史結束交易日"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain('正在載入歷史資料')
  })

  it('shows a recoverable fetch error and renders history after retry succeeds', async () => {
    const originalFetch = globalThis.fetch
    const originalUrl = window.location.href
    const monthPath = '/archive/history-panel-retry.json'
    const record = {
      marketDate: '2050-04-01', generatedAt: '2050-04-01T01:00:00Z', runId: 'retry-run', revision: 'r1',
      freshness: 'current', statusMessage: 'ok', formulaVersions: { regression: 'r', valuation: 'v', growthValuation: 'g', growthFallback: 'gf', ranking: 'rank-v1' },
      funnel: {}, strategies: { trust: [{ rank: 1, code: '2330', name: '台積電', sector: '電子', value: null, valueLabel: '', status: 'unknown', reason: '測試資料' }], growth: [], lowPosition: [] }, sourceRefs: [],
    }
    const index = {
      schemaVersion: 'screening-history-index-v1', generatedAt: '2050-04-01T01:00:00Z', retentionDays: 365,
      earliestMarketDate: '2050-04-01', latestMarketDate: '2050-04-01',
      months: [{ month: '2050-04', path: monthPath, sha256: 'abc', bytes: 1, marketDateStart: '2050-04-01', marketDateEnd: '2050-04-01', marketDates: ['2050-04-01'], recordCount: 1 }],
    }
    let monthFetchCount = 0
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/index.json')) return { ok: true, json: async () => index } as Response
      monthFetchCount += 1
      if (monthFetchCount === 1) throw new Error('offline')
      return { ok: true, json: async () => ({ schemaVersion: 'screening-history-month-v1', month: '2050-04', records: [record] }) } as Response
    }) as unknown as typeof fetch
    window.history.replaceState({}, '', '/?view=history')
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    try {
      await act(async () => { root.render(<HistoryPanel />) })
      await vi.waitFor(() => expect(host.textContent).toContain('歷史資料暫不可用'))
      const retry = Array.from(host.querySelectorAll('button')).find((button) => button.textContent === '重試')
      expect(retry).toBeTruthy()
      await act(async () => { retry?.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
      await vi.waitFor(() => expect(host.textContent).toContain('2330 台積電'))
      expect(monthFetchCount).toBe(2)
    } finally {
      await act(async () => root.unmount())
      host.remove()
      globalThis.fetch = originalFetch
      window.history.replaceState({}, '', new URL(originalUrl).pathname + new URL(originalUrl).search)
      sessionStorage.clear()
    }
  })
})
