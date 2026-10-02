import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { Coverage, RankingRow, Release, StockSummary } from './domain/types'
import { AppForTest, CoverageFunnelView, dashboardStrategyRows, GrowthStockDiagnosticsView } from './App'

const row: RankingRow = {
  rank: 1,
  code: '2330',
  name: '台積電',
  sector: '半導體業',
  value: 4.23,
  valueLabel: '%',
  status: 'pass',
  reason: '測試理由',
  currentPrice: 1000,
  fairPrice: 1450,
  valuePrice075: 1087.5,
  valuePrice066: 957,
  currentPeg: 0.52,
  pegBand: 'strict',
  valuationMethod: 'zulu-peg',
}

const coverage: Coverage = {
  universeCount: 100, databaseCount: 80, candidateCount: 5, pendingCount: 20,
  financialCompleteCount: 24, priceCompleteCount: 75, completenessPct: 75,
  finmindRequests: null, queueStatus: '補抓中',
}

function appRelease(): Release {
  return {
    schemaVersion: '1.0', strategyVersion: 'strategy-v1', formulaVersion: 'formula-v1',
    runId: 'app-flow-run', marketDate: '2026-10-02', generatedAt: '2026-10-02T10:00:00Z',
    nextExpectedUpdateAt: '2026-10-03T10:00:00Z', freshness: 'current', statusMessage: '', sourceRefs: [],
    coverage: { universeCount: 1, databaseCount: 1, candidateCount: 1, pendingCount: 0, financialCompleteCount: 1, priceCompleteCount: 1, completenessPct: 100, finmindRequests: null, queueStatus: 'ok' },
    funnel: { version: 'funnel-v1', universe: 1, priceComplete: 1, valuationComplete: 0, pegCandidates: 0, strategyCandidates: { trust: 0, growth: 0, lowPosition: 0 }, formalValuations: 0, proxyValuations: 0, instrumentExcluded: 0, instrumentPolicy: 'eligible only' },
    summary: { watchCount: 0, lowPositionCount: 0, candidateRouteCounts: { trust: 0, growth: 0, lowPosition: 0 }, addedToday: 0, improvedToday: 0, removedToday: 0 },
    stocks: [], rankings: { trust: [], growth: [], lowPosition: [], lowBase: [], lowBaseGrowth: [], lowBaseQuality: [] },
    research: { status: 'not_evaluable', reason: 'test', cagr: null, maxDrawdown: null, periods: [] },
  }
}

describe('dashboardStrategyRows', () => {
  it('maps the three tabs to their published ranking arrays', () => {
    const rankings: Release['rankings'] = {
      trust: [row],
      growth: [],
      lowPosition: [],
      lowBase: [],
      lowBaseGrowth: [],
      lowBaseQuality: [],
    }

    const blocks = dashboardStrategyRows({ rankings })

    expect(blocks.map((block) => block.presentation.key)).toEqual([
      'trust',
      'growth',
      'lowPosition',
    ])
    expect(blocks[0].rows).toBe(rankings.trust)
    expect(blocks[1].rows).toBe(rankings.growth)
    expect(blocks[2].rows).toBe(rankings.lowPosition)
  })
})

describe('growth coverage UI', () => {
  it('separates complete inputs from zero qualifying candidates and names missing inputs', () => {
    const markup = renderToStaticMarkup(<CoverageFunnelView strategy="growth" funnel={{
      universe: 100, priceComplete: 0, valuationComplete: 0,
      growthEvaluationState: 'partial', growthInputComplete: 12,
      growthValuationComplete: 8, growthThresholdCandidates: 0, growthHealthCandidates: 0,
      growthMissingReasons: [{ reason: 'dividendYield', count: 20 }],
      growthTerminalOutcomes: { universe: 90, missing: 70, knownInvalid: 10, extreme: 2, belowThreshold: 8, healthBlocked: 0, selected: 0 },
      pegCandidates: 0,
      strategyCandidates: 0, formalValuations: 0, proxyValuations: 0,
    }} coverage={coverage} />)
    expect(markup).toContain('估值輸入完整')
    expect(markup).toContain('<strong>12</strong>')
    expect(markup).toContain('已計算 8 檔，總報酬本益比 ≥ 1.20 為 0 檔')
    expect(markup).toContain('已確認股利 20 檔')
    expect(markup).toContain('成長健康 ≥ 4/5')
    expect(markup).toContain('追蹤行情完整度 <strong>75.0%</strong>')
    expect(markup).toContain('資料庫財務品質檢查通過率 <strong>30.0%</strong>')
    expect(markup).toContain('成長估值輸入建置 <strong>13.3%</strong>')
  })

  it('does not present absent legacy input coverage as zero', () => {
    const markup = renderToStaticMarkup(<CoverageFunnelView strategy="growth" funnel={{
      universe: 100, priceComplete: 10, valuationComplete: 4, growthInputComplete: null,
      growthValuationComplete: null, growthThresholdCandidates: null, growthHealthCandidates: null,
      growthMissingReasons: null, growthEvaluationState: null, growthTerminalOutcomes: null,
      pegCandidates: 2, strategyCandidates: 1, formalValuations: 0, proxyValuations: 4,
    }} coverage={coverage} />)
    expect(markup).toContain('此舊版發布未提供成長覆蓋診斷')
  })

  it('does not describe missing all inputs as a fully evaluated zero-result strategy', () => {
    const markup = renderToStaticMarkup(<CoverageFunnelView strategy="growth" funnel={{
      universe: 100, priceComplete: 10, valuationComplete: 4, growthInputComplete: 0,
      growthEvaluationState: 'not_evaluable',
      growthValuationComplete: 0, growthThresholdCandidates: 0, growthHealthCandidates: 0,
      growthMissingReasons: [{ reason: 'dividendYield', count: 100 }],
      growthTerminalOutcomes: { universe: 100, missing: 100, knownInvalid: 0, extreme: 0, belowThreshold: 0, healthBlocked: 0, selected: 0 }, pegCandidates: 2,
      strategyCandidates: 0, formalValuations: 0, proxyValuations: 4,
    }} coverage={coverage} />)
    expect(markup).toContain('成長估值尚不可評估')
    expect(markup).toContain('目前沒有可計算估值不代表條件未達')
    expect(markup).not.toContain('已計算 0 檔，但總報酬本益比門檻合格 0 檔')
    expect(markup).toContain('已確認股利 100 檔')
  })

  it('labels a legacy partial funnel as unavailable instead of reusing zeroes', () => {
    const markup = renderToStaticMarkup(<CoverageFunnelView strategy="growth" funnel={{
      universe: 100, priceComplete: 75, valuationComplete: 20, growthInputComplete: 0,
      growthValuationComplete: 0, growthThresholdCandidates: 0, growthHealthCandidates: 0,
      growthMissingReasons: [], growthEvaluationState: null, growthTerminalOutcomes: null,
      pegCandidates: 5, strategyCandidates: 0, formalValuations: 4, proxyValuations: 16,
    }} coverage={coverage} />)
    expect(markup).toContain('此舊版發布未提供成長覆蓋診斷')
    expect(markup).toContain('成長估值輸入建置')
    expect(markup).toContain('(未提供診斷)')
    expect(markup).not.toContain('成長估值輸入完整 0 檔')
  })

  it('renders stock-level evaluation reason, health outcome, and source provenance', () => {
    const stock = {
      code: '2330', name: '台積電', growthHealthEligible: false,
      growthValuation: {
        status: 'unavailable', reason: '缺少完整年度股利', inputsComplete: false,
        missingReasons: ['dividendYield'],
        inputAudit: {
          price: { origin: 'reported', sourcePeriod: '2026-10-01', method: 'same_day_close', source: 'TWSE' },
          ttmEps: { origin: 'unavailable', sourcePeriod: null, method: null, source: null, reason: 'nonconsecutive_quarters' },
        },
      },
      healthCategories: [{ key: 'growth', label: '成長', passCount: 3, total: 5, threshold: 4, status: 'fail', checks: [] }],
    } as unknown as StockSummary
    const markup = renderToStaticMarkup(<GrowthStockDiagnosticsView stocks={[stock]} />)
    expect(markup).toContain('台積電 (2330)')
    expect(markup).toContain('缺少完整年度股利')
    expect(markup).toContain('健康條件未達')
    expect(markup).toContain('價格：來源報告 · 2026-10-01 · TWSE')
    expect(markup).toContain('季度不連續')
  })

  it('keeps trust Top10 newcomers visible when the PEG pool is empty', () => {
    const markup = renderToStaticMarkup(<CoverageFunnelView strategy="trust" funnel={{
      universe: 100, priceComplete: 100, valuationComplete: 0, growthInputComplete: null,
      growthValuationComplete: null, growthThresholdCandidates: null, growthHealthCandidates: null,
      growthMissingReasons: null, growthEvaluationState: null, growthTerminalOutcomes: null,
      pegCandidates: 0, strategyCandidates: 3, formalValuations: 0, proxyValuations: 0,
    }} coverage={coverage} trustSignalCount={3} trustNewEntryCount={3} />)
    expect(markup).toContain('官方十日買超 Top10 新進榜')
    expect(markup).toContain('投信新進榜候選')
    expect(markup).toContain('<strong>3</strong>')
    expect(markup).toContain('PEG 低於 0.75 0 檔')
    expect(markup).not.toContain('<small>PEG <')
  })

  it('keeps low-position price observations separate from financial and PEG evidence', () => {
    const markup = renderToStaticMarkup(<CoverageFunnelView strategy="lowPosition" funnel={{
      universe: 100, priceComplete: 75, valuationComplete: 0, growthInputComplete: null,
      growthValuationComplete: null, growthThresholdCandidates: null, growthHealthCandidates: null,
      growthMissingReasons: null, growthEvaluationState: null, growthTerminalOutcomes: null,
      pegCandidates: 0, strategyCandidates: 4, formalValuations: 0, proxyValuations: 0,
    }} coverage={coverage} />)
    expect(markup).toContain('同日行情可用')
    expect(markup).toContain('3.5 年價格觀察候選')
    expect(markup).toContain('健康與估值資料是旁證，不隱藏價格觀察')
    expect(markup).toContain('PEG 低於 0.75 0 檔')
  })
})

describe('dashboard freshness clock', () => {
  it('updates freshness in the mounted app after the published deadline', async () => {
    const start = Date.parse('2026-10-01T12:00:00Z')
    const appRelease = {
      schemaVersion: '1.0', strategyVersion: 'strategy-v1', formulaVersion: 'formula-v1',
      runId: 'clock-run', marketDate: '2026-10-01', generatedAt: new Date(start).toISOString(),
      nextExpectedUpdateAt: new Date(start + 60_000).toISOString(), freshness: 'degraded', statusMessage: '離線重算', sourceRefs: [],
      coverage: { universeCount: 1, databaseCount: 1, candidateCount: 0, pendingCount: 0, financialCompleteCount: 0, priceCompleteCount: 1, completenessPct: 100, queueStatus: 'ok' },
      funnel: { version: 'v1', universe: 1, priceComplete: 1, valuationComplete: 0, pegCandidates: 0, strategyCandidates: { trust: 0, growth: 0, lowPosition: 0 }, formalValuations: 0, proxyValuations: 0, instrumentExcluded: 0, instrumentPolicy: 'eligible only' },
      summary: { watchCount: 0, lowPositionCount: 0, candidateRouteCounts: { trust: 0, growth: 0, lowPosition: 0 }, addedToday: 0, improvedToday: 0, removedToday: 0 },
      stocks: [], rankings: { trust: [], growth: [], lowPosition: [], lowBase: [], lowBaseGrowth: [], lowBaseQuality: [] },
      research: { status: 'not_evaluable', reason: 'test', cagr: null, maxDrawdown: null, periods: [] },
    }
    const previousFetch = globalThis.fetch
    const previousActEnvironment = (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    vi.useFakeTimers()
    vi.setSystemTime(start)
    localStorage.clear()
    globalThis.fetch = vi.fn(async () => ({ ok: true, text: async () => JSON.stringify(appRelease), json: async () => appRelease }) as Response)
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    try {
      await act(async () => { root.render(<AppForTest />) })
      await vi.waitFor(() => expect(host.textContent).toContain('新鮮度：正常'))
      expect(host.textContent).toContain('新鮮度：正常')
      expect(host.textContent).toContain('資料品質：降級發布')
      await act(async () => { vi.advanceTimersByTime(60_001) })
      expect(host.textContent).toContain('新鮮度：逾期')
      expect(host.textContent).toContain('資料品質：降級發布')
    } finally {
      await act(async () => root.unmount())
      host.remove()
      localStorage.clear()
      globalThis.fetch = previousFetch
      ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = previousActEnvironment
      vi.useRealTimers()
    }
  })
})

describe('history navigation integration', () => {
  it('opens history and returns to latest while preserving the selected history filter', async () => {
    const previousFetch = globalThis.fetch
    const previousUrl = window.location.href
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    const release = appRelease()
    const month = {
      schemaVersion: 'screening-history-month-v1', month: '2026-10', records: [{
        marketDate: '2026-10-02', generatedAt: release.generatedAt, runId: release.runId, revision: 'rev1',
        freshness: 'current', statusMessage: '', formulaVersions: { ranking: 'ranking-v1' }, funnel: {},
        strategies: { trust: [], growth: [], lowPosition: [{ rank: 1, code: '2330', name: '台積電', sector: '', value: null, valueLabel: '', status: 'pass', reason: 'price observation' }] },
      }],
    }
    globalThis.fetch = vi.fn(async (input) => {
      const url = String(input)
      if (url.endsWith('/latest.json')) return { ok: true, text: async () => JSON.stringify(release) } as Response
      if (url.endsWith('/publication.json')) return { ok: false, status: 404 } as Response
      if (url.endsWith('/index.json')) return { ok: true, json: async () => ({
        schemaVersion: 'screening-history-index-v1', generatedAt: release.generatedAt, retentionDays: 365,
        earliestMarketDate: '2026-10-02', latestMarketDate: '2026-10-02',
        months: [{ month: '2026-10', path: '/data/archive/rev1.json', sha256: 'a'.repeat(64), bytes: 1, marketDateStart: '2026-10-02', marketDateEnd: '2026-10-02', marketDates: ['2026-10-02'], recordCount: 1 }],
      }) } as Response
      return { ok: true, json: async () => month } as Response
    }) as unknown as typeof fetch
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    try {
      await act(async () => { root.render(<AppForTest />) })
      await vi.waitFor(() => expect(host.textContent).toContain('台股三策略選股'))
      await act(async () => { (host.querySelector('.history-nav-button') as HTMLButtonElement).click() })
      await vi.waitFor(() => expect(host.textContent).toContain('台積電'))
      expect(window.location.search).toContain('view=history')

      const codeInput = host.querySelector('.history-filters input') as HTMLInputElement
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(codeInput), 'value')?.set
        setter?.call(codeInput, '2330')
        codeInput.dispatchEvent(new Event('input', { bubbles: true }))
      })
      await vi.waitFor(() => expect(window.location.search).toContain('code=2330'))
      await act(async () => { (host.querySelector('.history-nav-button') as HTMLButtonElement).click() })
      expect(window.location.search).toContain('code=2330')
      expect(window.location.search).not.toContain('view=history')
      expect(host.querySelector('.history-panel')).toBeNull()

      await act(async () => { (host.querySelector('.history-nav-button') as HTMLButtonElement).click() })
      await vi.waitFor(() => expect(host.textContent).toContain('歷史篩選'))
      expect(window.location.search).toContain('code=2330')
      expect((host.querySelector('.history-filters input') as HTMLInputElement).value).toBe('2330')
    } finally {
      await act(async () => root.unmount())
      host.remove()
      globalThis.fetch = previousFetch
      window.history.replaceState({}, '', new URL(previousUrl).pathname + new URL(previousUrl).search)
    }
  })
})

describe('dashboard recovery', () => {
  it('shows a retryable error when no release is available and recovers after retry', async () => {
    const previousFetch = globalThis.fetch
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    const latest = vi.fn()
    localStorage.clear()
    globalThis.fetch = vi.fn(async (input) => {
      const url = String(input)
      if (url.endsWith('/latest.json')) {
        latest()
        if (latest.mock.calls.length === 1) throw new Error('network unavailable')
        return { ok: true, text: async () => JSON.stringify(appRelease()) } as Response
      }
      return { ok: false, status: 404 } as Response
    }) as unknown as typeof fetch
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    try {
      await act(async () => { root.render(<AppForTest />) })
      await vi.waitFor(() => expect(host.textContent).toContain('目前沒有可用的發布快照'))
      expect(host.textContent).toContain('network unavailable')
      await act(async () => { (host.querySelector('.retry-button') as HTMLButtonElement).click() })
      await vi.waitFor(() => expect(host.textContent).toContain('台股三策略選股'))
      expect(latest).toHaveBeenCalledTimes(2)
    } finally {
      await act(async () => root.unmount())
      host.remove()
      globalThis.fetch = previousFetch
      localStorage.clear()
    }
  })
})
