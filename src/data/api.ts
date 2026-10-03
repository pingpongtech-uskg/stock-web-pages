import type { RankingRow, Release, StockSummary } from '../domain/types'
export { loadHistoryIndex, loadHistoryMonth, validateHistoryIndex, validateHistoryMonth } from '../domain/history'

const DATA_ROOT = '/data'
const FRESHNESS_VALUES = new Set(['current', 'stale', 'degraded', 'unavailable'])
const STATUS_VALUES = new Set(['pass', 'fail', 'unknown', 'not_applicable'])
const RANKING_KEYS = ['trust', 'growth', 'lowPosition', 'lowBase', 'lowBaseGrowth', 'lowBaseQuality'] as const
const FUNNEL_STRATEGY_KEYS = ['trust', 'growth', 'lowPosition'] as const
const ROW_NULLABLE_NUMBERS = [
  'currentPrice', 'fairPrice', 'valuePrice075', 'valuePrice066', 'currentPeg',
  'currentPe', 'currentEps', 'valuationGrowthInput', 'zScore', 'slope',
  'regressionObservations', 'regressionExpectedObservations',
  'growthTotalReturnPe', 'growthConservativeGrowth', 'growthDividendYield',
  'growthForwardEps', 'growthFairPrice', 'growthBuyZonePrice',
] as const

type UnknownRecord = Record<string, unknown>
const RELEASE_CACHE_KEY = 'taiwan-stock-research:last-valid-release:v1'

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function invalidRelease(): never {
  throw new Error('發布快照格式錯誤，拒絕顯示不完整資料')
}

function expect(condition: boolean): void {
  if (!condition) invalidRelease()
}

function requireRecord(value: unknown): UnknownRecord {
  if (!isRecord(value)) invalidRelease()
  return value
}

function requireArray(value: unknown): unknown[] {
  if (!Array.isArray(value)) invalidRelease()
  return value
}

function requireString(value: unknown): string {
  if (typeof value !== 'string') invalidRelease()
  return value
}

function requireFiniteNumber(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) invalidRelease()
  return value
}

function requireCount(value: unknown): number {
  const count = requireFiniteNumber(value)
  expect(Number.isInteger(count) && count >= 0)
  return count
}

function requireNullableNumber(value: unknown): number | null {
  if (value === null) return null
  if (typeof value !== 'number' || !Number.isFinite(value)) invalidRelease()
  return value
}

function requireNullableString(value: unknown): string | null {
  if (value === null) return null
  if (typeof value !== 'string') invalidRelease()
  return value
}

function validateMarketIndicators(value: unknown): void {
  const indicators = requireRecord(value)
  if (indicators.volumeMultiple00631L === undefined) return
  const indicator = requireRecord(indicators.volumeMultiple00631L)
  expect(requireString(indicator.symbol) === '00631L')
  requireString(indicator.name)
  expect(requireString(indicator.market) === 'TWSE')
  requireNullableString(indicator.marketDate)
  requireNullableNumber(indicator.currentVolume)
  requireNullableNumber(indicator.previous5AverageVolume)
  requireNullableNumber(indicator.multiple)
  expect(indicator.threshold === 2)
  expect(indicator.displayOnly === true)
  expect(requireArray(indicator.priorFiveSessions).every((row) => {
    const item = requireRecord(row)
    requireString(item.date)
    requireFiniteNumber(item.volume)
    return true
  }))
  expect(['green', 'yellow', 'unknown'].includes(requireString(indicator.signal)))
  expect(['available', 'unavailable'].includes(requireString(indicator.status)))
  expect(requireString(indicator.formulaVersion) === 'twse-volume-multiple-v1')
  expect(requireArray(indicator.sourceRefs).every((ref) => typeof ref === 'string'))
  requireString(indicator.reason)
}

function validateChipReference(value: unknown): void {
  const chip = requireRecord(value)
  expect(requireString(chip.schemaVersion) === 'chip-reference-v1')
  expect(chip.displayOnly === true)
  expect(requireString(chip.formulaVersion) === 'chip-reference-v1')
  expect(['pass', 'fail', 'unknown'].includes(requireString(chip.status)))
  expect(['current', 'stale', 'unavailable'].includes(requireString(chip.dataFreshness)))
  expect(requireArray(chip.sourceRefs).every((ref) => typeof ref === 'string'))
  requireNullableString(chip.availableAt)
  for (const key of ['largeHolderTrend', 'directorSupervisor12m', 'shareholderCountTrend']) {
    const indicator = requireRecord(chip[key])
    expect(['pass', 'fail', 'unknown'].includes(requireString(indicator.status)))
    requireString(indicator.value)
    requireString(indicator.period)
    expect(requireArray(indicator.sourceRefs).every((ref) => typeof ref === 'string'))
    if (indicator.rawValues !== undefined && indicator.rawValues !== null) {
      if (key === 'directorSupervisor12m') {
        const raw = requireRecord(indicator.rawValues)
        requireFiniteNumber(raw.latest)
        requireFiniteNumber(raw.prior12m)
      } else {
        expect(requireArray(indicator.rawValues).every((raw) => typeof raw === 'number' && Number.isFinite(raw)))
      }
    }
  }
}

function validateRankingRow(value: unknown): void {
  const row = requireRecord(value)
  requireFiniteNumber(row.rank)
  expect(requireString(row.code).length > 0)
  requireString(row.name)
  requireString(row.sector)
  expect(STATUS_VALUES.has(requireString(row.status)))
  requireString(row.reason)
  requireNullableNumber(row.value)
  requireString(row.valueLabel)
  for (const key of ROW_NULLABLE_NUMBERS) {
    if (row[key] !== undefined) requireNullableNumber(row[key])
  }
  if (row.pegBand !== undefined) expect(row.pegBand === 'strict' || row.pegBand === 'acceptable')
  if (row.valuationEvidenceLevel !== undefined) expect(row.valuationEvidenceLevel === 'formal' || row.valuationEvidenceLevel === 'proxy' || row.valuationEvidenceLevel === 'unavailable')
  if (row.extremeExtrapolation !== undefined) expect(typeof row.extremeExtrapolation === 'boolean')
  if (row.valuationGrowthMethod !== undefined) requireString(row.valuationGrowthMethod)
  if (row.valuationGrowthMethodLabel !== undefined) requireString(row.valuationGrowthMethodLabel)
  if (row.valuationFormulaVersion !== undefined) requireString(row.valuationFormulaVersion)
  if (row.growthValuationStatus !== undefined) expect(['available', 'unavailable', 'extreme'].includes(requireString(row.growthValuationStatus)))
  if (row.growthValuationReason !== undefined) requireString(row.growthValuationReason)
  if (row.priceBasis !== undefined) expect(row.priceBasis === 'adjusted' || row.priceBasis === 'raw_proxy' || row.priceBasis === 'unknown')
  if (row.regressionStart !== undefined) requireNullableString(row.regressionStart)
  if (row.regressionEnd !== undefined) requireNullableString(row.regressionEnd)
  if (row.chipReference !== undefined) validateChipReference(row.chipReference)
}

function validateStockSummary(value: unknown): void {
  const stock = requireRecord(value)
  expect(requireString(stock.code).length > 0)
  requireString(stock.name)
  if (stock.slope !== undefined) requireNullableNumber(stock.slope)
  if (stock.zScore !== undefined) requireNullableNumber(stock.zScore)
  if (stock.lastPrice !== undefined) requireNullableNumber(stock.lastPrice)
  if (stock.sourceRefs !== undefined) expect(requireArray(stock.sourceRefs).every((ref) => typeof ref === 'string'))
  if (stock.chipReference !== undefined) validateChipReference(stock.chipReference)
}

function validateGrowthInputAudit(value: unknown): void {
  const audit = requireRecord(value)
  for (const key of ['price', 'pe', 'ttmEps', 'earningsGrowth', 'dividendYield']) {
    const evidence = requireRecord(audit[key])
    expect(['reported', 'derived', 'proxy', 'unavailable'].includes(requireString(evidence.origin)))
    requireNullableString(evidence.sourcePeriod)
    requireNullableString(evidence.method)
    requireNullableString(evidence.source)
    if (evidence.reason !== undefined) requireNullableString(evidence.reason)
  }
}

function validateGrowthCheckValue(value: unknown): void {
  if (value === null || typeof value === 'string') return
  if (typeof value === 'number') {
    requireFiniteNumber(value)
    return
  }
  const months = requireArray(value)
  expect(months.length === 3)
  months.forEach(requireFiniteNumber)
}

function validateGrowthStockDiagnostics(value: unknown): void {
  const stock = requireRecord(value)
  const growth = requireRecord(stock.growthValuation)
  expect(['available', 'unavailable', 'extreme'].includes(requireString(growth.status)))
  requireString(growth.reason)
  expect(requireArray(growth.missingReasons).every((reason) => typeof reason === 'string'))
  expect(typeof growth.inputsComplete === 'boolean')
  validateGrowthInputAudit(growth.inputAudit)
  expect(typeof stock.growthHealthEligible === 'boolean')
  const categories = requireArray(stock.healthCategories).map(requireRecord)
  const growthHealth = categories.find((category) => category.key === 'growth')
  expect(Boolean(growthHealth))
  requireString(growthHealth?.label)
  requireCount(growthHealth?.passCount)
  expect(requireCount(growthHealth?.total) === 5)
  expect(['pass', 'fail', 'unknown', 'not_applicable'].includes(requireString(growthHealth?.status)))
  const checks = requireArray(growthHealth?.checks)
  expect(checks.length === 5 && checks.every((value) => {
    const check = requireRecord(value)
    requireString(check.label)
    expect(['pass', 'fail', 'unknown', 'not_applicable'].includes(requireString(check.status)))
    validateGrowthCheckValue(check.value)
    requireString(check.period)
    requireString(check.explanation)
    expect(requireArray(check.sourceRefs).every((source) => typeof source === 'string'))
    return true
  }))
}

function validateGrowthCoverage(funnel: UnknownRecord, stocks: unknown[]): void {
  const version = funnel.growthCoverageVersion
  if (version === undefined) {
    const v1Fields = ['growthEvaluationState', 'growthInputComplete', 'growthThresholdCandidates', 'growthHealthCandidates', 'growthMissingReasons', 'growthTerminalOutcomes']
    expect(!v1Fields.some((key) => key in funnel))
    return
  }
  expect(version === 'growth-coverage-v1')
  expect(['not_evaluable', 'partial', 'evaluated'].includes(requireString(funnel.growthEvaluationState)))
  const inputComplete = requireCount(funnel.growthInputComplete)
  const valuationComplete = requireCount(funnel.growthValuationComplete)
  const thresholdCandidates = requireCount(funnel.growthThresholdCandidates)
  const healthCandidates = requireCount(funnel.growthHealthCandidates)
  const growthCandidates = requireCount(funnel.growthCandidates)
  expect(requireArray(funnel.growthMissingReasons).every((value) => {
    const item = requireRecord(value)
    requireString(item.reason)
    requireCount(item.count)
    return true
  }))
  const terminal = requireRecord(funnel.growthTerminalOutcomes)
  const terminalKeys = ['universe', 'missing', 'knownInvalid', 'extreme', 'belowThreshold', 'healthBlocked', 'selected']
  expect(Object.keys(terminal).sort().join('|') === [...terminalKeys].sort().join('|'))
  const terminalCounts = terminalKeys
    .map((key) => requireCount(terminal[key]))
  const [universe, missing, knownInvalid, extreme, belowThreshold, healthBlocked, selected] = terminalCounts
  expect(missing + knownInvalid + extreme + belowThreshold + healthBlocked + selected === universe)
  const motherUniverse = requireCount(funnel.universe)
  const instrumentExcluded = requireCount(funnel.instrumentExcluded)
  expect(instrumentExcluded <= motherUniverse && universe === motherUniverse - instrumentExcluded)
  expect(valuationComplete <= inputComplete && inputComplete <= universe)
  expect(belowThreshold + thresholdCandidates === valuationComplete)
  expect(healthBlocked + selected === thresholdCandidates)
  expect(selected === healthCandidates && growthCandidates === selected)
  const expectedState = universe === 0 || missing === universe ? 'not_evaluable' : missing > 0 ? 'partial' : 'evaluated'
  expect(funnel.growthEvaluationState === expectedState)
  const strategyCounts = requireRecord(funnel.strategyCandidates)
  expect(requireCount(strategyCounts.growth) === growthCandidates)
  const reasons = requireArray(funnel.growthMissingReasons)
  const reasonKeys = new Set<string>()
  reasons.forEach((value) => {
    const item = requireRecord(value)
    const reason = requireString(item.reason)
    const count = requireCount(item.count)
    expect(count > 0 && count <= universe && !reasonKeys.has(reason))
    reasonKeys.add(reason)
  })
  stocks.forEach(validateGrowthStockDiagnostics)
}

export function validateRelease(payload: unknown): Release {
  const p = requireRecord(payload)
  expect(requireString(p.runId).length > 0)
  requireString(p.schemaVersion)
  requireString(p.strategyVersion)
  requireString(p.formulaVersion)
  requireString(p.generatedAt)
  requireNullableString(p.marketDate)
  if (p.nextExpectedUpdateAt !== undefined) requireNullableString(p.nextExpectedUpdateAt)
  if (p.marketIndicators !== undefined) validateMarketIndicators(p.marketIndicators)
  expect(FRESHNESS_VALUES.has(requireString(p.freshness)))
  requireString(p.statusMessage)
  expect(requireArray(p.sourceRefs).every((ref) => typeof ref === 'string'))

  // coverage: every field the UI reads is fail-closed validated.  A stringy
  // completenessPct must reach the ErrorScreen, never crash inside .toFixed.
  const coverage = requireRecord(p.coverage)
  for (const key of ['universeCount', 'databaseCount', 'candidateCount', 'pendingCount', 'financialCompleteCount', 'priceCompleteCount']) {
    requireFiniteNumber(coverage[key])
  }
  if (coverage.completenessPct !== undefined) requireNullableNumber(coverage.completenessPct)
  if (coverage.scopeLabel !== undefined) requireString(coverage.scopeLabel)
  requireString(coverage.queueStatus)
  if (coverage.trackedCount !== undefined) requireFiniteNumber(coverage.trackedCount)
  if (coverage.trackedCompleteCount !== undefined) requireFiniteNumber(coverage.trackedCompleteCount)

  // funnel: producer-published stage counts that must conserve.
  const funnel = requireRecord(p.funnel)
  expect(requireString(funnel.version).length > 0)
  const funnelUniverse = requireFiniteNumber(funnel.universe)
  const funnelPrice = requireFiniteNumber(funnel.priceComplete)
  const funnelValuation = requireFiniteNumber(funnel.valuationComplete)
  if (funnel.growthValuationComplete !== undefined) requireFiniteNumber(funnel.growthValuationComplete)
  for (const key of ['growthInputComplete', 'growthThresholdCandidates', 'growthHealthCandidates']) {
    if (funnel[key] !== undefined) requireFiniteNumber(funnel[key])
  }
  if (funnel.growthMissingReasons !== undefined) {
    expect(requireArray(funnel.growthMissingReasons).every((value) => {
      const item = requireRecord(value)
      requireString(item.reason)
      requireFiniteNumber(item.count)
      return true
    }))
  }
  const funnelPeg = requireFiniteNumber(funnel.pegCandidates)
  const funnelFormal = requireFiniteNumber(funnel.formalValuations)
  const funnelProxy = requireFiniteNumber(funnel.proxyValuations)
  requireFiniteNumber(funnel.instrumentExcluded)
  requireString(funnel.instrumentPolicy)
  const strategyCounts = requireRecord(funnel.strategyCandidates)
  const funnelGrowth = funnel.growthCandidates === undefined
    ? requireFiniteNumber(strategyCounts.growth)
    : requireFiniteNumber(funnel.growthCandidates)
  const counts = FUNNEL_STRATEGY_KEYS.map((key) => requireFiniteNumber(strategyCounts[key]))
  expect(funnelPeg <= funnelValuation)
  expect(funnelFormal + funnelProxy === funnelValuation)
  expect(funnelUniverse >= 0 && funnelPrice >= 0)
  // Official trust flow and low-position price observations do not require
  // a PEG value. Only the growth route is bounded by the PEG pool.
  expect(counts[1] <= funnelGrowth)

  const rankings = requireRecord(p.rankings)
  for (const key of RANKING_KEYS) {
    for (const row of requireArray(rankings[key])) validateRankingRow(row)
  }
  const stocks = requireArray(p.stocks)
  for (const stock of stocks) validateStockSummary(stock)
  validateGrowthCoverage(funnel, stocks)
  requireRecord(p.summary)
  requireRecord(p.research)
  return payload as unknown as Release
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new Error(`資料讀取失敗（${response.status}）`)
  }
  return response.json() as Promise<T>
}

function cacheRelease(release: Release): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(RELEASE_CACHE_KEY, JSON.stringify(release))
  } catch {
    // Storage can be disabled or full. The network release remains primary.
  }
}

function loadCachedRelease(): Release | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(RELEASE_CACHE_KEY)
    return raw ? validateRelease(JSON.parse(raw) as unknown) : null
  } catch {
    return null
  }
}

export interface LoadedRelease {
  release: Release
  source: 'network' | 'cache'
  contentHash: string | null
}

async function sha256Text(value: string): Promise<string | null> {
  try {
    if (!globalThis.crypto?.subtle) return null
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
  } catch {
    return null
  }
}

export async function loadLatestRelease(): Promise<LoadedRelease> {
  try {
    const response = await fetch(`${DATA_ROOT}/latest.json`, { headers: { Accept: 'application/json' }, cache: 'no-store' })
    if (!response.ok) throw new Error(`資料讀取失敗（${response.status}）`)
    const body = await response.text()
    const release = validateRelease(JSON.parse(body) as unknown)
    cacheRelease(release)
    return { release, source: 'network', contentHash: await sha256Text(body) }
  } catch (error) {
    const cached = loadCachedRelease()
    if (cached) return { release: cached, source: 'cache', contentHash: null }
    throw error
  }
}

export async function loadStockDetail(runId: string, code: string): Promise<StockSummary> {
  const safeCode = encodeURIComponent(code)
  try {
    const detail = await getJson<StockSummary>(`${DATA_ROOT}/releases/${encodeURIComponent(runId)}/stocks/${safeCode}.json`)
    if (detail.code !== code) {
      throw new Error('個股資料代碼與請求不一致')
    }
    return detail
  } catch (error) {
    // Rankings are still useful while a large per-stock evidence file is
    // propagating through Pages.  Render the same release summary instead of
    // turning the whole stock page into a 404; the page clearly shows that
    // its detailed chart/evidence is waiting for the next data sync.
    const loaded = await loadLatestRelease()
    const summary = loaded.release.stocks.find((stock) => stock.code === code)
    if (!summary) throw error
    return summary
  }
}
