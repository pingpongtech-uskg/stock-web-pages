import { Component, createContext, useContext, useEffect, useState, Fragment, type ErrorInfo, type ReactNode } from 'react'

import { HistoryPanel } from './components/HistoryPanel'
import { MarketVolumeIndicator } from './components/MarketVolumeIndicator'
import { StrategyCard } from './components/StrategyCard'
import { DataStatus } from './components/DataStatus'
import { loadLatestRelease, type LoadedRelease } from './data/api'
import { releaseCoverageFunnel, type CoverageFunnel } from './domain/coverage'
import { trackEvent, trackEventOnce } from './domain/events'
import type { RankingRow, Release } from './domain/types'
import { strategyPresentations, type StrategyKey, type StrategyPresentation } from './domain/strategyPresentation'
import './styles.css'

interface DataContextValue {
  release: Release | null
  dataSource: LoadedRelease['source'] | null
  loading: boolean
  error: string | null
  reload: () => void
}

const DataContext = createContext<DataContextValue | null>(null)

function DataProvider({ children }: { children: ReactNode }) {
  const [release, setRelease] = useState<Release | null>(null)
  const [dataSource, setDataSource] = useState<LoadedRelease['source'] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    loadLatestRelease()
      .then((next) => {
        if (cancelled) return
        setRelease(next.release)
        setDataSource(next.source)
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
    <DataContext.Provider value={{ release, dataSource, loading, error, reload: () => setReloadKey((value) => value + 1) }}>
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
  const { release, dataSource, loading, error } = useData()
  if (loading) return <LoadingScreen />
  if (error || !release) return <ErrorScreen message={error ?? '發布快照不存在'} />
  return <DashboardContent release={release} dataSource={dataSource ?? 'network'} />
}

function DashboardContent({ release, dataSource }: { release: Release; dataSource: LoadedRelease['source'] }) {
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
    if (window.history.state?.historyView) {
      window.history.back()
      return
    }
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

        {historyView && <HistoryPanel />}
        <div hidden={historyView}>
        <MarketVolumeIndicator indicator={release.marketIndicators?.volumeMultiple00631L} />
        <CoverageFunnelView funnel={releaseCoverageFunnel(release, activeKey)} strategy={activeKey} />

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

export function CoverageFunnelView({ funnel, strategy }: { funnel: CoverageFunnel; strategy: StrategyKey }) {
  const growth = strategy === 'growth'
  const growthStages = [
    ['共同母體', funnel.universe],
    ['估值輸入完整', funnel.growthInputComplete],
    ['總報酬本益比可計算', funnel.growthValuationComplete],
    ['總報酬本益比 ≥ 1.20', funnel.growthThresholdCandidates],
    ['成長健康 ≥ 4/5', funnel.growthHealthCandidates],
    ['最終候選', funnel.strategyCandidates],
  ] as const
  const standardStages = [
    ['A 母體', funnel.universe],
    ['價格完整', funnel.priceComplete],
    ['PEG 可計算', funnel.valuationComplete],
    ['PEG < 0.75', funnel.pegCandidates],
    ['本策略', funnel.strategyCandidates],
  ] as const
  const stages = growth ? growthStages : standardStages
  const missingReasonLabels: Record<string, string> = {
    price: '價格', pe: 'PE', ttmEps: 'TTM EPS', annualEpsGrowth: '多年度 EPS 成長', earningsGrowth: '多年度 EPS 成長',
    dividend: '已確認股利', dividendYield: '已確認股利', extreme: '極端外推', threshold: '總報酬本益比門檻', health: '成長健康檢查',
  }
  const missingReasons = funnel.growthMissingReasons
    ?.filter((item) => item.count > 0)
    .map((item) => `${missingReasonLabels[item.reason] ?? item.reason} ${item.count} 檔`)
    .join(' · ')
  const growthExplanation = funnel.growthInputComplete === null
    ? '此發布未提供成長估值輸入覆蓋統計；— 表示沒有統計資料，不代表 0 檔合格。'
    : funnel.growthValuationComplete === 0
      ? `成長估值輸入完整 ${funnel.growthInputComplete} 檔，可計算 0 檔；目前沒有可評估門檻的估值。${missingReasons ? ` 原因：${missingReasons}。` : ''}`
      : funnel.growthThresholdCandidates === 0
        ? `已計算 ${funnel.growthValuationComplete} 檔，但總報酬本益比門檻合格 0 檔。${missingReasons ? ` 其他未入選原因：${missingReasons}。` : ''}`
        : missingReasons ? `未入選原因：${missingReasons}。` : '沒有缺少輸入原因明細。'
  return (
    <section className="coverage-funnel" aria-label="候選資料漏斗">
      <div className="funnel-steps">
        {stages.map(([label, count], index) => <Fragment key={label}>
          {index > 0 && <i aria-hidden="true">→</i>}
          <span><small>{label}</small><strong>{count ?? '—'}</strong></span>
        </Fragment>)}
      </div>
      {growth ? <p>{growthExplanation}</p>
        : <p>估值證據：正式 EPS {funnel.formalValuations} 檔 · 代理估算 {funnel.proxyValuations} 檔；代理 PEG 仍顯示，但不等同正式 EPS。</p>}
    </section>
  )
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
