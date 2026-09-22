import type { Release } from './types'
import type { StrategyKey } from './strategyPresentation'

export interface CoverageFunnel {
  universe: number
  priceComplete: number
  valuationComplete: number
  growthValuationComplete: number
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
    growthValuationComplete: funnel.growthValuationComplete ?? 0,
    pegCandidates: funnel.pegCandidates,
    strategyCandidates: funnel.strategyCandidates[strategy],
    formalValuations: funnel.formalValuations,
    proxyValuations: funnel.proxyValuations,
  }
}
