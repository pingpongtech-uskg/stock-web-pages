export type MetricStatus = 'pass' | 'fail' | 'unknown' | 'not_applicable'
export type Freshness = 'current' | 'stale' | 'degraded' | 'unavailable'

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
  zScore: number | null
  slope: number | null
  fiveLineStatus: MetricStatus
  qualityStatus: MetricStatus
  growthStatus: MetricStatus
  liquidityStatus: MetricStatus
  dataStatus: MetricStatus
  signalState: '待補資料' | '值得研究' | '低位觀察' | '進場觀察' | '條件失效' | '資料不足'
  entryReasons: string[]
  risks: string[]
  institutionNetShares10: number | null
  participation10: number | null
  positiveDays10: number | null
  revenueGrowth3m: number | null
  ttmOperatingProfitGrowth: number | null
  sourceRefs: string[]
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
}

export interface Coverage {
  universeCount: number
  databaseCount: number
  candidateCount: number
  pendingCount: number
  financialCompleteCount: number
  priceCompleteCount: number
  completenessPct: number | null
  finmindRequests: number | null
  queueStatus: string
}

export interface ResearchSummary {
  status: 'not_evaluable' | 'achieved' | 'not_achieved'
  reason: string
  cagr: number | null
  maxDrawdown: number | null
  periods: Array<{ label: string; status: string; cagr: number | null; maxDrawdown: number | null; trades: number | null }>
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
    candidateRouteCounts: { trust: number; growth: number; lowPosition: number }
    addedToday: number
    improvedToday: number
    removedToday: number
  }
  stocks: StockSummary[]
  rankings: {
    trust: RankingRow[]
    growth: RankingRow[]
    lowPosition: RankingRow[]
  }
  research: ResearchSummary
}
