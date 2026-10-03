import { Component, createContext, useContext, useEffect, useState, Fragment, type ErrorInfo, type ReactNode } from 'react'

import { HistoryPanel } from './components/HistoryPanel'
import { MarketVolumeIndicator } from './components/MarketVolumeIndicator'
import { StrategyCard } from './components/StrategyCard'
import { DataStatus } from './components/DataStatus'
import { PublicationNotice } from './components/PublicationNotice'
import { loadLatestRelease, type LoadedRelease } from './data/api'
import { growthHealthOutcome, qualityStatusCounts, releaseCoverageFunnel, stockGrowthHealthOutcome, type CoverageFunnel } from './domain/coverage'
import { trackEvent, trackEventOnce } from './domain/events'
import type { Coverage, GrowthInputAudit, RankingRow, Release, StockSummary } from './domain/types'
import { strategyPresentations, type StrategyKey, type StrategyPresentation } from './domain/strategyPresentation'
import './styles.css'

interface DataContextValue {
  release: Release | null
  dataSource: LoadedRelease['source'] | null
  contentHash: string | null
  loading: boolean
  error: string | null
  reload: () => void
}

const DataContext = createContext<DataContextValue | null>(null)

function DataProvider({ children }: { children: ReactNode }) {
  const [release, setRelease] = useState<Release | null>(null)
  const [dataSource, setDataSource] = useState<LoadedRelease['source'] | null>(null)
  const [contentHash, setContentHash] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(release === null)
    setError(null)
    loadLatestRelease()
      .then((next) => {
        if (cancelled) return
        setRelease(next.release)
        setDataSource(next.source)
        setContentHash(next.contentHash)
        setLoading(false)
        trackEvent('release_load_success', { runId: next.release.runId, source: next.source })
      })
      .catch((reason: unknown) => {
        if (cancelled) return
        const message = reason instanceof Error ? reason.message : '無法讀取發布快照'
        trackEvent(
          message.includes('發布快照格式錯誤') ? 'release_schema_rejected' : 'release_load_error',
          { message },
        )
        setError(message)
        setLoading(false)
      })
    return () => { cancelled = true }
  }, [reloadKey])

  return (
    <DataContext.Provider value={{ release, dataSource, contentHash, loading, error, reload: () => setReloadKey((value) => value + 1) }}>
      {children}
    </DataContext.Provider>
  )
}

function useData() {
  const value = useContext(DataContext)
  if (!value) throw new Error('useData must be used inside DataProvider')
  return value
}

export interface DashboardStrategyBlock {
  presentation: StrategyPresentation
  rows: RankingRow[]
}

export function dashboardStrategyRows(release: Pick<Release, 'rankings'>): DashboardStrategyBlock[] {
  return strategyPresentations.map((presentation) => ({
    presentation,
    rows: release.rankings[presentation.key],
  }))
}

export default function App() {
  return (
    <ErrorBoundary>
      <DataProvider>
        <Dashboard />
      </DataProvider>
    </ErrorBoundary>
  )
}

/**
 * Last-resort boundary: a runtime crash anywhere below must surface as a
 * visible, retryable panel — never an empty white React root.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, { message: string | null }> {
  state: { message: string | null } = { message: null }

  static getDerivedStateFromError(error: unknown): { message: string } {
    return { message: error instanceof Error ? error.message : '畫面發生未預期錯誤' }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('dashboard error boundary:', error, info.componentStack)
  }

  render() {
    if (this.state.message !== null) return <FatalScreen message={this.state.message} />
    return this.props.children
  }
}

function FatalScreen({ message }: { message: string }) {
  return (
    <div className="state-shell">
      <section className="state-panel error-panel" role="alert">
        <p className="site-kicker">DATA / UNAVAILABLE</p>
        <h1>畫面發生未預期錯誤</h1>
        <p>{message}</p>
        <p className="state-help">已停止渲染，避免顯示不完整或不正確的資料。</p>
        <button className="retry-button" onClick={() => { trackEvent('retry_release'); window.location.reload() }}>重新讀取</button>
      </section>
    </div>
  )
}

function Dashboard() {
  const { release, dataSource, contentHash, loading, error, reload } = useData()
  if (loading && !release) return <LoadingScreen />
  if (!release) return <ErrorScreen message={error ?? '發布快照不存在'} />
  return <DashboardContent release={release} dataSource={dataSource ?? 'network'} contentHash={contentHash} onReload={reload} refreshError={error} />
}

function DashboardContent({ release, dataSource, contentHash, onReload, refreshError }: { release: Release; dataSource: LoadedRelease['source']; contentHash: string | null; onReload: () => void; refreshError: string | null }) {
  const blocks = dashboardStrategyRows(release)
  const [activeKey, setActiveKey] = useState<StrategyKey>('trust')
  const [historyView, setHistoryView] = useState(() => new URLSearchParams(window.location.search).get('view') === 'history')
  useEffect(() => { const onPop = () => setHistoryView(new URLSearchParams(window.location.search).get('view') === 'history'); window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop) }, [])
  const showHistory = () => {
    const params = new URLSearchParams(window.location.search)
    params.set('view', 'history')
    window.history.pushState({ historyView: true }, '', `${window.location.pathname}?${params}`)
    setHistoryView(true)
    trackEvent('history_view')
  }
  const returnToLatest = () => {
    const params = new URLSearchParams(window.location.search)
    params.delete('view')
    const query = params.toString()
    window.history.pushState({}, '', `${window.location.pathname}${query ? `?${query}` : ''}`)
    setHistoryView(false)
  }
  const active = blocks.find((block) => block.presentation.key === activeKey) ?? blocks[0]

  useEffect(() => {
    trackEventOnce('dashboard_view', 'dashboard_view', { runId: release.runId })
  }, [release.runId])

  useEffect(() => {
    for (const row of release.rankings[activeKey]) {
      trackEventOnce(`impression:${activeKey}:${row.code}`, 'candidate_impression', { strategy: activeKey, code: row.code })
      if (row.valuationEvidenceLevel) {
        trackEventOnce(`evidence:${activeKey}:${row.code}`, 'valuation_evidence_view', {
          strategy: activeKey,
          code: row.code,
          level: row.valuationEvidenceLevel,
        })
      }
    }
  }, [activeKey, release])

  const selectStrategy = (key: StrategyKey) => {
    setActiveKey(key)
    trackEvent('strategy_tab_select', { strategy: key })
  }

  return (
    <div className="app-shell">
      <main className="dashboard-shell">
        <header className="dashboard-header">
          <div>
            <p className="site-kicker">TAIWAN STOCK RESEARCH</p>
            <h1>台股三策略選股</h1>
            <p className="dashboard-intro">切換策略 tab 後查看該策略的候選；每檔股票同步顯示 PEG、價格、估值帶與正式／代理證據等級。</p>
          </div>
          <div className="dashboard-meta" aria-label="資料資訊">
            <button className="history-nav-button" onClick={historyView ? returnToLatest : showHistory} aria-pressed={historyView}>{historyView ? '返回最新發布' : '歷史篩選'}</button>
          </div>
        </header>

        <DataStatus release={release} source={dataSource} />
        {refreshError && <p className="publication-notice" role="alert">最新發布讀取失敗，仍保留目前已載入版本：{refreshError}</p>}
        <PublicationNotice release={release} source={dataSource} contentHash={contentHash} onReload={onReload} />

        {historyView && <HistoryPanel refreshKey={contentHash ?? `${release.marketDate}:${release.runId}:${release.generatedAt}`} />}
        <div hidden={historyView}>
        <MarketVolumeIndicator indicator={release.marketIndicators?.volumeMultiple00631L} />
        <CoverageFunnelView
          funnel={releaseCoverageFunnel(release, activeKey)}
          strategy={activeKey}
          coverage={release.coverage}
          marketDate={release.marketDate}
          growthStocks={release.stocks}
          trustSignalCount={release.summary.trustSignalCount}
          trustNewEntryCount={release.summary.trustNewEntryCount}
        />

        <div className="strategy-tabs" role="tablist" aria-label="股票策略">
          {blocks.map((block, index) => {
            const selected = activeKey === block.presentation.key
            return (
              <button
                key={block.presentation.key}
                id={`strategy-tab-${block.presentation.key}`}
                className={selected ? 'strategy-tab active' : 'strategy-tab'}
                role="tab"
                aria-selected={selected}
                aria-controls={`strategy-panel-${block.presentation.key}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => selectStrategy(block.presentation.key)}
                onKeyDown={(event) => {
                  if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
                  event.preventDefault()
                  const nextIndex = event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? blocks.length - 1
                      : (index + (event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : -1) + blocks.length) % blocks.length
                  const nextKey = blocks[nextIndex].presentation.key
                  selectStrategy(nextKey)
                  document.getElementById(`strategy-tab-${nextKey}`)?.focus()
                }}
              >
                <span>{block.presentation.title}</span>
                <small>{block.presentation.subtitle}</small>
              </button>
            )
          })}
        </div>

        {blocks.map((block) => {
          const selected = block.presentation.key === activeKey
          return (
            <section
              key={block.presentation.key}
              className="strategy-panel"
              id={`strategy-panel-${block.presentation.key}`}
              role="tabpanel"
              aria-labelledby={`strategy-tab-${block.presentation.key}`}
              tabIndex={selected ? 0 : -1}
              hidden={!selected}
            >
              <StrategyCard presentation={block.presentation} rows={block.rows} />
            </section>
          )
        })}

        <footer className="dashboard-footer">
          <span>只讀同一次發布快照 · {release.runId}</span>
          <span>研究篩選入口，不是投資建議或自動下單。</span>
        </footer>
        </div>
      </main>
    </div>
  )
}

function percentage(numerator: number | undefined, denominator: number | undefined): string {
  if (typeof numerator !== 'number' || typeof denominator !== 'number' || denominator <= 0) return '—'
  return `${(numerator / denominator * 100).toFixed(1)}%`
}

const growthReasonLabels: Record<string, string> = {
  price: '同日價格', pe: 'PE', ttmEps: 'TTM EPS', annualEpsGrowth: '多年度 EPS 成長', earningsGrowth: '多年度 EPS 成長',
  dividend: '已確認股利', dividendYield: '已確認股利', extreme: '極端外推', threshold: '總報酬本益比門檻', health: '成長健康檢查',
}

export function CoverageFunnelView({ funnel, strategy, coverage, growthStocks = [], marketDate, trustSignalCount, trustNewEntryCount }: {
  funnel: CoverageFunnel
  strategy: StrategyKey
  coverage: Coverage
  growthStocks?: StockSummary[]
  marketDate?: string | null
  trustSignalCount?: number
  trustNewEntryCount?: number
}) {
  const growth = strategy === 'growth'
  const hasGrowthCoverage = funnel.growthEvaluationState !== null
  const growthStages = hasGrowthCoverage ? [
    ['普通股母體', funnel.growthTerminalOutcomes?.universe ?? null],
    ['估值輸入完整', funnel.growthInputComplete],
    ['總報酬本益比可計算', funnel.growthValuationComplete],
    ['總報酬本益比 ≥ 1.20', funnel.growthThresholdCandidates],
    ['成長健康 ≥ 4/5', funnel.growthHealthCandidates],
    ['最終候選', funnel.strategyCandidates],
  ] as const : []
  const standardStages = [
    ['A 普通股母體', funnel.universe],
    ...(strategy === 'trust'
      ? [['官方十日買超 Top10 新進榜', trustSignalCount ?? null] as const]
      : [['同日行情可用', funnel.priceComplete] as const]),
    [strategy === 'trust' ? '投信新進榜候選' : '3.5 年價格觀察候選', funnel.strategyCandidates],
  ] as const
  const stages = growth ? growthStages : standardStages
  const missingReasons = funnel.growthMissingReasons
    ?.filter((item) => item.count > 0)
    .map((item) => `${growthReasonLabels[item.reason] ?? item.reason} ${item.count} 檔`)
    .join(' · ')
  const growthExplanation = !hasGrowthCoverage
    ? '此舊版發布未提供成長覆蓋診斷；整組數字未知，等待新版重算。'
    : funnel.growthEvaluationState === 'not_evaluable'
      ? '成長估值尚不可評估：目前沒有可計算估值不代表條件未達。請查看財務建庫進度與逐檔缺漏。'
      : funnel.growthValuationComplete === 0
        ? `目前可計算估值 0 檔，無法判斷門檻是否達成。${missingReasons ? ` 輸入缺漏：${missingReasons}。` : ''}`
        : funnel.growthThresholdCandidates === 0
          ? `已計算 ${funnel.growthValuationComplete} 檔，總報酬本益比 ≥ 1.20 為 0 檔。`
          : funnel.growthHealthCandidates === 0
            ? `總報酬本益比門檻合格 ${funnel.growthThresholdCandidates} 檔，健康 ≥ 4/5 為 0 檔。`
            : `健康 ≥ 4/5 合格 ${funnel.growthHealthCandidates} 檔，最終候選 ${funnel.strategyCandidates} 檔。`
  const terminalLabels: Record<string, string> = { missing: '缺少輸入', knownInvalid: '已知不合格', extreme: '極端外推', belowThreshold: '低於估值門檻', healthBlocked: '健康未達', selected: '已入選' }
  const terminalOutcomes = funnel.growthTerminalOutcomes
    ? Object.entries(terminalLabels).map(([key, label]) => `${label} ${funnel.growthTerminalOutcomes?.[key as keyof typeof funnel.growthTerminalOutcomes]} 檔`).join(' · ')
    : null
  const financialStates = qualityStatusCounts(growthStocks)
  const financialSummary = growthStocks.length
    ? `明確通過 ${financialStates.pass} · 明確未通過 ${financialStates.fail} · 未評估 ${financialStates.unknown} · 不適用 ${financialStates.notApplicable} · 未提供 ${financialStates.unreported}`
    : `財務品質逐檔狀態未提供；發布摘要明確通過 ${coverage.financialCompleteCount} 檔`
  const trackedQuoteCount = coverage.trackedCompleteCount ?? coverage.priceCompleteCount
  const trackedQuoteUniverse = coverage.trackedCount ?? coverage.universeCount
  const growthInputPct = hasGrowthCoverage ? percentage(funnel.growthInputComplete ?? undefined, funnel.growthTerminalOutcomes?.universe) : '—'
  return (
    <section className="coverage-funnel" aria-label="候選資料漏斗">
      <div className="publication-coverage" aria-label="行情與財務建庫進度">
        <span>追蹤行情完整度 <strong>{percentage(trackedQuoteCount, trackedQuoteUniverse)}</strong> ({trackedQuoteCount}/{trackedQuoteUniverse})</span>
        <span>財務品質逐檔狀態 <strong>{financialSummary}</strong></span>
        <span>股票資料檔覆蓋 <strong>{coverage.databaseCount}/{coverage.universeCount}</strong></span>
        {growth && <span>成長估值輸入建置 <strong>{growthInputPct}</strong> ({hasGrowthCoverage ? `${funnel.growthInputComplete}/${funnel.growthTerminalOutcomes?.universe} · 缺資料 ${funnel.growthTerminalOutcomes?.missing}` : '未提供診斷'})</span>}
      </div>
      <div className="funnel-steps">
        {stages.map(([label, count], index) => <Fragment key={label}>
          {index > 0 && <i aria-hidden="true">→</i>}
          <span><small>{label}</small><strong>{count ?? '—'}</strong></span>
        </Fragment>)}
      </div>
      {growth ? <>
        <p>{growthExplanation}{hasGrowthCoverage ? ' 缺漏原因可能重疊，不可相加。' : ''}</p>
        {hasGrowthCoverage && missingReasons && <p>輸入或淘汰原因（可重疊）：{missingReasons}。</p>}
        {hasGrowthCoverage && terminalOutcomes && <p>互斥結果（普通股母體）：{terminalOutcomes}</p>}
        <GrowthStockDiagnosticsView stocks={growthStocks} coverageAvailable={hasGrowthCoverage} />
      </>
        : <>
          <p>{strategy === 'trust'
            ? `投信訊號：Top10 新進榜 ${trustSignalCount ?? '—'} 檔；新進榜確認 ${trustNewEntryCount ?? '—'} 檔。條件只依官方排名差集，不受 PE／PEG 缺值影響。`
            : '低位條件：同一 A 母體、合格調整價與 3.5 年回歸可用、Z ≤ 0、slope > 0；健康與估值資料是旁證，不隱藏價格觀察。'}</p>
          {strategy === 'trust' && <p>本次比較只涵蓋發布資料日 {marketDate || '未知'}；較新交易日尚未驗證。</p>}
          <p>估值旁證：祖魯 PEG 可計算 {funnel.valuationComplete} 檔 · PEG 低於 0.75 {funnel.pegCandidates} 檔 · 正式 EPS {funnel.formalValuations} 檔 · 代理估算 {funnel.proxyValuations} 檔；不作此策略必要門檻。</p>
        </>}
    </section>
  )
}

const growthInputLabels: Record<keyof GrowthInputAudit, string> = {
  price: '價格', pe: '本益比', ttmEps: 'TTM EPS', earningsGrowth: 'EPS 成長', dividendYield: '股利殖利率',
}
const growthOriginLabels: Record<string, string> = { reported: '來源報告', derived: '推導值', proxy: '代理值', unavailable: '缺少' }
const growthEvidenceReasonLabels: Record<string, string> = {
  insufficient_quarters: '季度不足', nonconsecutive_quarters: '季度不連續', incomparable_quarters: '股數或期間基礎不可比',
  missing_or_unavailable_quarter_eps: '季度 EPS 缺漏', missing_quarters: '缺少季度資料', nonpositive_ttm_eps: 'TTM EPS 非正值',
  nonpositive_eps: 'EPS 非正值',
}

function inputEvidenceLabel(audit: GrowthInputAudit | undefined, key: keyof GrowthInputAudit): string {
  const evidence = audit?.[key]
  if (!evidence) return `${growthInputLabels[key]}：未提供來源明細`
  const detail = [evidence.sourcePeriod, evidence.source].filter(Boolean).join(' · ')
  return `${growthInputLabels[key]}：${growthOriginLabels[evidence.origin] ?? evidence.origin}${detail ? ` · ${detail}` : ''}`
}

export function GrowthStockDiagnosticsView({ stocks, coverageAvailable = false }: { stocks: StockSummary[]; coverageAvailable?: boolean }) {
  if (!stocks.length) return <p>此發布沒有逐檔成長估值診斷。</p>
  const outcomes = stocks.reduce((counts, stock) => {
    counts[stockGrowthHealthOutcome(stock)] += 1
    return counts
  }, { qualified: 0, not_qualified: 0, unknown: 0, unreported: 0 })
  return <details className="growth-stock-diagnostics">
    <summary>逐檔成長估值診斷 ({stocks.length} 檔)</summary>
    <p>{coverageAvailable
      ? '以下是同次發布的逐檔估值與健康結果。'
      : '此舊版沒有完整的 growth-coverage-v1 總漏斗；以下只顯示發布已保存的逐檔值，不推算缺少的來源證據或總人數。'}</p>
    <p>五項健康檢查：月營收連續三個月 YOY 皆大於 0；最近單季毛利「金額」、營業利益、稅前淨利、稅後淨利各自同比大於 0。未知不算通過；四項確定通過即可合格，兩項確定失敗則已不可能達到 4/5。健康合格仍須估值可計算且總報酬本益比 ≥ 1.20 才能入選。</p>
    <p>逐檔健康狀態：合格 {outcomes.qualified} · 已知未達 {outcomes.not_qualified} · 尚未能判定 {outcomes.unknown} · 未提供檢查 {outcomes.unreported}。</p>
    <ul>{stocks.map((stock) => {
      const growth = stock.growthValuation
      const health = stock.healthCategories?.find((category) => category.key === 'growth')
      const outcome = growthHealthOutcome(health)
      const passCount = health?.checks?.filter((check) => check.status === 'pass').length
      const healthLabel = outcome === 'qualified'
        ? `健康合格 ${passCount}/5`
        : outcome === 'not_qualified'
          ? `健康未達（確定失敗至少兩項；已確認通過 ${passCount}/5）`
          : outcome === 'unknown'
            ? `健康未定（未知可能影響 4/5；已確認通過 ${passCount}/5）`
            : '未提供五項健康檢查'
      const statusLabel = growth?.status === 'available' ? '可計算' : growth?.status === 'extreme' ? '極端外推' : growth?.status === 'unavailable' ? '不可計算' : '未提供診斷'
      const missing = growth?.missingReasons?.map((reason) => growthReasonLabels[reason] ?? reason).join('、')
      return <li key={stock.code}>
        <details>
          <summary>{stock.name} ({stock.code}) · {statusLabel} · {healthLabel}</summary>
          <p>{growth?.reason || '此舊版發布未提供個股估值原因。'}{missing ? ` 缺少：${missing}。` : ''}</p>
          {growth?.inputAudit && <ul>{(['price', 'pe', 'ttmEps', 'earningsGrowth', 'dividendYield'] as const).map((key) => {
            const evidence = growth.inputAudit?.[key]
            return <li key={key}>{inputEvidenceLabel(growth.inputAudit, key)}{evidence?.method ? ` · ${evidence.method}` : ''}{evidence?.reason ? ` · ${growthEvidenceReasonLabels[evidence.reason] ?? evidence.reason}` : ''}</li>
          })}</ul>}
          {health?.checks?.length ? <ul>{health.checks.map((check) => <li key={check.label}>{check.label}：{check.status} · {check.explanation}</li>)}</ul> : null}
        </details>
      </li>
    })}</ul>
  </details>
}

function LoadingScreen() {
  return (
    <div className="state-shell">
      <section className="state-panel" role="status" aria-live="polite">
        <div className="loading-line" />
        <p className="site-kicker">TAIWAN STOCK RESEARCH</p>
        <h1>正在讀取最新發布</h1>
        <p>網站只列已知資料，不會用示範股票填補空白。</p>
      </section>
    </div>
  )
}

function ErrorScreen({ message }: { message: string }) {
  const { reload } = useData()
  return (
    <div className="state-shell">
      <section className="state-panel error-panel" role="alert">
        <p className="site-kicker">DATA / UNAVAILABLE</p>
        <h1>目前沒有可用的發布快照</h1>
        <p>{message}</p>
        <p className="state-help">請檢查公開發布資料。</p>
        <button className="retry-button" onClick={() => { trackEvent('retry_release'); reload() }}>重新讀取</button>
      </section>
    </div>
  )
}

export function AppForTest() {
  return <App />
}
