import type { HistoryRankingRow, ScreeningHistoryIndex, ScreeningHistoryMonth, ScreeningHistoryRecord } from './types'

export type HistoryStrategy = 'all' | 'trust' | 'growth' | 'lowPosition'
export interface HistoryQuery { strategy: HistoryStrategy; from: string; to: string; code: string; clamped: boolean; invalidRange: boolean }
const DATE = /^\d{4}-\d{2}-\d{2}$/
const STRATEGIES = new Set<HistoryStrategy>(['all', 'trust', 'growth', 'lowPosition'])

export function normalizeDigits(value: string): string { return value.replace(/[０-９]/g, (c) => String(c.charCodeAt(0) - 0xff10)) }
export function defaultHistoryRange(availableDates: string[]): { from: string; to: string } {
  const sorted = [...availableDates].sort()
  return { from: sorted[Math.max(0, sorted.length - 30)] ?? '', to: sorted.at(-1) ?? '' }
}
export function normalizeHistoryQuery(params: URLSearchParams, bounds: Pick<ScreeningHistoryIndex, 'earliestMarketDate' | 'latestMarketDate' | 'months'> | { earliestMarketDate: string; latestMarketDate: string; months?: Array<{ marketDates?: string[] }> }): HistoryQuery {
  const availableDates = bounds.months?.flatMap((month) => month.marketDates ?? []).filter((value) => DATE.test(value)).sort() ?? []
  const defaults = availableDates.length
    ? defaultHistoryRange(availableDates)
    : bounds.earliestMarketDate && bounds.latestMarketDate
      ? { from: bounds.earliestMarketDate, to: bounds.latestMarketDate }
      : { from: '', to: '' }
  let from = normalizeDigits(params.get('from')?.trim() ?? '')
  let to = normalizeDigits(params.get('to')?.trim() ?? '')
  let clamped = false
  if (!DATE.test(from)) from = defaults.from
  if (!DATE.test(to)) to = defaults.to
  const available = bounds.earliestMarketDate && bounds.latestMarketDate
    ? { from: bounds.earliestMarketDate, to: bounds.latestMarketDate }
    : { from: '', to: '' }
  if (available.from && from < available.from) { from = available.from; clamped = true }
  if (available.to && to > available.to) { to = available.to; clamped = true }
  const code = normalizeDigits(params.get('code')?.trim() ?? '')
  const strategy = STRATEGIES.has(params.get('strategy') as HistoryStrategy) ? params.get('strategy') as HistoryStrategy : 'all'
  return { strategy, from, to, code, clamped, invalidRange: Boolean(from && to && from > to) }
}
export function filterHistoryRows(rows: HistoryRankingRow[], query: string): HistoryRankingRow[] {
  const needle = normalizeDigits(query.trim()).toLocaleLowerCase()
  if (!needle) return rows
  return rows.filter((row) => row.code.startsWith(needle) || row.name.toLocaleLowerCase().includes(needle))
}
function record(value: unknown): ScreeningHistoryRecord {
  if (!value || typeof value !== 'object') throw new Error('歷史資料格式錯誤')
  const r = value as Record<string, unknown>
  if (typeof r.marketDate !== 'string' || !DATE.test(r.marketDate) || typeof r.runId !== 'string' || typeof r.revision !== 'string') throw new Error('歷史資料格式錯誤')
  if (!r.strategies || typeof r.strategies !== 'object') throw new Error('歷史資料格式錯誤')
  return value as ScreeningHistoryRecord
}
export function validateHistoryIndex(value: unknown): ScreeningHistoryIndex {
  if (!value || typeof value !== 'object') throw new Error('歷史索引格式錯誤')
  const v = value as Record<string, unknown>
  if (v.schemaVersion !== 'screening-history-index-v1' || !Array.isArray(v.months) || typeof v.generatedAt !== 'string' || typeof v.retentionDays !== 'number') throw new Error('歷史索引格式錯誤')
  for (const m of v.months) {
    if (!m || typeof m !== 'object' || !/^\d{4}-\d{2}$/.test((m as Record<string, unknown>).month as string)) throw new Error('歷史索引格式錯誤')
    const entry = m as Record<string, unknown>
    if (typeof entry.path !== 'string' || typeof entry.sha256 !== 'string' || !Array.isArray(entry.marketDates)) throw new Error('歷史索引格式錯誤')
  }
  return value as ScreeningHistoryIndex
}
export function validateHistoryMonth(value: unknown): ScreeningHistoryMonth {
  if (!value || typeof value !== 'object') throw new Error('歷史月份格式錯誤')
  const v = value as Record<string, unknown>
  if (v.schemaVersion !== 'screening-history-month-v1' || typeof v.month !== 'string' || !Array.isArray(v.records)) throw new Error('歷史月份格式錯誤')
  v.records.forEach(record)
  return value as ScreeningHistoryMonth
}
const INDEX_CACHE = 'taiwan-stock-research:history-index:v1'
const monthRequests = new Map<string, Promise<ScreeningHistoryMonth>>()
async function fetchJson(url: string): Promise<unknown> { const response = await fetch(url, { headers: { Accept: 'application/json' } }); if (!response.ok) throw new Error(`歷史資料讀取失敗（${response.status}）`); return response.json() }
export async function loadHistoryIndex(): Promise<ScreeningHistoryIndex> {
  try { const index = validateHistoryIndex(await fetchJson('/data/archive/v1/index.json')); try { sessionStorage.setItem(INDEX_CACHE, JSON.stringify(index)) } catch {} return index }
  catch (error) { try { const cached = sessionStorage.getItem(INDEX_CACHE); if (cached) return validateHistoryIndex(JSON.parse(cached)) } catch {} throw error }
}
export function loadHistoryMonth(entry: { month: string; path: string; sha256?: string }): Promise<ScreeningHistoryMonth> {
  const cacheKey = `${entry.path}|${entry.sha256 ?? ''}`
  const existing = monthRequests.get(cacheKey); if (existing) return existing
  const request = fetchJson(entry.path).then(validateHistoryMonth).catch((error: unknown) => {
    monthRequests.delete(cacheKey)
    throw error
  })
  monthRequests.set(cacheKey, request)
  return request
}
export function recordsForRange(months: ScreeningHistoryMonth[], from: string, to: string): ScreeningHistoryRecord[] { return months.flatMap((m) => m.records).filter((r) => r.marketDate >= from && r.marketDate <= to).sort((a, b) => a.marketDate.localeCompare(b.marketDate)) }
