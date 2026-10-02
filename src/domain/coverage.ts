import type { GrowthTerminalOutcomes, Release } from './types'
import type { StrategyKey } from './strategyPresentation'

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
