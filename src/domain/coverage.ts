import type { GrowthTerminalOutcomes, HealthCategory, Release, StockSummary } from './types'
import type { StrategyKey } from './strategyPresentation'

export const GROWTH_HEALTH_CHECK_LABELS = [
  '月營收 YOY 連續三個月大於 0',
  '近一季毛利年增率大於 0',
  '近一季營業利益年增率大於 0',
  '近一季稅前淨利年增率大於 0',
  '近一季稅後淨利年增率大於 0',
] as const

export type GrowthHealthOutcome = 'qualified' | 'not_qualified' | 'unknown' | 'unreported'

export interface QualityStatusCounts {
  pass: number
  fail: number
  unknown: number
  notApplicable: number
  unreported: number
}

export function qualityStatusCounts(stocks: readonly { qualityStatus?: unknown }[]): QualityStatusCounts {
  return stocks.reduce<QualityStatusCounts>((counts, stock) => {
    if (stock.qualityStatus === 'pass') counts.pass += 1
    else if (stock.qualityStatus === 'fail') counts.fail += 1
    else if (stock.qualityStatus === 'unknown') counts.unknown += 1
    else if (stock.qualityStatus === 'not_applicable') counts.notApplicable += 1
    else counts.unreported += 1
    return counts
  }, { pass: 0, fail: 0, unknown: 0, notApplicable: 0, unreported: 0 })
}

export function growthHealthOutcome(category: Pick<HealthCategory, 'checks'> | undefined): GrowthHealthOutcome {
  if (!category) return 'unreported'
  const checks = category.checks
  if (!Array.isArray(checks) || checks.length !== GROWTH_HEALTH_CHECK_LABELS.length) return 'unknown'
  const byLabel = new Map(checks.map((check) => [check.label, check]))
  if (byLabel.size !== GROWTH_HEALTH_CHECK_LABELS.length
    || GROWTH_HEALTH_CHECK_LABELS.some((label) => !byLabel.has(label))) return 'unknown'
  const statuses = GROWTH_HEALTH_CHECK_LABELS.map((label) => byLabel.get(label)?.status)
  if (statuses.some((status) => !['pass', 'fail', 'unknown'].includes(String(status)))) return 'unknown'
  const passCount = statuses.filter((status) => status === 'pass').length
  if (passCount >= 4) return 'qualified'
  const knownFailures = statuses.filter((status) => status === 'fail').length
  return knownFailures >= 2 ? 'not_qualified' : 'unknown'
}

export function stockGrowthHealthOutcome(stock: Pick<StockSummary, 'healthCategories'>): GrowthHealthOutcome {
  const category = stock.healthCategories?.find((item) => item.key === 'growth')
  return growthHealthOutcome(category)
}

export interface CoverageFunnel {
  universe: number
  priceComplete: number
  valuationComplete: number
  growthInputComplete: number | null
  growthValuationComplete: number | null
  growthThresholdCandidates: number | null
  growthHealthCandidates: number | null
  growthMissingReasons: Array<{ reason: string; count: number }> | null
  growthEvaluationState: 'not_evaluable' | 'partial' | 'evaluated' | null
  growthTerminalOutcomes: GrowthTerminalOutcomes | null
  pegCandidates: number
  strategyCandidates: number
  formalValuations: number
  proxyValuations: number
}

/**
 * Stage counts come straight from the producer-published funnel.  The v2
 * implementation derived them from the already PEG-filtered rankings, which
 * under-counted the PEG pool (5 instead of 6) — never reconstruct
 * pre-filter stages from a filtered ranking again.
 */
export function releaseCoverageFunnel(release: Pick<Release, 'funnel'>, strategy: StrategyKey): CoverageFunnel {
  const funnel = release.funnel
  return {
    universe: funnel.universe,
    priceComplete: funnel.priceComplete,
    valuationComplete: funnel.valuationComplete,
    // The version marker gates the whole diagnostic group. Legacy releases may
    // contain an older partial set of zero-valued fields.
    growthInputComplete: funnel.growthCoverageVersion === 'growth-coverage-v1' ? funnel.growthInputComplete ?? null : null,
    growthValuationComplete: funnel.growthCoverageVersion === 'growth-coverage-v1' ? funnel.growthValuationComplete ?? null : null,
    growthThresholdCandidates: funnel.growthCoverageVersion === 'growth-coverage-v1' ? funnel.growthThresholdCandidates ?? null : null,
    growthHealthCandidates: funnel.growthCoverageVersion === 'growth-coverage-v1' ? funnel.growthHealthCandidates ?? null : null,
    growthMissingReasons: funnel.growthCoverageVersion === 'growth-coverage-v1' ? funnel.growthMissingReasons ?? null : null,
    growthEvaluationState: funnel.growthCoverageVersion === 'growth-coverage-v1' ? funnel.growthEvaluationState ?? null : null,
    growthTerminalOutcomes: funnel.growthCoverageVersion === 'growth-coverage-v1' ? funnel.growthTerminalOutcomes ?? null : null,
    pegCandidates: funnel.pegCandidates,
    strategyCandidates: funnel.strategyCandidates[strategy],
    formalValuations: funnel.formalValuations,
    proxyValuations: funnel.proxyValuations,
  }
}
