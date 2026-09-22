import { useEffect, useMemo, useRef, useState } from 'react'
import type { ScreeningHistoryIndex, ScreeningHistoryMonth, ScreeningHistoryRecord } from '../domain/types'
import { filterHistoryRows, loadHistoryIndex, loadHistoryMonth, normalizeHistoryQuery, recordsForRange, type HistoryStrategy } from '../domain/history'

interface Props { index?: ScreeningHistoryIndex | null }
const labels: Record<HistoryStrategy, string> = { all: '全部', trust: '投信新進榜', growth: '成長股', lowPosition: '低位觀察' }

export function HistoryPanel({ index: suppliedIndex }: Props) {
  const [index, setIndex] = useState<ScreeningHistoryIndex | null>(suppliedIndex ?? null)
  const [error, setError] = useState(false)
  const [query, setQuery] = useState(() => normalizeHistoryQuery(new URLSearchParams(window.location.search), suppliedIndex ?? { earliestMarketDate: '', latestMarketDate: '' }))
  const [records, setRecords] = useState<ScreeningHistoryRecord[]>([])
  const [methodOpen, setMethodOpen] = useState(false)
  const canonicalized = useRef(false)
  useEffect(() => { if (suppliedIndex !== undefined) return; loadHistoryIndex().then(setIndex).catch(() => setError(true)) }, [suppliedIndex])
  useEffect(() => { if (!index) return; const next = normalizeHistoryQuery(new URLSearchParams(window.location.search), index); setQuery(next); if (!canonicalized.current) { canonicalized.current = true; const params = new URLSearchParams(); params.set('view', 'history'); if (next.strategy !== 'all') params.set('strategy', next.strategy); if (next.from) params.set('from', next.from); if (next.to) params.set('to', next.to); if (next.code) params.set('code', next.code); window.history.replaceState(null, '', `${window.location.pathname}?${params}`) } if (next.invalidRange) return; const entries = index.months.filter((m) => m.month >= next.from.slice(0, 7) && m.month <= next.to.slice(0, 7)); Promise.all(entries.map(loadHistoryMonth)).then((months) => setRecords(recordsForRange(months, next.from, next.to))).catch(() => setError(true)) }, [index, query.from, query.to])
  const update = (patch: Partial<typeof query>) => { const next = { ...query, ...patch }; setQuery(next); const params = new URLSearchParams(); params.set('view', 'history'); if (next.strategy !== 'all') params.set('strategy', next.strategy); if (next.from) params.set('from', next.from); if (next.to) params.set('to', next.to); if (next.code) params.set('code', next.code); window.history.replaceState(null, '', `${window.location.pathname}?${params}`) }
  useEffect(() => { const onPop = () => setQuery(normalizeHistoryQuery(new URLSearchParams(window.location.search), index ?? { earliestMarketDate: '', latestMarketDate: '' })); window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop) }, [index])
  const rows = useMemo(() => records.flatMap((record) => Object.entries(record.strategies).flatMap(([strategy, values]) => query.strategy !== 'all' && strategy !== query.strategy ? [] : filterHistoryRows(values, query.code).map((row) => ({ ...row, strategy, record })))), [records, query])
  return <section className="history-panel" aria-labelledby="history-heading">
    <div className="history-heading"><div><p className="site-kicker">ARCHIVE / HISTORY</p><h2 id="history-heading">歷史篩選</h2></div><button className="method-button" aria-expanded={methodOpen} aria-controls="history-method" onClick={() => setMethodOpen((v) => !v)}>ⓘ 方法說明</button></div>
    {methodOpen && <p id="history-method" className="history-method">本站依公開方法與現有研究文件整理實作；數值是研究參考，不是目標價、買賣建議或即時報價。成長估值：總報酬本益比（本站整理）、總報酬估值參考價（本站整理）、低估門檻參考價。</p>}
    <div className="history-filters"><label>策略<select value={query.strategy} onChange={(e) => update({ strategy: e.target.value as HistoryStrategy })}>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>股票代號／名稱<input value={query.code} onChange={(e) => update({ code: e.target.value })} /></label><label>起始日<input type="date" aria-label="選擇歷史起始交易日" aria-invalid={query.invalidRange} aria-describedby="history-date-error" value={query.from} onChange={(e) => update({ from: e.target.value })} /></label><label>結束日<input type="date" aria-label="選擇歷史結束交易日" aria-invalid={query.invalidRange} aria-describedby="history-date-error" value={query.to} onChange={(e) => update({ to: e.target.value })} /></label></div>
    {query.invalidRange && <p id="history-date-error" className="history-error" role="alert">起始日不可晚於結束日，未載入資料。</p>}
    {query.clamped && <p className="history-notice">已限制在可查詢期間</p>}
    {error && <p className="history-empty">歷史資料同步中／暫不可用</p>}
    {!error && !index && <p className="history-empty">歷史資料同步中／暫不可用</p>}
    {!error && index && !query.invalidRange && !records.length && <p className="history-empty">休市／沒有發布</p>}
    <div className="history-results">{rows.map(({ record, strategy, ...row }) => <article className="history-card" key={`${record.marketDate}-${strategy}-${row.code}`}><header><strong>{record.marketDate}</strong><span>{labels[strategy as HistoryStrategy]}</span></header><div className="history-row"><b>{row.code} {row.name}</b><span>{row.entryStatus === 'new' ? '新進榜' : row.entryStatus === 'retained' ? '續留' : '資料未知'}</span><span>{row.reason}</span></div><small>runId {record.runId} · ranking {record.formulaVersions.ranking}</small></article>)}</div>
  </section>
}
