export type MetricStatus = 'pass' | 'fail' | 'unknown' | 'not_applicable'
export type Freshness = 'current' | 'stale' | 'degraded' | 'unavailable'
export type PriceBasis = 'adjusted' | 'raw_proxy' | 'unknown'

export interface MetricValue<T = number> {
  value: T | null
  unit: string
  period: string
  availableAt: string | null
  status: MetricStatus
  sourceRefs: string[]
  formulaVersion: string
}

export interface PricePoint {
  date: string
  close: number | null
  /** Adjusted close used for the research curve when available. */
  adjustedClose?: number | null
  volume: number | null
  amount: number | null
  mid: number | null
  bands: Record<'-2' | '-1' | '0' | '1' | '2', number | null>
}

export interface ValuationSummary {
  method: 'zulu-peg'
  current_price: number
  current_pe: number
  current_eps: number | null
  eps_growth: number
  eps_growth_pct: number
  forward_eps: number
  current_peg: number
  reasonable_pe: number
  fair_price: number
  value_price_075: number
  value_price_066: number
  peg_acceptable_max: number
  peg_strict_max: number
  below_075: boolean
  below_066: boolean
  growth_method: string
  growth_method_label: string
  formula_version: string
}

export interface GrowthValuationSummary {
  method: 'growth-total-return-pe'
  formula_version: 'growth-total-return-pe-v1'
  status: 'available' | 'unavailable' | 'extreme'
  reason: string
  current_price: number | null
  current_pe: number | null
  ttm_eps: number | null
  earnings_growth: number | null
  growth_method: string
  growth_method_label: string
  dividend_yield: number | null
  conservative_growth: number | null
  total_return_pct: number | null
  total_return_pe: number | null
  forward_eps: number | null
  fair_pe: number | null
  fair_price: number | null
  buy_zone_price: number | null
  undervalued: boolean
  reasonable: boolean
  extreme_extrapolation: boolean
  growth_valid_years?: number
  growth_years?: number | null
}

export interface StockSummary {
  code: string
  name: string
  market: 'TWSE' | 'TPEx' | 'unknown'
  sector: string
  asOf: string | null
  lastPrice: number | null
  changePct: number | null
  adjustedLastPrice?: number | null
  adjustedChangePct?: number | null
  zScore: number | null
  slope: number | null
  fiveLineStatus: MetricStatus
  priceBasis?: PriceBasis
  adjustedPriceStatus?: MetricStatus
  qualityStatus: MetricStatus
  qualityProxyStatus?: MetricStatus
  qualityProxyPassCount?: number
  qualityProxyReason?: string
  growthStatus: MetricStatus
  growthProxyStatus?: MetricStatus
  growthProxyReason?: string
  /** Low-base strategy is a transparent proxy route, separate from formal entry. */
  lowBaseStatus?: MetricStatus
  lowBaseReason?: string
  lowBaseGates?: LowBaseGate[]
  lowBaseGrowthStatus?: MetricStatus
  lowBaseGrowthReason?: string
  lowBaseGrowthGates?: LowBaseGate[]
  lowBaseQualityStatus?: MetricStatus
  lowBaseQualityReason?: string
  lowBaseQualityGates?: LowBaseGate[]
  lowBaseGrowthWatchStatus?: MetricStatus
  lowBaseQualityWatchStatus?: MetricStatus
  liquidityStatus: MetricStatus
  dataStatus: MetricStatus
  signalState: '待補資料' | '值得研究' | '低位觀察' | '進場觀察' | '條件失效' | '資料不足'
  entryReasons: string[]
  risks: string[]
  institutionNetShares10: number | null
  participation10: number | null
  positiveDays10: number | null
  revenueGrowth3m: number | null
  /** Official monthly YoY fallback when a complete three-month window is unavailable. */
  revenueGrowthProxy?: number | null
  ttmOperatingProfitGrowth: number | null
  sourceRefs: string[]
  chipReference?: ChipReference
  valuation?: ValuationSummary
  growthValuation?: GrowthValuationSummary
  healthCategories?: HealthCategory[]
  healthScore?: { passCount: number; total: number; status: MetricStatus }
  healthInputSummary?: { valuationDate?: string | null; incomePeriods: number; balancePeriods: number; dividendRows: number; officialRevenueRows: number; source: string }
  /** Bounded raw FinMind rows retained for the next normalization pass. */
  financialInputs?: { incomeStatement: Array<Record<string, unknown>>; balanceSheet: Array<Record<string, unknown>>; cashFlow: Array<Record<string, unknown>> }
}

export interface RegressionSummary {
  status: MetricStatus
  method: string
  label: string
  intercept: number | null
  slope: number | null
  lastMid: number | null
  sigma: number | null
  z: number | null
  bands: Record<'-2' | '-1' | '0' | '1' | '2', number | null>
  coveragePct: number | null
  historyStart: string | null
  historyEnd: string | null
  signalEligible: boolean
  priceBasis?: PriceBasis
  observations?: number | null
  expectedObservations?: number | null
  reason: string
  sourceRefs: string[]
}

export interface InstitutionalPoint {
  date: string
  netShares: number | null
  volume: number | null
  status: MetricStatus
}

export interface RevenuePoint {
  month: string
  revenue: number | null
  availableAt: string | null
  status: MetricStatus
}

export interface RuleCheck {
  label: string
  status: MetricStatus
  value: string
  period: string
  explanation: string
  sourceRefs: string[]
}

export type ChipReferenceStatus = 'pass' | 'fail' | 'unknown'
export type ChipReferenceFreshness = 'current' | 'stale' | 'unavailable'

export interface ChipReferenceIndicator<TRaw = unknown> {
  status: ChipReferenceStatus
  value: string
  period: string
  sourceRefs: string[]
  rawValues?: TRaw
}

export interface ChipReference {
  schemaVersion: 'chip-reference-v1'
  status: ChipReferenceStatus
  displayOnly: true
  formulaVersion: 'chip-reference-v1'
  dataFreshness: ChipReferenceFreshness
  largeHolderTrend: ChipReferenceIndicator<number[]>
  directorSupervisor12m: ChipReferenceIndicator<{ latest: number; prior12m: number }>
  shareholderCountTrend: ChipReferenceIndicator<number[]>
  sourceRefs: string[]
  availableAt: string | null
}

export type HealthCategoryKey = 'quality' | 'growth' | 'chip' | 'cheap' | 'turnaround' | 'antiPitfall' | 'dividend'

export interface HealthCategory {
  key: HealthCategoryKey
  label: string
  passCount: number
  total: number
  threshold: number
  status: MetricStatus
  checks: RuleCheck[]
}

export interface HistorySnapshot {
  date: string
  z: number | null
  state: string
  reason: string
}

export interface StockDetail extends StockSummary {
  priceSeries: PricePoint[]
  regression: RegressionSummary
  institutionalDaily: InstitutionalPoint[]
  revenueMonthly: RevenuePoint[]
  qualityChecks: RuleCheck[]
  healthCategories?: HealthCategory[]
  healthScore?: { passCount: number; total: number; status: MetricStatus }
  healthInputSummary?: { valuationDate?: string | null; incomePeriods: number; balancePeriods: number; dividendRows: number; officialRevenueRows: number; source: string }
  /** Latest-period proxies; these never replace formal point-in-time checks. */
  qualityProxyChecks?: RuleCheck[]
  historySnapshots: HistorySnapshot[]
  notes: string[]
  detailLimitations: string[]
}

export interface RankingRow {
  rank: number
  sourceRank?: number
  previousRank?: number | null
  entryStatus?: 'new' | 'retained' | 'unknown' | 'not_applicable'
  code: string
  name: string
  sector: string
  value: number | null
  valueLabel: string
  status: MetricStatus
  reason: string
  chipReference?: ChipReference
  /** Rows from the low-base route are explicitly marked as proxy evidence. */
  proxy?: boolean
  evidenceLevel?: 'proxy' | 'formal'
  route?: 'lowBase' | 'lowBaseGrowth' | 'lowBaseQuality'
  gates?: LowBaseGate[]
  currentPrice?: number | null
  fairPrice?: number | null
  valuePrice075?: number | null
  valuePrice066?: number | null
  currentPeg?: number | null
  currentPe?: number | null
  currentEps?: number | null
  pegBand?: 'strict' | 'acceptable'
  valuationMethod?: 'zulu-peg' | 'growth-total-return-pe'
  valuationGrowthInput?: number
  valuationGrowthMethod?: string
  valuationGrowthMethodLabel?: string
  valuationEvidenceLevel?: 'formal' | 'proxy' | 'unavailable'
  valuationFormulaVersion?: string
  growthTotalReturnPe?: number | null
  growthConservativeGrowth?: number | null
  growthDividendYield?: number | null
  growthForwardEps?: number | null
  growthFairPrice?: number | null
  growthBuyZonePrice?: number | null
  growthValuationStatus?: 'available' | 'unavailable' | 'extreme'
  growthValuationReason?: string
  /** Proxy growth beyond 100% (or a scenario price >3× current) needs an
   *  explicit "do not extrapolate" warning next to the scenario prices. */
  extremeExtrapolation?: boolean
  priceBasis?: PriceBasis
  zScore?: number
  slope?: number
  regressionStart?: string | null
  regressionEnd?: string | null
  regressionObservations?: number | null
  regressionExpectedObservations?: number | null
  /** Producer-approved growth health evidence, when supplied by the release. */
  growthHealth?: {
    status: MetricStatus
    passCount: number
    total: number
    reason: string
    evidenceLevel?: 'proxy' | 'formal' | 'unavailable'
  }
  /** Low-position detail summary; unknown is deliberately not a pass. */
  lowPositionEvidence?: {
    growthHealthStatus?: MetricStatus
    growthHealthReason?: string
    evidenceLevel?: 'proxy' | 'formal' | 'unavailable'
  }
}

export interface LowBaseGate {
  key: string
  label: string
  status: MetricStatus
  value: string
  reason: string
}

export interface LowBaseGap {
  candidateCount: number
  trackedCount: number
  explanation: string
  missing: string[]
}

export interface Coverage {
  universeCount: number
  databaseCount: number
  candidateCount: number
  pendingCount: number
  financialCompleteCount: number
  priceCompleteCount: number
  completenessPct: number | null
  trackedCount?: number
  trackedCompleteCount?: number
  trackedCompletenessPct?: number | null
  universeCoveragePct?: number | null
  scopeLabel?: string
  finmindRequests: number | null
  queueStatus: string
}

export interface ResearchSummary {
  status: 'not_evaluable' | 'achieved' | 'not_achieved'
  reason: string
  cagr: number | null
  maxDrawdown: number | null
  periods: Array<{ label: string; status: string; cagr: number | null; maxDrawdown: number | null; trades: number | null }>
  proxyReadiness?: {
    label: string
    candidateCount: number
    formalEntryCount: number
    explanation: string
  }
}

export interface ReleaseFunnel {
  version: string
  universe: number
  priceComplete: number
  valuationComplete: number
  growthValuationComplete?: number
  pegCandidates: number
  growthCandidates?: number
  strategyCandidates: { trust: number; growth: number; lowPosition: number }
  formalValuations: number
  proxyValuations: number
  instrumentPolicy: string
  instrumentExcluded: number
}

export interface Release {
  schemaVersion: string
  strategyVersion: string
  formulaVersion: string
  runId: string
  marketDate: string | null
  generatedAt: string
  nextExpectedUpdateAt: string | null
  freshness: Freshness
  statusMessage: string
  sourceRefs: string[]
  coverage: Coverage
  /** Producer-published funnel stage counts; never derived from rankings. */
  funnel: ReleaseFunnel
  summary: {
    watchCount: number
    lowPositionCount: number
    candidateRouteCounts: {
      trust: number
      growth: number
      lowPosition: number
      lowBase?: number
      lowBaseGrowth?: number
      lowBaseQuality?: number
      lowBaseGrowthStrict?: number
      lowBaseQualityStrict?: number
    }
    addedToday: number
    improvedToday: number
    removedToday: number
    formalEntryCount?: number
    proxyCandidateCount?: number
    trustSignalCount?: number
    trustNewEntryCount?: number
    trustValuationVisibleCount?: number
    lowBaseGap?: LowBaseGap
    lowBaseGrowthGap?: LowBaseGap
    lowBaseQualityGap?: LowBaseGap
  }
  stocks: StockSummary[]
  rankings: {
    trust: RankingRow[]
    growth: RankingRow[]
    lowPosition: RankingRow[]
    lowBase: RankingRow[]
    lowBaseGrowth: RankingRow[]
    lowBaseQuality: RankingRow[]
  }
  research: ResearchSummary
}
