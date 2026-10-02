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
export function historyGrowthCoverageSummary(record: Pick<ScreeningHistoryRecord, 'legacy' | 'growthCoverage'>): string {
  const coverage = record.growthCoverage
  if (!coverage) return '舊版歷史發布未提供成長覆蓋診斷；不依新規則回推。'
  const terminal = coverage.terminalOutcomes
  const state = coverage.evaluationState === 'not_evaluable' ? '尚不可評估' : coverage.evaluationState === 'partial' ? '部分評估' : '已完整評估'
  const labels: Record<string, string> = { price: '價格', pe: 'PE', ttmEps: 'TTM EPS', earningsGrowth: 'EPS 成長', dividendYield: '股利殖利率' }
  const reasons = coverage.missingReasons.map((item) => `${labels[item.reason] ?? item.reason} ${item.count}`).join('、')
  return `成長覆蓋 ${state}：輸入完整 ${coverage.inputComplete}/${terminal.universe} 檔、可計算 ${coverage.valuationComplete} 檔、總報酬本益比 ≥ 1.20 為 ${coverage.thresholdCandidates} 檔、健康 ≥ 4/5 為 ${coverage.healthCandidates} 檔、最終 ${coverage.candidates} 檔；互斥缺少輸入 ${terminal.missing} 檔、已知不合格 ${terminal.knownInvalid} 檔、極端外推 ${terminal.extreme} 檔、低於門檻 ${terminal.belowThreshold} 檔、健康未達 ${terminal.healthBlocked} 檔、入選 ${terminal.selected} 檔。${reasons ? `重疊原因：${reasons}。` : ''}`
}
function record(value: unknown): ScreeningHistoryRecord {
  if (!value || typeof value !== 'object') throw new Error('歷史資料格式錯誤')
  const r = value as Record<string, unknown>
  if (typeof r.marketDate !== 'string' || !DATE.test(r.marketDate) || typeof r.runId !== 'string' || typeof r.revision !== 'string') throw new Error('歷史資料格式錯誤')
  if (!r.strategies || typeof r.strategies !== 'object') throw new Error('歷史資料格式錯誤')
  if (r.legacy !== undefined && typeof r.legacy !== 'boolean') throw new Error('歷史資料格式錯誤')
  if (r.growthCoverage !== undefined) {
    if (r.legacy === true) throw new Error('歷史資料格式錯誤')
    validateHistoryGrowthCoverage(r.growthCoverage)
  }
  else if (r.legacy === false) throw new Error('歷史資料格式錯誤')
  return value as ScreeningHistoryRecord
}

function validateHistoryGrowthCoverage(value: unknown): void {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('歷史成長覆蓋格式錯誤')
  const coverage = value as Record<string, unknown>
  const fields = ['version', 'evaluationState', 'inputComplete', 'valuationComplete', 'thresholdCandidates', 'healthCandidates', 'candidates', 'missingReasons', 'terminalOutcomes']
  if (Object.keys(coverage).sort().join('|') !== [...fields].sort().join('|')
    || coverage.version !== 'growth-coverage-v1'
    || !['not_evaluable', 'partial', 'evaluated'].includes(String(coverage.evaluationState))) throw new Error('歷史成長覆蓋格式錯誤')
  const count = (candidate: unknown): number => {
    if (typeof candidate !== 'number' || !Number.isInteger(candidate) || candidate < 0) throw new Error('歷史成長覆蓋格式錯誤')
    return candidate
  }
  const inputComplete = count(coverage.inputComplete)
  const valuationComplete = count(coverage.valuationComplete)
  const thresholdCandidates = count(coverage.thresholdCandidates)
  const healthCandidates = count(coverage.healthCandidates)
  const candidates = count(coverage.candidates)
  if (!Array.isArray(coverage.missingReasons)) throw new Error('歷史成長覆蓋格式錯誤')
  const reasons = new Set<string>()
  for (const value of coverage.missingReasons) {
    if (!value || typeof value !== 'object') throw new Error('歷史成長覆蓋格式錯誤')
    const reason = (value as Record<string, unknown>).reason
    const amount = count((value as Record<string, unknown>).count)
    if (typeof reason !== 'string' || !reason || reasons.has(reason)) throw new Error('歷史成長覆蓋格式錯誤')
    reasons.add(reason)
    if (amount < 1) throw new Error('歷史成長覆蓋格式錯誤')
  }
  if (!coverage.terminalOutcomes || typeof coverage.terminalOutcomes !== 'object' || Array.isArray(coverage.terminalOutcomes)) throw new Error('歷史成長覆蓋格式錯誤')
  const terminal = coverage.terminalOutcomes as Record<string, unknown>
  const keys = ['universe', 'missing', 'knownInvalid', 'extreme', 'belowThreshold', 'healthBlocked', 'selected']
  if (Object.keys(terminal).sort().join('|') !== [...keys].sort().join('|')) throw new Error('歷史成長覆蓋格式錯誤')
  const counts = Object.fromEntries(keys.map((key) => [key, count(terminal[key])])) as Record<typeof keys[number], number>
  if (Object.values(counts).slice(1).reduce((total, item) => total + item, 0) !== counts.universe
    || counts.selected !== candidates || counts.selected !== healthCandidates
    || counts.healthBlocked + counts.selected !== thresholdCandidates
    || counts.belowThreshold + thresholdCandidates !== valuationComplete
    || valuationComplete > inputComplete || inputComplete > counts.universe
    || coverage.missingReasons.some((item) => count((item as Record<string, unknown>).count) > counts.universe)) throw new Error('歷史成長覆蓋不守恆')
  const state = counts.universe === 0 || counts.missing === counts.universe
    ? 'not_evaluable'
    : counts.missing > 0 ? 'partial' : 'evaluated'
  if (coverage.evaluationState !== state) throw new Error('歷史成長覆蓋狀態不一致')
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
