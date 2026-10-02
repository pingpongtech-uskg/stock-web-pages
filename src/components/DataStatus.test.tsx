import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import type { Release } from '../domain/types'
import { DataStatus, getEffectiveFreshness } from './DataStatus'

const release = {
  schemaVersion: '1.0', strategyVersion: 'strategy-v1', formulaVersion: 'formula-v1',
  runId: 'run-1', marketDate: '2026-09-11', generatedAt: '2026-09-18T00:00:00Z',
  nextExpectedUpdateAt: '2026-09-13T00:00:00Z', freshness: 'current', statusMessage: '資料正常', sourceRefs: [],
  coverage: { universeCount: 100, databaseCount: 100, candidateCount: 2, pendingCount: 0, financialCompleteCount: 0, priceCompleteCount: 7, completenessPct: 7, finmindRequests: null, queueStatus: 'ok' },
  summary: { watchCount: 0, lowPositionCount: 0, candidateRouteCounts: { trust: 2, growth: 2, lowPosition: 2 }, addedToday: 0, improvedToday: 0, removedToday: 0 },
  stocks: [], rankings: { trust: [], growth: [], lowPosition: [], lowBase: [], lowBaseGrowth: [], lowBaseQuality: [] },
  research: { status: 'not_evaluable', reason: 'test', cagr: null, maxDrawdown: null, periods: [] },
} as unknown as Release

describe('DataStatus freshness', () => {
  it('downgrades producer-current data after its expected update time', () => {
    expect(getEffectiveFreshness(release, Date.parse('2026-09-18T00:00:00Z'))).toBe('stale')
    const markup = renderToStaticMarkup(<DataStatus release={release} />)
    expect(markup).toContain('新鮮度：逾期')
    expect(markup).toContain('資料品質：正常')
    expect(markup).toContain('逾期')
    expect(markup).toContain('追蹤行情完整度 7.0%')
  })

  it('keeps the degraded label and still shows how overdue the data is', () => {
    const degraded = {
      ...release,
      freshness: 'degraded',
      statusMessage: '離線重算 100 檔；沿用已發布的調整價與財務代理。',
    } as unknown as Release
    const now = Date.parse('2026-09-18T12:00:00Z')

    const markup = renderToStaticMarkup(<DataStatus release={degraded} now={now} />)

    expect(markup).toContain('降級發布')
    expect(markup).toContain('離線重算 100 檔')
    expect(markup).toContain('逾期約 132 小時')
    expect(markup).toContain('資料品質：降級發布')
    expect(markup).toContain('新鮮度：逾期')
  })

  it('labels browser cache separately from freshness and release quality', () => {
    const markup = renderToStaticMarkup(<DataStatus release={release} source="cache" now={Date.parse('2026-09-12T00:00:00Z')} />)
    expect(markup).toContain('瀏覽器快取')
    expect(markup).toContain('新鮮度：正常')
    expect(markup).toContain('資料品質：正常')
    expect(markup).toContain('更新 UTC+8')
  })

  it('updates overdue freshness at deadline without a prop change while keeping degraded quality separate', async () => {
    const start = Date.parse('2026-10-01T12:00:00Z')
    const deadline = start + 60_000
    const degraded = { ...release, freshness: 'degraded', nextExpectedUpdateAt: new Date(deadline).toISOString() } as unknown as Release
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    const previousActEnvironment = (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT
    vi.useFakeTimers()
    vi.setSystemTime(start)
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    try {
      await act(async () => { root.render(<DataStatus release={degraded} />) })
      expect(host.textContent).toContain('新鮮度：正常')
      expect(host.textContent).toContain('資料品質：降級發布')
      await act(async () => { vi.advanceTimersByTime(60_001) })
      expect(host.textContent).toContain('新鮮度：逾期')
      expect(host.textContent).toContain('資料品質：降級發布')
    } finally {
      await act(async () => root.unmount())
      host.remove()
      ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = previousActEnvironment
      vi.useRealTimers()
    }
  })

  it('keeps an explicitly injected now value deterministic', async () => {
    const start = Date.parse('2026-10-01T12:00:00Z')
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    const previousActEnvironment = (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT
    vi.useFakeTimers()
    vi.setSystemTime(start)
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    try {
      await act(async () => { root.render(<DataStatus release={{ ...release, nextExpectedUpdateAt: new Date(start + 1).toISOString() } as Release} now={start} />) })
      expect(host.textContent).toContain('新鮮度：正常')
      await act(async () => { vi.advanceTimersByTime(60_000) })
      expect(host.textContent).toContain('新鮮度：正常')
    } finally {
      await act(async () => root.unmount())
      host.remove()
      ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = previousActEnvironment
      vi.useRealTimers()
    }
  })
})
