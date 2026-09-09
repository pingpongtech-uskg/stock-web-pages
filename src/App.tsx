import { createContext, useContext, useEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react'
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom'
import { DataStatus, CoverageLine } from './components/DataStatus'
import { EmptyState } from './components/EmptyState'
import { LineChart } from './components/LineChart'
import { MetricCell } from './components/MetricCell'
import { Sparkline } from './components/Sparkline'
import { StatusPill, statusLabels } from './components/StatusPill'
import { loadLatestRelease, loadStockDetail } from './data/api'
import type {
  HistorySnapshot,
  MetricStatus,
  RankingRow,
  Release,
  RuleCheck,
  StockDetail,
  StockSummary,
} from './domain/types'
import {
  emptyJournal,
  exportJournal,
  loadJournal,
  parseJournalImport,
  saveJournal,
  type JournalState,
  type TradeEntry,
} from './storage/journal'
import './styles.css'

interface DataContextValue {
  release: Release | null
  loading: boolean
  error: string | null
  reload: () => void
  getStock: (code: string) => Promise<StockDetail>
}

const DataContext = createContext<DataContextValue | null>(null)

function DataProvider({ children }: { children: ReactNode }) {
  const [release, setRelease] = useState<Release | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const detailCache = useRef<Record<string, StockDetail>>({})

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    loadLatestRelease()
      .then((next) => {
        if (!cancelled) {
          detailCache.current = {}
          setRelease(next)
          setLoading(false)
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : '無法讀取發布快照')
          setLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [reloadKey])

  const getStock = async (code: string) => {
    if (!release) throw new Error('發布快照尚未載入')
    if (!detailCache.current[code]) detailCache.current[code] = await loadStockDetail(release.runId, code)
    return detailCache.current[code]
  }

  return <DataContext.Provider value={{ release, loading, error, reload: () => setReloadKey((value) => value + 1), getStock }}>{children}</DataContext.Provider>
}

function useData() {
  const value = useContext(DataContext)
  if (!value) throw new Error('useData must be used inside DataProvider')
  return value
}

function useJournalState() {
  const [state, setState] = useState<JournalState>(emptyJournal)
  const [ready, setReady] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    loadJournal().then((next) => {
      setState(next)
      setReady(true)
    })
  }, [])

  const update = async (next: JournalState) => {
    setState(next)
    setSaving(true)
    await saveJournal(next)
    setSaving(false)
  }

  return { state, ready, saving, update }
}

const navigation = [
  { to: '/', label: '今日研究', mark: '01', end: true },
  { to: '/screener', label: '選股器', mark: '02' },
  { to: '/rankings', label: '排行榜', mark: '03' },
  { to: '/compare', label: '比較', mark: '04' },
  { to: '/journal', label: '自選與紀律', mark: '05' },
  { to: '/research', label: '策略檢驗', mark: '06' },
  { to: '/methodology', label: '方法與資料', mark: '07' },
]

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <DataProvider>
        <AppLayout />
      </DataProvider>
    </BrowserRouter>
  )
}

function AppLayout() {
  const { release, loading, error } = useData()
  const location = useLocation()
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [dark, setDark] = useState(() => window.localStorage.getItem('screen-theme') === 'dark')

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    window.localStorage.setItem('screen-theme', dark ? 'dark' : 'light')
  }, [dark])

  const submitSearch = (event: FormEvent) => {
    event.preventDefault()
    const query = search.trim()
    navigate(query ? `/screener?q=${encodeURIComponent(query)}` : '/screener')
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/" aria-label="回到今日研究">
          <span className="brand-symbol">低</span>
          <span><strong>台股低位</strong><small>研究室</small></span>
        </Link>
        <div className="sidebar-kicker">RESEARCH DESK</div>
        <nav className="primary-nav" aria-label="主要導覽">
          {navigation.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
              <span className="nav-mark">{item.mark}</span><span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-note">
          <span className="note-label">研究原則</span>
          <p>候選不是下單。資料不足就標未知，不用零值補洞。</p>
        </div>
        <div className="sidebar-foot">本機研究版 · v0.1</div>
      </aside>

      <div className="main-shell">
        <header className="topbar">
          <form className="global-search" onSubmit={submitSearch} role="search">
            <span className="search-icon" aria-hidden="true">⌕</span>
            <input aria-label="搜尋代碼或公司名稱" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜尋代碼／公司名稱" />
            <kbd>⌘ K</kbd>
          </form>
          <div className="topbar-actions">
            {release && <span className="top-date">資料日 {release.marketDate ?? '—'}</span>}
            <button className="icon-button" onClick={() => setDark((value) => !value)} aria-label={dark ? '切換亮色主題' : '切換深色主題'} title="切換主題">
              {dark ? '☼' : '◐'}
            </button>
            <Link className="profile-chip" to="/journal"><span>O</span><strong>本機</strong></Link>
          </div>
        </header>

        <main className="content" id="main-content">
          {loading && <LoadingScreen />}
          {!loading && error && <ErrorScreen message={error} />}
          {!loading && !error && release && (
            <>
              <DataStatus release={release} />
              <Routes>
                <Route path="/" element={<TodayPage />} />
                <Route path="/screener" element={<ScreenerPage />} />
                <Route path="/rankings" element={<RankingsPage />} />
                <Route path="/stocks/:code" element={<StockPage />} />
                <Route path="/compare" element={<ComparePage />} />
                <Route path="/journal" element={<JournalPage />} />
                <Route path="/research" element={<ResearchPage />} />
                <Route path="/methodology" element={<MethodologyPage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
              <footer className="page-footer">本頁只讀同一發布快照 · {release.runId} · 不連券商、不自動下單</footer>
            </>
          )}
        </main>
      </div>
      <a className="skip-link" href="#main-content">跳到主要內容</a>
      <span className="route-hint" data-route={location.pathname} aria-hidden="true" />
    </div>
  )
}

function LoadingScreen() {
  return <div className="state-panel"><div className="loading-line" /><h2>正在讀取已驗證發布</h2><p>前端不直接呼叫金融 API。若資料檔不存在，會明示不可用。</p></div>
}

function ErrorScreen({ message }: { message: string }) {
  const { reload } = useData()
  return <div className="state-panel error-panel"><div className="error-code">DATA / 503</div><h2>目前沒有可用的發布快照</h2><p>{message}</p><p className="muted">這不是示範資料頁。請先完成一次資料發布，或檢查 `public/data/latest.json`。</p><button className="button primary" onClick={reload}>重新讀取</button></div>
}

function PageTitle({ eyebrow, title, description, actions }: { eyebrow: string; title: ReactNode; description?: string; actions?: ReactNode }) {
  return <div className="page-title"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="page-actions">{actions}</div>}</div>
}

function StatCard({ label, value, detail, tone = 'blue' }: { label: string; value: string | number; detail: string; tone?: 'blue' | 'amber' | 'neutral' | 'red' | 'green' }) {
  return <div className={`stat-card tone-${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
}

function formatPct(value: number | null, digits = 1) {
  return value == null || !Number.isFinite(value) ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
}

function formatNumber(value: number | null, digits = 0) {
  return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('zh-TW', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function stateClass(state: StockSummary['signalState']) {
  if (state === '進場觀察') return 'state-entry'
  if (state === '低位觀察') return 'state-low'
  if (state === '值得研究') return 'state-research'
  return 'state-muted'
}

function SignalState({ state }: { state: StockSummary['signalState'] }) {
  return <span className={`signal-state ${stateClass(state)}`}>{state}</span>
}

function routeLabel(reason: string) {
  if (reason.startsWith('投信')) return '投信關注'
  if (reason.startsWith('成長')) return '成長改善'
  if (reason.startsWith('低位')) return '低位品質'
  if (reason.startsWith('營收')) return '營收線索'
  if (reason.startsWith('價格')) return '價格描述'
  return '研究'
}

function DataEvidence({ stock }: { stock: StockSummary }) {
  const priceLabel = stock.priceBasis === 'adjusted' ? 'yfinance Adj Close' : stock.priceBasis === 'raw_proxy' ? 'FinMind 未調整收盤代理' : '價格資料未知'
  const qualityStatus = stock.qualityProxyStatus ?? stock.qualityStatus
  const qualityReason = stock.qualityProxyReason ?? (qualityStatus === 'unknown' ? '正式三年財務條件仍未知' : `品質代理${statusLabels[qualityStatus]}`)
  const growthReason = stock.growthProxyReason ?? (stock.revenueGrowth3m == null ? '三月營收年增未知' : `三月營收年增 ${formatPct(stock.revenueGrowth3m)}；門檻 15%`)
  return <div className="evidence-list">
    <span><strong>價格</strong>{priceLabel} → 四年回歸／Z</span>
    <span><strong>品質</strong>{qualityReason}</span>
    <span><strong>成長</strong>{growthReason}</span>
    <span><strong>投信</strong>十日淨買超＋成交占比 → 投信排序</span>
    <span className="risk-text"><strong>風險</strong>{stock.risks[0] ?? '—'}</span>
    <small className="table-sub">資料狀態：{statusLabels[stock.dataStatus]} · 數值只讀本次快照</small>
  </div>
}

function StockTable({
  stocks,
  compact = false,
  compareCodes = [],
  onCompare,
  watchlist = [],
  onWatch,
}: {
  stocks: StockSummary[]
  compact?: boolean
  compareCodes?: string[]
  onCompare?: (code: string) => void
  watchlist?: string[]
  onWatch?: (code: string) => void
}) {
  if (!stocks.length) return <EmptyState title="目前沒有符合條件的標的" body="空名單是正常結果。請調整研究條件，或等待資料覆蓋完成；不會偷偷補入示範股票。" />
  return (
    <div className="table-wrap">
      <table className="stock-table">
        <thead><tr><th className="sticky-col">標的</th><th>入選原因</th><th>狀態</th><th>四年 Z</th><th>品質</th><th>成長</th><th>投信十日</th><th>風險／資料</th>{(onCompare || onWatch) && <th>操作</th>}</tr></thead>
        <tbody>
          {stocks.map((stock) => (
            <tr key={stock.code}>
              <td className="sticky-col stock-identity"><Link to={`/stocks/${stock.code}`} className="stock-code">{stock.code}</Link><Link to={`/stocks/${stock.code}`} className="stock-name">{stock.name}</Link><span>{stock.market} · {stock.sector || '產業未填'}</span></td>
              <td className="reason-cell"><div className="reason-tags">{stock.entryReasons.slice(0, compact ? 1 : 2).map((reason) => <span className="reason-tag" key={reason}>{routeLabel(reason)}</span>)}</div><p>{stock.entryReasons[0] ?? '尚無足夠條件說明'}</p></td>
              <td><SignalState state={stock.signalState} /></td>
              <td className={stock.zScore != null && stock.zScore >= 0 ? 'market-up number-cell' : stock.zScore != null ? 'market-down number-cell' : 'number-cell'}>{stock.zScore == null ? '—' : stock.zScore.toFixed(2)}<small>{stock.fiveLineStatus === 'unknown' ? '待驗證' : '四年模型'}</small></td>
              <td><StatusPill status={stock.qualityProxyStatus ?? stock.qualityStatus} label={stock.qualityProxyStatus ? `代理 ${statusLabels[stock.qualityProxyStatus]}` : undefined} /></td>
              <td><span className="number-cell">{formatPct(stock.revenueGrowth3m)}</span><small className="table-sub">{statusLabels[stock.growthProxyStatus ?? stock.growthStatus]}{stock.growthProxyStatus ? '（營收代理）' : ''}</small></td>
              <td><span className="number-cell">{stock.participation10 == null ? '—' : formatPct(stock.participation10)}</span><small className="table-sub">{stock.positiveDays10 == null ? '—' : `${stock.positiveDays10}/10 正買超`}</small></td>
              <td><DataEvidence stock={stock} /></td>
              {(onCompare || onWatch) && <td><div className="row-actions">{onCompare && <button className={`mini-button ${compareCodes.includes(stock.code) ? 'selected' : ''}`} onClick={() => onCompare(stock.code)} aria-label={`${compareCodes.includes(stock.code) ? '移除' : '加入'}比較 ${stock.code}`}>{compareCodes.includes(stock.code) ? '已選' : '比較'}</button>}{onWatch && <button className={`watch-button ${watchlist.includes(stock.code) ? 'saved' : ''}`} onClick={() => onWatch(stock.code)} aria-label={`${watchlist.includes(stock.code) ? '移除自選' : '加入自選'} ${stock.code}`}>{watchlist.includes(stock.code) ? '★' : '☆'}</button>}</div></td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function useWatchlist() {
  const { state, update } = useJournalState()
  const toggle = async (code: string) => {
    const next = state.watchlist.includes(code) ? state.watchlist.filter((item) => item !== code) : [...state.watchlist, code]
    await update({ ...state, watchlist: next })
  }
  return { watchlist: state.watchlist, toggle }
}

function TodayPage() {
  const { release } = useData()
  const { watchlist, toggle } = useWatchlist()
  const priority = useMemo(() => {
    const order: Record<StockSummary['signalState'], number> = { '進場觀察': 0, '低位觀察': 1, '值得研究': 2, '待補資料': 3, '資料不足': 4, '條件失效': 5 }
    return [...release!.stocks].sort((a, b) => order[a.signalState] - order[b.signalState] || a.code.localeCompare(b.code)).slice(0, 10)
  }, [release])
  const routeCounts = release!.summary.candidateRouteCounts
  const lowBaseGrowthCount = release!.stocks.filter((stock) => Number.isFinite(stock.zScore) && stock.zScore! <= -1 && Number.isFinite(stock.slope) && stock.slope! > 0 && stock.growthProxyStatus === 'pass').length
  const lowBaseQualityCount = release!.stocks.filter((stock) => Number.isFinite(stock.zScore) && stock.zScore! <= -1 && Number.isFinite(stock.slope) && stock.slope! > 0 && (stock.qualityProxyPassCount ?? 0) >= 4).length
  return (
    <div className="page-stack">
      <PageTitle eyebrow={`DAILY RESEARCH / ${release!.marketDate ?? '—'}`} title="今天值得先研究" description="先看資料狀態，再看條件與缺口。每日篩選不等於每日交易。" actions={<Link className="button secondary" to="/screener">開啟選股器 <span>→</span></Link>} />
      <section className="stat-grid">
        <StatCard label="市場資料日" value={release!.marketDate ?? '—'} detail={`更新 ${new Date(release!.generatedAt).toLocaleString('zh-TW', { hour: '2-digit', minute: '2-digit' })}`} />
        <StatCard label="正式進場" value={release!.summary.formalEntryCount ?? 0} detail="正式條件全數通過才會進入" tone="amber" />
        <StatCard label="研究候選" value={release!.coverage.candidateCount} detail={`三路聯集 · 投信 ${routeCounts.trust} / 成長 ${routeCounts.growth}`} />
        <StatCard label="資料完整度" value={release!.coverage.trackedCompletenessPct == null ? (release!.coverage.completenessPct == null ? '—' : `${release!.coverage.completenessPct.toFixed(1)}%`) : `${release!.coverage.trackedCompletenessPct.toFixed(1)}%`} detail={release!.coverage.scopeLabel ?? `${release!.coverage.databaseCount} 檔已建庫 / ${release!.coverage.universeCount.toLocaleString('zh-TW')} 檔母體`} tone="neutral" />
      </section>

      <section className="panel hero-panel">
        <div className="section-heading"><div><span className="eyebrow">PRIORITY LIST</span><h2>優先研究名單 <span className="count-badge">最多 10</span></h2></div><Link className="text-link" to="/rankings">看完整排行榜 →</Link></div>
        <div className="callout info"><span className="callout-icon">i</span><p>入選原因、四年 Z、品質與成長分開呈現。<strong>代理數值會標明來源與口徑</strong>；嚴格條件仍可為零，但不再讓可取得的研究證據消失。</p></div>
        <StockTable stocks={priority} watchlist={watchlist} onWatch={toggle} />
      </section>

      <section className="route-grid">
        <RouteCard title="投信關注" subtitle="十個市場交易日" value={routeCounts.trust} detail="以淨買超股數與該股成交占比排序" tone="red" link="/rankings?tab=trust" />
        <RouteCard title="品質代理" subtitle="最新年度五項檢查" value={release!.stocks.filter((stock) => stock.qualityProxyPassCount != null).length} detail="4/5 以上可作研究入口，正式三年條件另列" tone="blue" link="/rankings?tab=quality" />
        <RouteCard title="低基期成長" subtitle="Z ≤ -1 · 斜率為正" value={lowBaseGrowthCount} detail="營收年增代理通過，不要求投信先買" tone="green" link="/rankings?tab=lowBaseGrowth" />
        <RouteCard title="低基期品質" subtitle="Z ≤ -1 · 斜率為正" value={lowBaseQualityCount} detail="品質代理至少 4/5，不要求投信先買" tone="blue" link="/rankings?tab=lowBaseQuality" />
        <RouteCard title="成長改善" subtitle="三個月合計營收" value={routeCounts.growth} detail="營運改善證據，不是未來成長預測" tone="green" link="/rankings?tab=growth" />
      </section>

      <section className="split-panels">
        <div className="panel"><div className="section-heading"><div><span className="eyebrow">MOVEMENT</span><h2>今日變化</h2></div><span className="muted">相較前次發布</span></div><div className="movement-list"><MovementRow label="新增研究" value={release!.summary.addedToday} tone="blue" /><MovementRow label="條件改善" value={release!.summary.improvedToday} tone="green" /><MovementRow label="移出候選" value={release!.summary.removedToday} tone="amber" /></div></div>
        <div className="panel"><div className="section-heading"><div><span className="eyebrow">COVERAGE</span><h2>資料水位</h2></div><Link className="text-link" to="/methodology">查看口徑 →</Link></div><CoverageLine release={release!} /><p className="panel-note">首次建庫與免費額度會造成部分覆蓋。網站不把部分深度資料稱成「掃描全市場全部條件」。</p></div>
      </section>
      <div className="disclaimer">研究提示：四年回歸中線不是合理價；±2σ 不是未來漲跌機率；品質欄位是財務代理，不宣稱已證明護城河。</div>
    </div>
  )
}

function RouteCard({ title, subtitle, value, detail, tone, link }: { title: string; subtitle: string; value: number; detail: string; tone: 'red' | 'blue' | 'green'; link: string }) {
  return <Link to={link} className={`route-card route-${tone}`}><div><span className="eyebrow">{subtitle}</span><h3>{title}</h3></div><strong>{value}</strong><p>{detail}</p><span className="route-arrow">查看 →</span></Link>
}

function MovementRow({ label, value, tone }: { label: string; value: number; tone: string }) {
  return <div className="movement-row"><span className={`movement-dot dot-${tone}`} /><span>{label}</span><strong>{value}</strong><span className="muted">檔</span></div>
}

function ScreenerPage() {
  const { release } = useData()
  const { watchlist, toggle } = useWatchlist()
  const [params, setParams] = useSearchParams()
  const [query, setQuery] = useState(params.get('q') ?? '')
  const [market, setMarket] = useState(params.get('market') ?? 'all')
  const [entry, setEntry] = useState(params.get('entry') ?? 'all')
  const [quality, setQuality] = useState(params.get('quality') ?? 'all')
  const [status, setStatus] = useState(params.get('status') ?? 'all')
  const [sort, setSort] = useState<'state' | 'z' | 'growth' | 'trust'>((params.get('sort') as 'state' | 'z' | 'growth' | 'trust') || 'state')
  const [compareCodes, setCompareCodes] = useState<string[]>([])

  const filtered = useMemo(() => {
    const text = query.trim().toLowerCase()
    const list = release!.stocks.filter((stock) => {
      const matchesText = !text || `${stock.code} ${stock.name} ${stock.sector}`.toLowerCase().includes(text)
      const matchesMarket = market === 'all' || stock.market === market
      const matchesEntry = entry === 'all' || stock.entryReasons.some((reason) => reason.startsWith(entry))
      // The formal three-year rule is intentionally still unknown for the
      // current seed universe.  Let the user filter the available latest-period
      // quality proxy instead of showing an empty "通過" view.
      const matchesQuality = quality === 'all' || (stock.qualityProxyStatus ?? stock.qualityStatus) === quality
      const matchesStatus = status === 'all' || stock.dataStatus === status
      return matchesText && matchesMarket && matchesEntry && matchesQuality && matchesStatus
    })
    const stateOrder: Record<StockSummary['signalState'], number> = { '進場觀察': 0, '低位觀察': 1, '值得研究': 2, '待補資料': 3, '資料不足': 4, '條件失效': 5 }
    return [...list].sort((a, b) => {
      if (sort === 'z') return (a.zScore ?? Number.POSITIVE_INFINITY) - (b.zScore ?? Number.POSITIVE_INFINITY)
      if (sort === 'growth') return (b.revenueGrowth3m ?? Number.NEGATIVE_INFINITY) - (a.revenueGrowth3m ?? Number.NEGATIVE_INFINITY)
      if (sort === 'trust') return (b.participation10 ?? Number.NEGATIVE_INFINITY) - (a.participation10 ?? Number.NEGATIVE_INFINITY)
      return stateOrder[a.signalState] - stateOrder[b.signalState] || a.code.localeCompare(b.code)
    })
  }, [entry, market, quality, query, release, sort, status])

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value === 'all' || value === '') next.delete(key)
    else next.set(key, value)
    setParams(next)
  }

  const toggleCompare = (code: string) => setCompareCodes((current) => current.includes(code) ? current.filter((item) => item !== code) : current.length >= 4 ? current : [...current, code])
  const exportCsv = () => {
    const headers = ['代碼', '名稱', '市場', '產業', '狀態', '四年Z', '品質', '三月營收成長', '投信十日成交占比', '資料日', '公式版']
    const rows = filtered.map((stock) => [stock.code, stock.name, stock.market, stock.sector, stock.signalState, stock.zScore == null ? 'unknown' : stock.zScore.toFixed(4), stock.qualityStatus, stock.revenueGrowth3m == null ? 'unknown' : formatPct(stock.revenueGrowth3m), stock.participation10 == null ? 'unknown' : formatPct(stock.participation10), stock.asOf ?? '—', release!.formulaVersion])
    const csv = '\ufeff' + [headers, ...rows].map((row) => row.map((value) => csvCell(value)).join(',')).join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `screener-${release!.marketDate ?? 'snapshot'}.csv`; anchor.click(); URL.revokeObjectURL(url)
  }

  return <div className="page-stack"><PageTitle eyebrow="SCREENER / STATIC SNAPSHOT" title="選股器" description="前端搜尋、篩選與排序只作用於同次發布的靜態資料，不改正式策略或歷史績效。" actions={<><button className="button secondary" onClick={exportCsv}>匯出 CSV</button><Link className={`button primary ${compareCodes.length < 2 ? 'disabled-button' : ''}`} to={compareCodes.length >= 2 ? `/compare?symbols=${compareCodes.join(',')}` : '/compare'}>比較 {compareCodes.length}/4</Link></>} />
    <div className="filter-bar"><label className="filter-search"><span>⌕</span><input value={query} onChange={(event) => { setQuery(event.target.value); setFilter('q', event.target.value) }} placeholder="代碼、中文名、產業" /></label><FilterSelect label="市場" value={market} onChange={(value) => { setMarket(value); setFilter('market', value) }} options={[['all', '全部市場'], ['TWSE', '上市'], ['TPEx', '上櫃']]} /><FilterSelect label="入口" value={entry} onChange={(value) => { setEntry(value); setFilter('entry', value) }} options={[['all', '三路聯集'], ['投信', '投信關注'], ['成長', '成長改善'], ['低位', '低位品質']]} /><FilterSelect label="品質" value={quality} onChange={(value) => { setQuality(value); setFilter('quality', value) }} options={[['all', '全部狀態'], ['pass', '通過'], ['unknown', '未知'], ['fail', '未通過']]} /><FilterSelect label="資料" value={status} onChange={(value) => { setStatus(value); setFilter('status', value) }} options={[['all', '全部資料'], ['pass', '完整'], ['unknown', '待補／未知']]} /></div>
    <div className="list-toolbar"><span>符合 {filtered.length} 檔</span><div className="toolbar-right"><span className="muted">排序</span><select value={sort} onChange={(event) => { const value = event.target.value as typeof sort; setSort(value); setFilter('sort', value) }}><option value="state">狀態優先</option><option value="z">Z 值由低到高</option><option value="growth">營收成長</option><option value="trust">投信成交占比</option></select><span className="muted">資料日 {release!.marketDate ?? '—'}</span></div></div>
    <section className="panel table-panel"><StockTable stocks={filtered} compareCodes={compareCodes} onCompare={toggleCompare} watchlist={watchlist} onWatch={toggle} /></section>
    <div className="disclaimer">缺值顯示 unknown，不轉成 0；「比較」最多 4 檔，只比較同口徑欄位。CSV 已加 BOM 並防止試算表公式注入。</div>
  </div>
}

function FilterSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: Array<[string, string]> }) {
  return <label className="filter-select"><span>{label}</span><select value={value} onChange={(event) => onChange(event.target.value)}>{options.map(([option, text]) => <option key={option} value={option}>{text}</option>)}</select></label>
}

function csvCell(value: string) {
  const safe = /^[=+\-@]/.test(value) ? `'${value}` : value
  return `"${safe.replaceAll('"', '""')}"`
}

function RankingsPage() {
  const { release } = useData()
  const [params, setParams] = useSearchParams()
  const tabParam = params.get('tab')
  const tab = tabParam === 'growth' || tabParam === 'quality' || tabParam === 'lowPosition' || tabParam === 'lowBase' || tabParam === 'lowBaseGrowth' || tabParam === 'lowBaseQuality' ? tabParam : 'trust'
  const period = params.get('period') || '10'
  const lowBaseEligible = (stock: StockSummary) => Number.isFinite(stock.zScore) && stock.zScore! <= -1 && Number.isFinite(stock.slope) && stock.slope! > 0
  const qualityPasses = (stock: StockSummary) => stock.qualityProxyPassCount ?? 0
  const qualityRows: RankingRow[] = [...release!.stocks]
    .filter((stock) => stock.qualityProxyPassCount != null)
    .sort((a, b) => qualityPasses(b) - qualityPasses(a) || (b.revenueGrowth3m ?? Number.NEGATIVE_INFINITY) - (a.revenueGrowth3m ?? Number.NEGATIVE_INFINITY) || a.code.localeCompare(b.code))
    .map((stock, index) => ({
      rank: index + 1,
      code: stock.code,
      name: stock.name,
      sector: stock.sector,
      value: qualityPasses(stock),
      valueLabel: '/5',
      status: qualityPasses(stock) >= 4 ? 'pass' : stock.qualityProxyStatus === 'unknown' ? 'unknown' : 'fail',
      proxy: true,
      reason: `${stock.qualityProxyReason ?? '品質代理尚未完成'}；正式三年品質條件仍需逐期財報驗證。`,
    }))
  const lowBaseRows: RankingRow[] = [...release!.stocks]
    .filter(lowBaseEligible)
    .filter((stock) => stock.growthProxyStatus === 'pass' || qualityPasses(stock) >= 4)
    .sort((a, b) => (b.participation10 ?? Number.NEGATIVE_INFINITY) - (a.participation10 ?? Number.NEGATIVE_INFINITY) || (a.zScore ?? Number.POSITIVE_INFINITY) - (b.zScore ?? Number.POSITIVE_INFINITY))
    .map((stock, index) => ({ rank: index + 1, code: stock.code, name: stock.name, sector: stock.sector, value: stock.zScore, valueLabel: '', status: 'pass', proxy: true, reason: `Z ${stock.zScore?.toFixed(2)} ≤ -1、斜率為正；${stock.growthProxyStatus === 'pass' ? '成長代理通過' : `品質代理 ${qualityPasses(stock)}/5 通過`}。投信只作排序參考，不是硬門檻。` }))
  const lowBaseGrowthRows: RankingRow[] = [...release!.stocks]
    .filter(lowBaseEligible)
    .filter((stock) => stock.growthProxyStatus === 'pass')
    .sort((a, b) => (b.revenueGrowth3m ?? Number.NEGATIVE_INFINITY) - (a.revenueGrowth3m ?? Number.NEGATIVE_INFINITY) || (a.zScore ?? Number.POSITIVE_INFINITY) - (b.zScore ?? Number.POSITIVE_INFINITY))
    .map((stock, index) => ({ rank: index + 1, code: stock.code, name: stock.name, sector: stock.sector, value: stock.zScore, valueLabel: '', status: 'pass', proxy: true, reason: `低基期成長：Z ${stock.zScore?.toFixed(2)} ≤ -1、斜率為正、三月合計營收年增 ${formatPct(stock.revenueGrowth3m)} ≥ 15%。` }))
  const lowBaseQualityRows: RankingRow[] = [...release!.stocks]
    .filter(lowBaseEligible)
    .filter((stock) => qualityPasses(stock) >= 4)
    .sort((a, b) => qualityPasses(b) - qualityPasses(a) || (a.zScore ?? Number.POSITIVE_INFINITY) - (b.zScore ?? Number.POSITIVE_INFINITY))
    .map((stock, index) => ({ rank: index + 1, code: stock.code, name: stock.name, sector: stock.sector, value: stock.zScore, valueLabel: '', status: 'pass', proxy: true, reason: `低基期品質：Z ${stock.zScore?.toFixed(2)} ≤ -1、斜率為正、品質代理 ${qualityPasses(stock)}/5 通過。` }))
  const rows = tab === 'growth' ? release!.rankings.growth : tab === 'quality' ? qualityRows : tab === 'lowPosition' ? release!.rankings.lowPosition : tab === 'lowBaseGrowth' ? lowBaseGrowthRows : tab === 'lowBaseQuality' ? lowBaseQualityRows : tab === 'lowBase' ? lowBaseRows : release!.rankings.trust
  const setTab = (value: string) => { const next = new URLSearchParams(params); next.set('tab', value); setParams(next) }
  const setPeriod = (value: string) => { const next = new URLSearchParams(params); next.set('period', value); setParams(next) }
  const heading = tab === 'trust' ? '投信關注' : tab === 'growth' ? '成長改善' : tab === 'quality' ? '品質代理' : tab === 'lowPosition' ? '低位品質' : tab === 'lowBaseGrowth' ? '低基期成長' : tab === 'lowBaseQuality' ? '低基期品質' : '低基期策略'
  return <div className="page-stack"><PageTitle eyebrow="RANKINGS / TRACKED UNIVERSE" title="排行榜" description={`${release!.coverage.scopeLabel ?? '本次發布追蹤範圍'}。榜單是研究入口，不是下單訊號。`} actions={<Link className="button secondary" to="/screener">用選股器篩選</Link>} /><div className="tab-row" role="tablist">{[['trust', '投信關注'], ['growth', '成長改善'], ['quality', '品質代理'], ['lowPosition', '低位品質'], ['lowBaseGrowth', '低基期成長'], ['lowBaseQuality', '低基期品質'], ['lowBase', '低基期聯集']].map(([value, label]) => <button key={value} className={tab === value ? 'tab active' : 'tab'} onClick={() => setTab(value)}>{label}</button>)}<span className="tab-spacer" />{['1', '5', '10', '20'].map((value) => <button key={value} className={period === value ? 'period-chip active' : 'period-chip'} onClick={() => setPeriod(value)}>{value}日</button>)}</div><section className="panel"><div className="section-heading"><div><span className="eyebrow">{period} TRADING SESSIONS</span><h2>{heading} <span className="count-badge">{rows.length}</span></h2></div><span className="muted">可取得資料排名 · 資料日 {release!.marketDate ?? '—'}</span></div>{['lowBase', 'lowBaseGrowth', 'lowBaseQuality'].includes(tab) && <div className="callout info"><span className="callout-icon">i</span><p>低基期入口要求四年 Z ≤ -1 且斜率為正；成長與品質分開成榜，投信動向只用來排序，不阻擋未被法人買進的低基期公司。代理只作研究入口，正式條件另行驗證。</p></div>}{tab === 'quality' && <div className="callout info"><span className="callout-icon">i</span><p>品質代理以最新可得年度五項檢查排序；4/5 以上顯示為代理通過。正式三年 point-in-time 財報條件仍會保留為獨立狀態。</p></div>}{period !== '10' && tab === 'trust' && <div className="callout warning"><span className="callout-icon">!</span><p>目前發布的投信口徑保存十個市場交易日；其他期間切換只改介面篩選，沒有把較短資料冒充完整窗口。</p></div>}<RankingTable rows={rows} tab={tab} /></section><div className="disclaimer">投信榜顯示股數與該股十日成交占比；成長榜是三月營收代理；品質榜是最新年度代理；低基期榜是價格回歸代理。正式條件與代理證據分開。</div></div>
}

function RankingTable({ rows, tab }: { rows: RankingRow[]; tab: string }) {
  if (!rows.length) return <EmptyState title="這個入口目前沒有可發布排行" body="可能是資料覆蓋不足或來源完整性閘門未通過。查看方法與資料頁，不把缺資料當成零名次。" />
  return <div className="table-wrap"><table className="ranking-table"><thead><tr><th>排名</th><th>標的</th><th>產業</th><th>{tab === 'trust' ? '十日淨買超／成交占比' : tab === 'growth' ? '三月合計營收年增' : tab === 'quality' ? '品質代理' : '四年 Z'}</th><th>狀態</th><th>說明</th></tr></thead><tbody>{rows.map((row) => <tr key={row.code}><td><span className="rank-number">{String(row.rank).padStart(2, '0')}</span></td><td><Link className="stock-code" to={`/stocks/${row.code}`}>{row.code}</Link><strong className="ranking-name">{row.name}</strong></td><td>{row.sector || '—'}</td><td className="number-cell">{row.value == null ? '—' : `${formatNumber(row.value, tab === 'lowPosition' || tab === 'lowBase' || tab === 'lowBaseGrowth' || tab === 'lowBaseQuality' ? 2 : row.valueLabel.includes('%') ? 2 : 0)}${row.valueLabel}`}</td><td><StatusPill status={row.status} label={row.proxy ? `代理 ${statusLabels[row.status]}` : undefined} /></td><td className="reason-cell"><p>{row.reason}</p><Link className="table-sub text-link" to={`/stocks/${row.code}`}>查看逐項證據 →</Link></td></tr>)}</tbody></table></div>
}

function StockPage() {
  const { code = '' } = useParams()
  const { release, getStock } = useData()
  const summary = release!.stocks.find((stock) => stock.code === code)
  const { watchlist, toggle } = useWatchlist()
  const [detail, setDetail] = useState<StockDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [historyDate, setHistoryDate] = useState('')

  useEffect(() => {
    let cancelled = false
    if (!summary) return
    setDetail(null); setError(null)
    getStock(code).then((value) => { if (!cancelled) setDetail(value) }).catch((reason: unknown) => { if (!cancelled) setError(reason instanceof Error ? reason.message : '個股資料不可用') })
    return () => { cancelled = true }
  }, [code, getStock, summary])

  if (!summary) return <div className="page-stack"><EmptyState title="找不到這檔股票" body="代碼可能尚未建庫，或不在本次發布母體。搜尋結果不會虛構個股資料。" action={<Link className="button secondary" to="/screener">回到選股器</Link>} /></div>
  const snapshot = historyDate ? detail?.historySnapshots.find((item) => item.date === historyDate) : null
  return <div className="page-stack"><PageTitle eyebrow={`STOCK / ${summary.code}`} title={<span className="stock-heading"><span>{summary.name}</span><small>{summary.code} · {summary.market} · {summary.sector || '產業未填'}</small></span>} description="個股頁把當期回歸、歷史摘要、財務條件與來源證據分開。" actions={<><button className={`button secondary ${watchlist.includes(summary.code) ? 'saved-button' : ''}`} onClick={() => toggle(summary.code)}>{watchlist.includes(summary.code) ? '★ 已在自選' : '☆ 加入自選'}</button><Link className="button primary" to={`/compare?symbols=${summary.code}`}>加入比較</Link><a className="button secondary" href={`https://statementdog.com/analysis/${summary.code}`} target="_blank" rel="noreferrer">財報狗 ↗</a></>} /><div className="stock-hero-grid"><section className="panel quote-panel"><div className="quote-label">最新可用報價 · {summary.asOf ?? '—'}</div><div className="quote-price">{formatNumber(summary.lastPrice, 2)}</div><div className={summary.changePct != null && summary.changePct >= 0 ? 'market-up quote-change' : 'market-down quote-change'}>{summary.changePct == null ? '—' : `${summary.changePct >= 0 ? '+' : ''}${summary.changePct.toFixed(2)}%`} <span>日變化</span></div><div className="quote-status"><SignalState state={summary.signalState} /><StatusPill status={summary.dataStatus} /></div></section><section className="panel metric-grid-panel"><MetricCell label="四年 Z" value={summary.zScore?.toFixed(2) ?? null} status={summary.fiveLineStatus} detail={`研究價格：${summary.priceBasis === 'adjusted' ? 'yfinance Adj Close' : '未調整收盤代理'}`} /><MetricCell label="投信十日成交占比" value={summary.participation10 == null ? null : (summary.participation10 * 100).toFixed(2)} unit="%" status={summary.participation10 == null ? 'unknown' : 'pass'} /><MetricCell label="三月營收年增" value={summary.revenueGrowth3m == null ? null : (summary.revenueGrowth3m * 100).toFixed(1)} unit="%" status={summary.growthProxyStatus ?? summary.growthStatus} detail="營收代理；正式營業利益成長另列" /></section></div>{error && <div className="callout danger"><span className="callout-icon">!</span><p>{error}。摘要仍保留，但不以最新回歸補寫歷史。</p></div>}{!detail && !error && <div className="panel loading-panel">正在載入個股快照…</div>}{detail && <><section className="panel"><div className="section-heading"><div><span className="eyebrow">CURRENT FOUR-YEAR FIT</span><h2>本期四年回歸</h2></div><StatusPill status={detail.regression.status} label={detail.regression.signalEligible ? '可作正式計算' : `行情可看／${detail.regression.label}`} /></div><div className="callout info"><span className="callout-icon">i</span><p>{detail.regression.reason} <strong>{detail.regression.method}</strong>。覆蓋 {detail.regression.coveragePct == null ? '—' : `${detail.regression.coveragePct.toFixed(1)}%`}；資料 {detail.regression.historyStart ?? '—'} 至 {detail.regression.historyEnd ?? '—'}。</p></div><LineChart points={detail.priceSeries} priceBasis={detail.regression.priceBasis} /></section><div className="detail-grid"><section className="panel"><div className="section-heading"><div><span className="eyebrow">FORMAL RULE CHECKS</span><h2>正式條件檢查</h2></div></div><RuleList rules={detail.qualityChecks} />{detail.qualityProxyChecks?.length ? <><div className="section-heading proxy-heading"><div><span className="eyebrow">AVAILABLE PROXIES</span><h2>可取得替代指標</h2></div></div><RuleList rules={detail.qualityProxyChecks} /></> : null}</section><section className="panel"><div className="section-heading"><div><span className="eyebrow">INSTITUTION / REVENUE</span><h2>營運與法人</h2></div></div><MiniBars label="投信每日淨股數" values={detail.institutionalDaily.map((point) => point.netShares)} /><MiniBars label="月營收（原始單位）" values={detail.revenueMonthly.slice(-12).map((point) => point.revenue)} /></section></div><section className="panel"><div className="section-heading"><div><span className="eyebrow">POINT-IN-TIME SNAPSHOTS</span><h2>已保存的歷史摘要</h2></div><span className="muted">不使用今天的回歸線回頭判斷</span></div>{detail.historySnapshots.length ? <div className="history-row"><label>查閱日期<select value={historyDate} onChange={(event) => setHistoryDate(event.target.value)}><option value="">選擇已保存日期</option>{detail.historySnapshots.map((item) => <option key={item.date} value={item.date}>{item.date}</option>)}</select></label>{snapshot ? <div className="history-result"><span>{snapshot.date}</span><strong>Z {snapshot.z == null ? '—' : snapshot.z.toFixed(2)}</strong><SignalState state={snapshot.state as StockSummary['signalState']} /><p>{snapshot.reason}</p></div> : <p className="muted history-help">只顯示確實保存的當日 Z、五線末端與訊號摘要；未保存日期不回填。</p>}</div> : <EmptyState title="尚無歷史摘要" body="這檔股票尚未累積可重現的 point-in-time 快照。" />}</section><div className="limitations-list">{detail.detailLimitations.map((item) => <span key={item}>• {item}</span>)}</div></>}</div>
}

function RuleList({ rules }: { rules: RuleCheck[] }) {
  return <div className="rule-list">{rules.map((rule) => <details className="rule-row" key={rule.label}><summary><StatusPill status={rule.status} /><strong>{rule.label}</strong><span>{rule.value}</span><span className="rule-chevron">＋</span></summary><div className="rule-detail"><p>{rule.explanation}</p><span>期間：{rule.period} · 來源：{rule.sourceRefs.join('、') || '未提供'}</span></div></details>)}</div>
}

function MiniBars({ label, values }: { label: string; values: Array<number | null> }) {
  const usable = values.filter((value): value is number => value != null && Number.isFinite(value))
  const max = Math.max(...usable.map((value) => Math.abs(value)), 1)
  return <div className="mini-bars"><div className="mini-bars-heading"><span>{label}</span><span>{usable.length ? `最近 ${usable.length} 筆` : 'unknown'}</span></div><div className="bars" aria-label={label}>{values.slice(-20).map((value, index) => <span key={`${index}-${value}`} className={value != null && value >= 0 ? 'bar positive' : 'bar negative'} style={{ height: `${value == null ? 3 : Math.max(5, Math.abs(value) / max * 100)}%` }} title={value == null ? 'unknown' : formatNumber(value, 0)} />)}</div></div>
}

function ComparePage() {
  const { release } = useData()
  const [params, setParams] = useSearchParams()
  const requested = (params.get('symbols') ?? '').split(',').map((item) => item.trim()).filter(Boolean)
  const selected = requested.filter((code) => release!.stocks.some((stock) => stock.code === code)).slice(0, 4)
  const selectionRef = useRef<string[]>(selected)
  useEffect(() => { selectionRef.current = selected }, [params, release, selected])
  const add = (code: string) => {
    const current = selectionRef.current
    const next = current.includes(code) ? current.filter((item) => item !== code) : current.length >= 4 ? current : [...current, code]
    selectionRef.current = next
    setParams({ symbols: next.join(',') })
  }
  const copyUrl = async () => { await navigator.clipboard?.writeText(window.location.href); window.alert('比較 URL 已複製；不含私人筆記與交易紀錄。') }
  const compared = selected.map((code) => release!.stocks.find((stock) => stock.code === code)!).filter(Boolean)
  return <div className="page-stack"><PageTitle eyebrow="COMPARE / SAME SNAPSHOT" title="比較工作台" description="最多 4 檔。共同欄位會保留資料期間與 unknown，不把不同口徑的數字硬湊成分數。" actions={<button className="button secondary" onClick={copyUrl} disabled={selected.length < 2}>複製比較 URL</button>} /><section className="panel"><div className="section-heading"><div><span className="eyebrow">SELECT 2—4</span><h2>選擇標的 <span className="count-badge">{selected.length}/4</span></h2></div><Link className="text-link" to="/screener">從選股器加入 →</Link></div><div className="compare-picker">{release!.stocks.slice(0, 12).map((stock) => <button key={stock.code} className={selected.includes(stock.code) ? 'picker-card selected' : 'picker-card'} onClick={() => add(stock.code)}><span>{selected.includes(stock.code) ? '✓' : '＋'}</span><strong>{stock.code}</strong><small>{stock.name}</small></button>)}</div></section>{selected.length < 2 ? <EmptyState title="至少選 2 檔開始比較" body="選擇同一發布中的標的。私人筆記與交易紀錄不會進入 URL。" /> : <section className="panel compare-panel"><div className="compare-grid"><div className="compare-label-col"><span>欄位</span><strong>狀態</strong><span>最新價</span><span>四年 Z</span><span>品質</span><span>成長</span><span>投信占比</span><span>主要風險</span></div>{compared.map((stock) => <div className="compare-column" key={stock.code}><Link to={`/stocks/${stock.code}`} className="compare-stock"><span>{stock.code}</span><strong>{stock.name}</strong></Link><SignalState state={stock.signalState} /><span className="compare-value">{formatNumber(stock.lastPrice, 2)}</span><span className="compare-value">{stock.zScore == null ? '—' : stock.zScore.toFixed(2)} <small>{statusLabels[stock.fiveLineStatus]}</small></span><StatusPill status={stock.qualityStatus} /><span className="compare-value">{formatPct(stock.revenueGrowth3m)} <small>{statusLabels[stock.growthStatus]}</small></span><span className="compare-value">{formatPct(stock.participation10)} <small>十日</small></span><span className="compare-risk">{stock.risks[0] ?? '—'}</span></div>)}</div></section>}</div>
}

function JournalPage() {
  const { release } = useData()
  const { state, ready, saving, update } = useJournalState()
  const [selectedCode, setSelectedCode] = useState(state.watchlist[0] ?? release!.stocks[0]?.code ?? '')
  const [note, setNote] = useState('')
  const [tradeForm, setTradeForm] = useState({ code: release!.stocks[0]?.code ?? '', action: 'buy' as TradeEntry['action'], date: release!.marketDate ?? new Date().toISOString().slice(0, 10), shares: '', price: '', amount: '', note: '' })
  const [message, setMessage] = useState('')

  useEffect(() => { if (ready) { setSelectedCode(state.watchlist[0] ?? release!.stocks[0]?.code ?? ''); setNote(state.notes[state.watchlist[0] ?? release!.stocks[0]?.code ?? ''] ?? '') } }, [ready])
  useEffect(() => { setNote(state.notes[selectedCode] ?? '') }, [selectedCode, state.notes])

  const currentMonth = (release!.marketDate ?? new Date().toISOString().slice(0, 10)).slice(0, 7)
  const currentYear = currentMonth.slice(0, 4)
  const buys = state.trades.filter((trade) => trade.action === 'buy' || trade.action === 'add')
  const monthCount = new Set(buys.filter((trade) => trade.date.startsWith(currentMonth)).map((trade) => trade.decisionId)).size
  const yearCount = new Set(buys.filter((trade) => trade.date.startsWith(currentYear)).map((trade) => trade.decisionId)).size
  const saveNote = async () => { await update({ ...state, notes: { ...state.notes, [selectedCode]: note } }); setMessage('筆記已保存於本機') }
  const toggleWatch = async (code: string) => { await update({ ...state, watchlist: state.watchlist.includes(code) ? state.watchlist.filter((item) => item !== code) : [...state.watchlist, code] }); setMessage('自選已更新；不會送入每日批次') }
  const submitTrade = async (event: FormEvent) => { event.preventDefault(); const entry: TradeEntry = { id: crypto.randomUUID?.() ?? `${Date.now()}`, decisionId: `${tradeForm.date}-${tradeForm.code}-${tradeForm.action}`, code: tradeForm.code, name: release!.stocks.find((stock) => stock.code === tradeForm.code)?.name ?? '', action: tradeForm.action, date: tradeForm.date, shares: tradeForm.shares ? Number(tradeForm.shares) : null, price: tradeForm.price ? Number(tradeForm.price) : null, amount: tradeForm.amount ? Number(tradeForm.amount) : null, note: tradeForm.note }; await update({ ...state, trades: [entry, ...state.trades] }); setTradeForm((current) => ({ ...current, shares: '', price: '', amount: '', note: '' })); setMessage('紀律紀錄已加入本機') }
  const removeTrade = async (id: string) => update({ ...state, trades: state.trades.filter((trade) => trade.id !== id) })
  const download = () => { const url = URL.createObjectURL(new Blob([exportJournal(state)], { type: 'application/json' })); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `taiwan-stock-journal-${new Date().toISOString().slice(0, 10)}.json`; anchor.click(); URL.revokeObjectURL(url) }
  const importFile = (event: ChangeEvent<HTMLInputElement>) => { const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onload = async () => { try { await update(parseJournalImport(String(reader.result))); setMessage('備份已匯入本機') } catch (reason: unknown) { setMessage(reason instanceof Error ? reason.message : '匯入失敗') } }; reader.readAsText(file); event.target.value = '' }
  const saveScenario = async () => { await update({ ...state, scenario: { ...state.scenario } }); setMessage('使用者情境已保存，不影響正式訊號') }

  if (!ready) return <div className="page-stack"><div className="panel loading-panel">正在開啟本機 IndexedDB…</div></div>
  return <div className="page-stack"><PageTitle eyebrow="JOURNAL / LOCAL ONLY" title="自選與紀律" description="自選、筆記與交易流水只保存在這台瀏覽器。沒有雲端同步，也不會回傳批次。" actions={<><button className="button secondary" onClick={download}>匯出 JSON</button><label className="button secondary file-button">匯入備份<input type="file" accept="application/json" onChange={importFile} /></label></>} />{message && <div className="toast" role="status">{message}</div>}<section className="stat-grid journal-stats"><StatCard label="本月買進／加碼" value={`${monthCount} / 2`} detail="同 decision_id 合併；賣出與股息不算" tone={monthCount > 2 ? 'red' : 'blue'} /><StatCard label="本年買進／加碼" value={`${yearCount} / 24`} detail="不因每日篩選而自動增加" /><StatCard label="自選檔數" value={state.watchlist.length} detail="本機清單；未建庫會明示" tone="neutral" /><StatCard label="保存狀態" value={saving ? '寫入中' : '已保存'} detail="IndexedDB（不支援時使用本機 fallback）" tone="green" /></section><div className="journal-grid"><section className="panel"><div className="section-heading"><div><span className="eyebrow">WATCHLIST</span><h2>我的自選</h2></div></div>{state.watchlist.length ? <div className="watchlist">{state.watchlist.map((code) => { const stock = release!.stocks.find((item) => item.code === code); return <div className="watch-row" key={code}><button className={selectedCode === code ? 'watch-select active' : 'watch-select'} onClick={() => setSelectedCode(code)}><strong>{code}</strong><span>{stock?.name ?? '尚未建庫'}</span></button><Link to={`/stocks/${code}`} className="text-link">查看</Link><button className="icon-button subtle" onClick={() => toggleWatch(code)} aria-label={`移除 ${code}`}>×</button></div> })}</div> : <EmptyState title="還沒有自選" body="在今日研究或個股頁按 ☆。自選不會改變批次追蹤設定。" />}</section><section className="panel note-panel"><div className="section-heading"><div><span className="eyebrow">RESEARCH NOTE</span><h2>{selectedCode || '選一檔'} 的研究筆記</h2></div><span className="local-label">LOCAL</span></div><textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="記錄研究理由、否決原因、待查資料…" aria-label="研究筆記" /><div className="form-footer"><span className="muted">內容不會送至伺服器</span><button className="button primary" onClick={saveNote}>保存筆記</button></div></section></div><section className="panel"><div className="section-heading"><div><span className="eyebrow">TRADE LOG</span><h2>交易流水</h2></div><span className="muted">日終紀律紀錄，不是券商連線</span></div><form className="trade-form" onSubmit={submitTrade}><label>代碼<select value={tradeForm.code} onChange={(event) => setTradeForm({ ...tradeForm, code: event.target.value })}>{release!.stocks.map((stock) => <option key={stock.code} value={stock.code}>{stock.code} {stock.name}</option>)}</select></label><label>動作<select value={tradeForm.action} onChange={(event) => setTradeForm({ ...tradeForm, action: event.target.value as TradeEntry['action'] })}><option value="buy">買進</option><option value="add">加碼</option><option value="sell">賣出</option><option value="dividend">股息</option><option value="fee">費用</option><option value="deposit">入金</option><option value="withdrawal">出金</option><option value="split">分割</option></select></label><label>日期<input type="date" value={tradeForm.date} onChange={(event) => setTradeForm({ ...tradeForm, date: event.target.value })} /></label><label>股數<input inputMode="numeric" value={tradeForm.shares} onChange={(event) => setTradeForm({ ...tradeForm, shares: event.target.value })} placeholder="可空" /></label><label>價格<input inputMode="decimal" value={tradeForm.price} onChange={(event) => setTradeForm({ ...tradeForm, price: event.target.value })} placeholder="可空" /></label><label>金額<input inputMode="decimal" value={tradeForm.amount} onChange={(event) => setTradeForm({ ...tradeForm, amount: event.target.value })} placeholder="可空" /></label><label className="wide-field">備註<input value={tradeForm.note} onChange={(event) => setTradeForm({ ...tradeForm, note: event.target.value })} placeholder="成交、滑價、原因" /></label><button className="button primary" type="submit">加入紀錄</button></form>{state.trades.length ? <div className="table-wrap"><table className="trade-table"><thead><tr><th>日期</th><th>標的</th><th>動作</th><th>股數</th><th>價格</th><th>金額</th><th>decision_id</th><th /></tr></thead><tbody>{state.trades.map((trade) => <tr key={trade.id}><td>{trade.date}</td><td>{trade.code} {trade.name}</td><td>{tradeActionLabel[trade.action]}</td><td>{formatNumber(trade.shares, 0)}</td><td>{formatNumber(trade.price, 2)}</td><td>{formatNumber(trade.amount, 0)}</td><td><code>{trade.decisionId}</code></td><td><button className="text-button danger-text" onClick={() => removeTrade(trade.id)}>刪除</button></td></tr>)}</tbody></table></div> : <EmptyState title="尚無交易紀錄" body="可以先記錄研究決策；股息、公司行動與買進次數會分開處理。" />}</section><section className="panel scenario-panel"><div className="section-heading"><div><span className="eyebrow">USER SCENARIO</span><h2>使用者情境試算</h2></div><span className="local-label">不改正式模型</span></div><div className="scenario-form"><label>估值假設<input value={state.scenario.valuation} onChange={(event) => update({ ...state, scenario: { ...state.scenario, valuation: event.target.value } })} placeholder="例如：2027 EPS × 18" /></label><label>停損距離 <strong>{state.scenario.stopLossPct}%</strong><input type="range" min="1" max="30" value={state.scenario.stopLossPct} onChange={(event) => update({ ...state, scenario: { ...state.scenario, stopLossPct: Number(event.target.value) } })} /></label><label>備註<textarea value={state.scenario.note} onChange={(event) => update({ ...state, scenario: { ...state.scenario, note: event.target.value } })} placeholder="使用者自己的風險假設" /></label></div><div className="form-footer"><span className="muted">正式停損基準仍為計畫版本；這裡只保存你的情境。</span><button className="button secondary" onClick={saveScenario}>保存情境</button></div></section></div>
}

const tradeActionLabel: Record<TradeEntry['action'], string> = { buy: '買進', add: '加碼', sell: '賣出', dividend: '股息', fee: '費用', deposit: '入金', withdrawal: '出金', split: '分割' }

function ResearchPage() {
  const { release } = useData()
  const result = release!.research
  return <div className="page-stack"><PageTitle eyebrow="RESEARCH / P5 IN PROGRESS" title="策略檢驗" description="軟體完成與策略有效分開。資料不足時顯示 not_evaluable，不用示範績效填空。" actions={<Link className="button secondary" to="/methodology">看研究協議</Link>} /><section className="research-banner"><div className="research-status">{result.status}</div><div><h2>{result.status === 'not_evaluable' ? '目前尚不能評估投資目標' : '研究結果已鎖定'}</h2><p>{result.reason}</p></div></section><div className="stat-grid"><StatCard label="CAGR" value={result.cagr == null ? '—' : formatPct(result.cagr)} detail="只用整體 NAV，不用個股平均漲幅" /><StatCard label="最大回撤" value={result.maxDrawdown == null ? '—' : formatPct(result.maxDrawdown)} detail="含現金、資金流調整後" tone="amber" /><StatCard label="目標" value="50% / 30%" detail="研究挑戰目標，不是保證或上線門檻" tone="neutral" /></div><section className="panel"><div className="section-heading"><div><span className="eyebrow">FIXED PROTOCOL</span><h2>研究必須留下的證據</h2></div></div><div className="protocol-grid"><ProtocolItem number="01" title="時間隔離" body="2014—2019 開發、2020—2022 驗證、2023—2025 保留測試；資料不足就標缺口。" /><ProtocolItem number="02" title="消融比較" body="只投信、三入口無轉強、完整策略與全市場基準分開，不挑最好版本。" /><ProtocolItem number="03" title="可得性" body="財報使用當時可得版本；沒有公告日的歷史資料標 approximate_availability。" /><ProtocolItem number="04" title="成交約束" body="收盤後訊號，下一可交易日執行；跳空、停牌、漲跌停不虛構成交。" /></div></section><section className="panel"><div className="section-heading"><div><span className="eyebrow">RECORDED RESULTS</span><h2>已發布研究區間</h2></div></div>{result.periods.length ? <div className="table-wrap"><table className="ranking-table"><thead><tr><th>區間</th><th>狀態</th><th>CAGR</th><th>MDD</th><th>買進／加碼</th></tr></thead><tbody>{result.periods.map((period) => <tr key={period.label}><td>{period.label}</td><td>{period.status}</td><td>{period.cagr == null ? '—' : formatPct(period.cagr)}</td><td>{period.maxDrawdown == null ? '—' : formatPct(period.maxDrawdown)}</td><td>{period.trades ?? '—'}</td></tr>)}</tbody></table></div> : <EmptyState title="尚無可稽核回測結果" body="先完成 point-in-time 母體、財報可得時間、公司行動、成本與成交限制；不以短期示範績效代替。" />}</section><div className="disclaimer">投資目標狀態只能是 achieved／not_achieved／not_evaluable。軟體介面上線，不代表年化 50% 或回撤 30% 已達成。</div></div>
}

function ProtocolItem({ number, title, body }: { number: string; title: string; body: string }) {
  return <div className="protocol-item"><span>{number}</span><div><h3>{title}</h3><p>{body}</p></div></div>
}

function MethodologyPage() {
  return <div className="page-stack"><PageTitle eyebrow="METHOD / DATA CONTRACT" title="方法與資料" description="公式、閾值與來源界線公開；任何未知欄位保留未知，不靠文案補齊。" actions={<Link className="button secondary" to="/research">看策略檢驗</Link>} /><section className="panel method-intro"><div className="method-quote">「值得研究」不是「應該買」。</div><p>本站用四年線性回歸、投信十個市場交易日、營收改善與財務品質代理整理研究順序。回歸中線不是合理價，品質條件也不是已證明的護城河。</p></section><div className="method-grid"><MethodCard title="四年五線譜" label="lohas-linear-4y-v1" body={<><p>在觀察日以前的四個日曆年，對有效調整後收盤價做線性 OLS；殘差標準差使用母體 ddof=0。</p><pre>{`b = Σ((x−x̄)(y−ȳ)) / Σ((x−x̄)²)\na = ȳ − b·x̄\nσ = √(Σe² / n)\nZ = (y_last − mid) / σ`}</pre></>} /><MethodCard title="投信窗口" label="10 market sessions" body={<><p>只使用連續十個市場交易日，窗口含 0 與賣超日。分母是同一檔股票十日成交股數總和。</p><pre>{`net = Σ(buy_shares − sell_shares)\nparticipation = net / Σ(stock_volume)`}</pre></>} /><MethodCard title="品質與成長" label="quality-growth-v1" body={<><p>品質代理是最新可得年度五項檢查，至少 4/5 才能作為低基期品質入口；正式條件仍是三年獲利、CFO、ROE 與負債口徑。成長入口要求三月合計營收年增至少 15%。</p><p className="muted">金融業可搜尋，但非金融規則標 not_applicable。</p></>} /><MethodCard title="進場觀察" label="research signal" body={<><p>品質與對應分組通過、四年斜率正、最近八個已結束交易週曾 Z≤−1、目前 Z≤0、最新完整週收盤高於十週均線。</p><p className="warning-text">這是研究訊號，不是券商下單或報酬保證。</p></>} /><MethodCard title="低基期策略" label="institution + z + proxy" body={<><p>低基期成長：Z ≤ -1、斜率為正、成長代理通過；低基期品質：Z ≤ -1、斜率為正、品質代理至少 4/5。投信動向只作排序參考，不再是硬門檻。</p><p className="muted">目前只對已建庫標的計算；未建庫股票不會被猜測補入。</p></>} /></div><section className="panel"><div className="section-heading"><div><span className="eyebrow">SOURCE REGISTRY</span><h2>四個金融來源</h2></div><span className="muted">目前發布器使用 FinMind 與 yfinance，來源隨快照保存</span></div><div className="source-grid"><SourceRow name="FinMind" use="按股歷史價量、法人、月營收、財報、公司行動" limit="免費／付費能力分開；財報期末不等於公告時間" href="https://finmind.github.io/" /><SourceRow name="TWSE" use="上市母體、行情、法人與批次資料" limit="每個 OpenAPI 欄位與日期需實測" href="https://openapi.twse.com.tw/" /><SourceRow name="TPEx" use="上櫃對應資料" limit="完整法人報表可取性另做 runner smoke" href="https://www.tpex.org.tw/openapi/" /><SourceRow name="yfinance" use="發布器端調整後價格與最新年度財務代理" limit="來源與期間隨快照保存；不把代理誤稱為正式條件" href="https://github.com/ranaroussi/yfinance" /></div></section><section className="panel status-guide"><div className="section-heading"><div><span className="eyebrow">MISSING DATA SEMANTICS</span><h2>狀態不是裝飾</h2></div></div><div className="status-guide-grid"><StatusGuide status="pass" body="來源與條件已通過。" /><StatusGuide status="fail" body="資料存在，但條件沒有通過。" /><StatusGuide status="unknown" body="缺資料、缺日期或來源不完整；不等於 0。" /><StatusGuide status="not_applicable" body="該規則對此產業不適用。" /></div></section><div className="source-links"><a href="https://finmind.github.io/api_usage_count/" target="_blank" rel="noreferrer">FinMind 用量說明 ↗</a><a href="https://finmind.github.io/Disclaimer/" target="_blank" rel="noreferrer">FinMind 免責與授權 ↗</a><a href="https://developers.cloudflare.com/pages/" target="_blank" rel="noreferrer">Cloudflare Pages 文件 ↗</a></div></div>
}

function MethodCard({ title, label, body }: { title: string; label: string; body: ReactNode }) { return <article className="method-card"><span className="eyebrow">{label}</span><h2>{title}</h2>{body}</article> }
function SourceRow({ name, use, limit, href }: { name: string; use: string; limit: string; href: string }) { return <div className="source-row"><strong>{name}</strong><span>{use}</span><small>{limit}</small><a href={href} target="_blank" rel="noreferrer">文件 ↗</a></div> }
function StatusGuide({ status, body }: { status: MetricStatus; body: string }) { return <div className="status-guide-item"><StatusPill status={status} /><p>{body}</p></div> }

function NotFoundPage() { return <div className="page-stack"><EmptyState title="頁面不存在" body="回到今日研究或使用左側導覽。" action={<Link className="button primary" to="/">回到首頁</Link>} /></div> }

export function AppForTest() { return <App /> }
