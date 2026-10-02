import { useEffect, useMemo, useRef, useState } from 'react'
import type { ScreeningHistoryIndex, ScreeningHistoryRecord } from '../domain/types'
import { filterHistoryRows, loadHistoryIndex, loadHistoryMonth, normalizeHistoryQuery, recordsForRange, type HistoryStrategy } from '../domain/history'

interface Props { index?: ScreeningHistoryIndex | null }
const labels: Record<HistoryStrategy, string> = { all: '全部', trust: '投信新進榜', growth: '成長股', lowPosition: '低位觀察' }

function queryUrl(query: ReturnType<typeof normalizeHistoryQuery>): string {
  const params = new URLSearchParams()
  params.set('view', 'history')
  if (query.strategy !== 'all') params.set('strategy', query.strategy)
  if (query.from) params.set('from', query.from)
  if (query.to) params.set('to', query.to)
  if (query.code) params.set('code', query.code)
  return `${window.location.pathname}?${params}`
}

export function HistoryPanel({ index: suppliedIndex }: Props) {
  const [index, setIndex] = useState<ScreeningHistoryIndex | null>(suppliedIndex ?? null)
  const [error, setError] = useState(false)
  const [loadingIndex, setLoadingIndex] = useState(suppliedIndex === undefined)
  const [loadingRecords, setLoadingRecords] = useState(false)
  const [retryCount, setRetryCount] = useState(0)
  const [query, setQuery] = useState(() => normalizeHistoryQuery(new URLSearchParams(window.location.search), suppliedIndex ?? { earliestMarketDate: '', latestMarketDate: '' }))
  const [records, setRecords] = useState<ScreeningHistoryRecord[]>([])
  const [methodOpen, setMethodOpen] = useState(false)
  const canonicalized = useRef(false)

  useEffect(() => {
    if (suppliedIndex !== undefined) return
    let cancelled = false
    setLoadingIndex(true)
    setError(false)
    loadHistoryIndex().then((next) => {
      if (!cancelled) setIndex(next)
    }).catch(() => {
      if (!cancelled) setError(true)
    }).finally(() => {
      if (!cancelled) setLoadingIndex(false)
    })
    return () => { cancelled = true }
  }, [suppliedIndex, retryCount])

  useEffect(() => {
    if (!index) return
    const next = normalizeHistoryQuery(new URLSearchParams(window.location.search), index)
    setQuery(next)
    if (!canonicalized.current) {
      canonicalized.current = true
      window.history.replaceState(window.history.state, '', queryUrl(next))
    }
    if (next.invalidRange) {
      setRecords([])
      setLoadingRecords(false)
      return
    }

    let cancelled = false
    setRecords([])
    setLoadingRecords(true)
    setError(false)
    const entries = index.months.filter((month) => month.month >= next.from.slice(0, 7) && month.month <= next.to.slice(0, 7))
    Promise.all(entries.map(loadHistoryMonth)).then((months) => {
      if (!cancelled) setRecords(recordsForRange(months, next.from, next.to))
    }).catch(() => {
      if (!cancelled) setError(true)
    }).finally(() => {
      if (!cancelled) setLoadingRecords(false)
    })
    return () => { cancelled = true }
  }, [index, query.from, query.to, retryCount])

  const update = (patch: Partial<typeof query>) => {
    const next = { ...query, ...patch }
    setQuery(next)
    window.history.replaceState(window.history.state, '', queryUrl(next))
  }

  useEffect(() => {
    const onPop = () => setQuery(normalizeHistoryQuery(new URLSearchParams(window.location.search), index ?? { earliestMarketDate: '', latestMarketDate: '' }))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [index])

  const rows = useMemo(() => records.flatMap((record) => Object.entries(record.strategies).flatMap(([strategy, values]) => query.strategy !== 'all' && strategy !== query.strategy ? [] : filterHistoryRows(values, query.code).map((row) => ({ ...row, strategy, record })))), [records, query])
  const pending = loadingIndex || loadingRecords || (!index && !error)

  return <section className="history-panel" aria-labelledby="history-heading">
    <div className="history-heading"><div><p className="site-kicker">ARCHIVE / HISTORY</p><h2 id="history-heading">歷史篩選</h2></div><button className="method-button" aria-expanded={methodOpen} aria-controls="history-method" onClick={() => setMethodOpen((value) => !value)}>ⓘ 方法說明</button></div>
    {methodOpen && <p id="history-method" className="history-method">本站依公開方法與現有研究文件整理實作；數值是研究參考，不是目標價、買賣建議或即時報價。成長估值：總報酬本益比（本站整理）、總報酬估值參考價（本站整理）、低估門檻參考價。</p>}
    <div className="history-filters"><label>策略<select value={query.strategy} onChange={(event) => update({ strategy: event.target.value as HistoryStrategy })}>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>股票代號／名稱<input value={query.code} onChange={(event) => update({ code: event.target.value })} /></label><label>起始日<input type="date" aria-label="選擇歷史起始交易日" aria-invalid={query.invalidRange} aria-describedby="history-date-error" value={query.from} onChange={(event) => update({ from: event.target.value })} /></label><label>結束日<input type="date" aria-label="選擇歷史結束交易日" aria-invalid={query.invalidRange} aria-describedby="history-date-error" value={query.to} onChange={(event) => update({ to: event.target.value })} /></label></div>
    {query.invalidRange && <p id="history-date-error" className="history-error" role="alert">起始日不可晚於結束日，未載入資料。</p>}
    {query.clamped && <p className="history-notice">已限制在可查詢期間</p>}
    {pending && <p className="history-empty" role="status" aria-live="polite">正在載入歷史資料…</p>}
    {error && <div className="history-error history-retry" role="alert"><span>歷史資料暫不可用，請稍後重試。</span><button type="button" onClick={() => setRetryCount((count) => count + 1)}>重試</button></div>}
    {!pending && !error && index && !query.invalidRange && !records.length && <p className="history-empty">休市／沒有發布</p>}
    <div className="history-results">{rows.map(({ record, strategy, ...row }) => <article className="history-card" key={`${record.marketDate}-${strategy}-${row.code}`}><header><strong>{record.marketDate}</strong><span>{labels[strategy as HistoryStrategy]}</span></header><div className="history-row"><b>{row.code} {row.name}</b><span>{row.entryStatus === 'new' ? '新進榜' : row.entryStatus === 'retained' ? '續留' : '資料未知'}</span><span>{row.reason}</span></div><small>runId {record.runId} · ranking {record.formulaVersions.ranking}</small></article>)}</div>
  </section>
}
