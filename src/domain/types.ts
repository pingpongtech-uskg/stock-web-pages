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
  code: string
  name: string
  sector: string
  value: number | null
  valueLabel: string
  status: MetricStatus
  reason: string
  /** Rows from the low-base route are explicitly marked as proxy evidence. */
  proxy?: boolean
  evidenceLevel?: 'proxy' | 'formal'
  route?: 'lowBase' | 'lowBaseGrowth' | 'lowBaseQuality'
  gates?: LowBaseGate[]
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
