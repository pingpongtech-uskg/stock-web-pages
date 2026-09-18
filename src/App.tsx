import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { DataStatus } from './components/DataStatus'
import { StrategyCard } from './components/StrategyCard'
import { loadLatestRelease } from './data/api'
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
      })
      .catch((reason: unknown) => {
        if (cancelled) return
        setError(reason instanceof Error ? reason.message : '無法讀取發布快照')
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
  return <DataProvider><Dashboard /></DataProvider>
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

  return (
    <div className="app-shell">
      <main className="dashboard-shell">
        <header className="dashboard-header">
          <div>
            <p className="site-kicker">TAIWAN STOCK RESEARCH</p>
            <h1>台股三策略選股</h1>
            <p className="dashboard-intro">切換策略 tab 後查看該策略的已知候選；每檔股票同步顯示現在價格與祖魯合理價。</p>
          </div>
          <div className="dashboard-meta" aria-label="資料資訊">
            <span>資料日 <strong>{release.marketDate ?? '—'}</strong></span>
            <span>更新 <strong>{formatGeneratedAt(release.generatedAt)}</strong></span>
          </div>
        </header>

        <DataStatus release={release} />

        <div className="strategy-tabs" role="tablist" aria-label="股票策略">
          {blocks.map((block) => (
            <button
              key={block.presentation.key}
              className={activeKey === block.presentation.key ? 'strategy-tab active' : 'strategy-tab'}
              role="tab"
              aria-selected={activeKey === block.presentation.key}
              onClick={() => setActiveKey(block.presentation.key)}
            >
              <span>{block.presentation.title}</span>
              <small>{block.presentation.subtitle}</small>
            </button>
          ))}
        </div>

        <section className="strategy-panel" role="tabpanel" aria-label={`${active.presentation.title}內容`}>
          <StrategyCard presentation={active.presentation} rows={active.rows} />
        </section>

        <footer className="dashboard-footer">
          <span>只讀同一次發布快照 · {release.runId}</span>
          <span>研究篩選入口，不是投資建議或自動下單。</span>
        </footer>
      </main>
    </div>
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
        <button className="retry-button" onClick={reload}>重新讀取</button>
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
