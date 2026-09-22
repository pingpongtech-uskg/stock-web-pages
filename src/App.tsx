import { Component, createContext, useContext, useEffect, useState, type ErrorInfo, type ReactNode } from 'react'

import { StrategyCard } from './components/StrategyCard'
import { loadLatestRelease } from './data/api'
import { releaseCoverageFunnel, type CoverageFunnel } from './domain/coverage'
import { trackEvent, trackEventOnce } from './domain/events'
import type { RankingRow, Release } from './domain/types'
import { strategyPresentations, type StrategyKey, type StrategyPresentation } from './domain/strategyPresentation'
import './styles.css'

interface DataContextValue {
  release: Release | null
  loading: boolean
  error: string | null
  reload: () => void
}

const DataContext = createContext<DataContextValue | null>(null)

function DataProvider({ children }: { children: ReactNode }) {
  const [release, setRelease] = useState<Release | null>(null)
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
        setRelease(next)
        setLoading(false)
        trackEvent('release_load_success', { runId: next.runId })
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
    <DataContext.Provider value={{ release, loading, error, reload: () => setReloadKey((value) => value + 1) }}>
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
  const { release, loading, error } = useData()
  if (loading) return <LoadingScreen />
  if (error || !release) return <ErrorScreen message={error ?? '發布快照不存在'} />
  return <DashboardContent release={release} />
}

function DashboardContent({ release }: { release: Release }) {
  const blocks = dashboardStrategyRows(release)
  const [activeKey, setActiveKey] = useState<StrategyKey>('trust')
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
            <span>資料日 <strong>{release.marketDate ?? '—'}</strong></span>
            <span>更新 <strong>{formatGeneratedAt(release.generatedAt)}</strong></span>
          </div>
        </header>

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
      </main>
    </div>
  )
}

function CoverageFunnelView({ funnel, strategy }: { funnel: CoverageFunnel; strategy: StrategyKey }) {
  const growth = strategy === 'growth'
  return (
    <section className="coverage-funnel" aria-label="候選資料漏斗">
      <div className="funnel-steps">
        <span><small>A 母體</small><strong>{funnel.universe}</strong></span>
        <i aria-hidden="true">→</i>
        <span><small>價格完整</small><strong>{funnel.priceComplete}</strong></span>
        <i aria-hidden="true">→</i>
        <span><small>{growth ? '影片版估值可計算' : 'PEG 可計算'}</small><strong>{growth ? funnel.growthValuationComplete : funnel.valuationComplete}</strong></span>
        <i aria-hidden="true">→</i>
        <span><small>{growth ? '總報酬本益比 ≥ 1.20' : 'PEG &lt; 0.75'}</small><strong>{growth ? funnel.strategyCandidates : funnel.pegCandidates}</strong></span>
        <i aria-hidden="true">→</i>
        <span><small>本策略</small><strong>{funnel.strategyCandidates}</strong></span>
      </div>
      <p>估值證據：正式 EPS {funnel.formalValuations} 檔 · 代理估算 {funnel.proxyValuations} 檔；代理 PEG 仍顯示，但不等同正式 EPS。</p>
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

function formatGeneratedAt(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-TW', { dateStyle: 'short', timeStyle: 'short' })
}

export function AppForTest() {
  return <App />
}
