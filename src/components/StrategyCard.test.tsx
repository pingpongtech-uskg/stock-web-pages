import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ChipReference, RankingRow } from '../domain/types'
import { strategyPresentations } from '../domain/strategyPresentation'
import { ChipReferenceSummary, StrategyCard } from './StrategyCard'

const knownRow: RankingRow = {
  rank: 1,
  code: '2330',
  name: '台積電',
  sector: '半導體業',
  value: 12.3,
  valueLabel: '%',
  status: 'pass',
  reason: '已知營收成長條件符合',
  entryStatus: 'new',
  currentPrice: 1000,
  fairPrice: 1450,
  valuePrice075: 1087.5,
  valuePrice066: 957,
  currentPeg: 0.52,
  pegBand: 'strict',
  valuationMethod: 'zulu-peg',
  valuationGrowthMethod: 'ltm_reported_eps',
  valuationGrowthMethodLabel: 'LTM 已公布 EPS 成長',
  growthTotalReturnPe: 21 / 13,
  growthConservativeGrowth: 0.16,
  growthDividendYield: 0.05,
  growthForwardEps: 8.92,
  growthFairPrice: 187.32,
  growthBuyZonePrice: 156.1,
  growthValuationStatus: 'available',
  growthValuationReason: '可用的總報酬本益比（本站整理）',
}

const unavailableRow: RankingRow = {
  ...knownRow,
  code: '9999',
  name: '資料不足股',
  status: 'unknown',
  currentPrice: undefined,
  fairPrice: undefined,
}

describe('StrategyCard', () => {
  it('renders display-only chip reference summary in non-growth strategy tabs', () => {
    const chipReference: ChipReference = {
      schemaVersion: 'chip-reference-v1', status: 'pass' as const, displayOnly: true as const, formulaVersion: 'chip-reference-v1', dataFreshness: 'current' as const,
      largeHolderTrend: { status: 'pass' as const, value: '42.1% → 42.5% → 42.8%', period: '2026-06..2026-08', rawValues: [42.1, 42.5, 42.8], sourceRefs: ['TDCC'] },
      directorSupervisor12m: { status: 'fail' as const, value: '18.3% vs 17.9%', period: '2026-08 vs 2025-08', rawValues: { latest: 18.3, prior12m: 17.9 }, sourceRefs: ['TWSE OpenAPI'] },
      shareholderCountTrend: { status: 'unknown' as const, value: '未知', period: '2026-06..2026-08', sourceRefs: ['TDCC'] },
      sourceRefs: ['TDCC', 'TWSE OpenAPI'], availableAt: '2026-09-04',
    }
    const row: RankingRow = { ...knownRow, zScore: -0.4, slope: 0.1, chipReference }
    const markups = strategyPresentations.filter((presentation) => presentation.key !== 'growth').map((presentation) => renderToStaticMarkup(<StrategyCard presentation={presentation} rows={[row]} />))
    for (const markup of markups) {
      expect(markup).toContain('籌碼參考（不影響策略篩選）')
      expect(markup).toContain('大股東：近三個月觀察值逐期增加')
      expect(markup).toContain('董監：未通過')
      expect(markup).toContain('股東人數：未知／待補資料')
      expect(markup).toContain('大股東期別：2026-06..2026-08')
      expect(markup).toContain('董監期別：2026-08 vs 2025-08')
      expect(markup).toContain('股東人數期別：2026-06..2026-08')
      expect(markup).toContain('資料新鮮度：目前')
    }
  })

  it('hides chip reference on growth and renders the neutral total-return valuation', () => {
    const chipReference: ChipReference = {
      schemaVersion: 'chip-reference-v1', status: 'unknown', displayOnly: true, formulaVersion: 'chip-reference-v1', dataFreshness: 'unavailable',
      largeHolderTrend: { status: 'unknown', value: '—', period: '—', sourceRefs: [] },
      directorSupervisor12m: { status: 'unknown', value: '—', period: '—', sourceRefs: [] },
      shareholderCountTrend: { status: 'unknown', value: '—', period: '—', sourceRefs: [] },
      sourceRefs: [], availableAt: null,
    }
    const markup = renderToStaticMarkup(<StrategyCard presentation={strategyPresentations[1]} rows={[{ ...knownRow, chipReference }]} />)

    expect(markup).toContain('總報酬本益比（本站整理）')
    expect(markup).toContain('總報酬本益比')
    expect(markup).toContain('1.62')
    expect(markup).toContain('總報酬估值參考價（本站整理）')
    expect(markup).toContain('187.32')
    expect(markup).toContain('低估門檻參考價')
    expect(markup).toContain('祖魯 PEG 交叉參考')
    expect(markup).not.toContain('籌碼參考（不影響策略篩選）')
    expect(markup).not.toContain('董監：')
  })

  it('makes stale chip data explicit without changing row rendering', () => {
    const row: RankingRow = {
      ...knownRow,
      chipReference: {
        schemaVersion: 'chip-reference-v1', status: 'unknown', displayOnly: true, formulaVersion: 'chip-reference-v1', dataFreshness: 'stale',
        largeHolderTrend: { status: 'unknown', value: '—', period: '2025-01..2025-03', sourceRefs: [] },
        directorSupervisor12m: { status: 'unknown', value: '—', period: '—', sourceRefs: [] },
        shareholderCountTrend: { status: 'unknown', value: '—', period: '2025-01..2025-03', sourceRefs: [] },
        sourceRefs: [], availableAt: '2025-04-01',
      },
    }
    const markup = renderToStaticMarkup(<StrategyCard presentation={strategyPresentations[0]} rows={[row]} />)
    expect(markup).toContain('資料較舊')
    expect(markup).toContain('1 檔')
  })

  it('renders one consistent Zulu valuation and current price', () => {
    const markup = renderToStaticMarkup(
      <StrategyCard presentation={strategyPresentations[0]} rows={[knownRow]} />,
    )

    expect(markup).toContain('投信關注')
    expect(markup).toContain('1 檔')
    expect(markup).toContain('2330')
    expect(markup).toContain('現在價格')
    expect(markup).toContain('1,000')
    expect(markup).toContain('祖魯合理價')
    expect(markup).toContain('1,450')
    expect(markup).toContain('目前 PEG')
    expect(markup).toContain('0.52')
    expect(markup).toContain('PEG 0.66 價值帶')
    expect(markup).toContain('https://statementdog.com/analysis/2330/stock-health-check')
    expect(markup).not.toContain('成長健康：通過')
    expect(markup).not.toContain('未知')
  })

  it('hides retained trust rows and keeps only new entries', () => {
    const officialUnavailable: RankingRow = {
      ...knownRow,
      code: '9999',
      name: '估值不足股',
      currentPrice: null,
      fairPrice: null,
      valuePrice075: null,
      valuePrice066: null,
      currentPeg: null,
      valuationEvidenceLevel: undefined,
      entryStatus: 'retained',
    }
    const markup = renderToStaticMarkup(
      <StrategyCard presentation={strategyPresentations[0]} rows={[knownRow, officialUnavailable]} />,
    )

    expect(markup).toContain('1 檔')
    expect(markup).toContain('2330')
    expect(markup).not.toContain('9999')
  })

  it('labels growth proxy evidence and never fabricates unavailable prices', () => {
    const row: RankingRow = {
      ...knownRow,
      code: '2888',
      name: '營收代理股',
      currentPrice: 80,
      fairPrice: null,
      valuePrice075: null,
      valuePrice066: null,
      currentPeg: null,
      valuationEvidenceLevel: 'proxy',
      valuationGrowthMethodLabel: '營收成長代理',
      growthTotalReturnPe: null,
      growthConservativeGrowth: null,
      growthDividendYield: null,
      growthForwardEps: null,
      growthFairPrice: null,
      growthBuyZonePrice: null,
      growthValuationStatus: 'unavailable',
      growthValuationReason: '缺少已確認現金股利資料',
      growthHealth: { status: 'pass', passCount: 3, total: 4, reason: '成長健康證據' },
    }
    const markup = renderToStaticMarkup(<StrategyCard presentation={strategyPresentations[1]} rows={[row]} />)
    expect(markup).toContain('營收成長僅為代理，不等同 EPS 成長')
    expect(markup).toContain('總報酬估值')
    expect(markup).toContain('缺少已確認現金股利資料')
    expect(markup).toContain('PEG 不可用')
    expect(markup).not.toContain('<strong>0.00</strong>')
  })

  it('renders passed growth health with a positive badge semantic', () => {
    const row: RankingRow = {
      ...knownRow,
      code: '1504',
      name: '通過股',
      currentPrice: 69.5,
      currentPeg: null,
      fairPrice: null,
      valuePrice075: null,
      valuePrice066: null,
      zScore: -0.54,
      slope: 0.048,
      regressionStart: '2023-03-20',
      regressionEnd: '2026-09-18',
      priceBasis: 'adjusted',
      growthHealth: { status: 'pass', passCount: 5, total: 5, reason: '五項成長健康檢查已通過' },
      lowPositionEvidence: { growthHealthStatus: 'pass', growthHealthReason: '五項成長健康檢查已通過' },
    }
    const markup = renderToStaticMarkup(<StrategyCard presentation={strategyPresentations[2]} rows={[row]} />)

    expect(markup).toContain('成長健康：通過 5/5')
    expect(markup).toContain('class="evidence-badge formal">成長健康：通過 5/5')
    expect(markup).not.toContain('class="evidence-badge observation">成長健康：通過 5/5')
  })


  it('renders low-position observations without PEG and treats unknown health as unassessed', () => {
    const row: RankingRow = { ...knownRow, code: '1777', name: '低位觀察股', currentPrice: 50, fairPrice: null, valuePrice075: null, valuePrice066: null, currentPeg: null, zScore: -1.2, slope: 0.03, regressionStart: '2023-01-01', regressionEnd: '2026-06-30', priceBasis: 'adjusted', lowPositionEvidence: { growthHealthStatus: 'unknown', growthHealthReason: '必要資料不足' } }
    const markup = renderToStaticMarkup(<StrategyCard presentation={strategyPresentations[2]} rows={[row]} />)
    expect(markup).toContain('價格／回歸觀察')
    expect(markup).toContain('成長健康：未知／未評估')
    expect(markup).toContain('Z -1.20')
    expect(markup).toContain('slope 0.030')
    expect(markup).toContain('現在價格')
    expect(markup).toContain('目前 PEG')
    expect(markup).toContain('PEG 不可用')
    expect(markup).not.toContain('成長健康：通過')
  })

  it('marks a trust top10 newcomer without changing PEG display', () => {
    const markup = renderToStaticMarkup(
      <StrategyCard presentation={strategyPresentations[0]} rows={[{ ...knownRow, entryStatus: 'new' }]} />,
    )

    expect(markup).toContain('新進榜')
    expect(markup).toContain('目前 PEG')
    expect(markup).toContain('0.52')
  })

  it('keeps a complete-value observation row visible without exposing machine unknown', () => {
    const observationRow: RankingRow = {
      ...knownRow,
      code: '3413',
      name: '京鼎',
      status: 'unknown',
      reason: 'Z -0.35 ≤ 0；低位代理，完整歷史條件仍待驗證',
      valuationGrowthMethod: 'three_month_revenue_proxy',
      valuationGrowthMethodLabel: '三月營收成長代理',
      zScore: -0.35,
      slope: 0.03,
    }
    const markup = renderToStaticMarkup(
      <StrategyCard presentation={strategyPresentations[2]} rows={[observationRow]} />,
    )
    expect(markup).toContain('1 檔')
    expect(markup).toContain('3413')
    expect(markup).toContain('價格／回歸觀察')
    expect(markup).toContain('三月營收成長代理')
    expect(markup).not.toContain('unknown')
    expect(markup).toContain('目前 PEG')
    expect(markup).toContain('0.52')
  })

  it('renders a useful empty state when no known rows remain', () => {
    const markup = renderToStaticMarkup(
      <StrategyCard presentation={strategyPresentations[2]} rows={[unavailableRow]} />,
    )

    expect(markup).toContain('3.5 年回歸 Z ≤ 0')
    expect(markup).toContain('PEG 缺值不會排除低位觀察')
    expect(markup).not.toContain('9999')
  })

  it('labels proxy scenario prices and warns on extreme extrapolation', () => {
    const proxyRow: RankingRow = {
      ...knownRow,
      code: '2382',
      name: '廣達',
      valuationGrowthMethod: 'three_month_revenue_proxy',
      valuationGrowthMethodLabel: '三月營收成長代理',
      valuationEvidenceLevel: 'proxy',
      valuationGrowthInput: 1.7745,
      currentPe: 14.66,
      currentEps: 22.95,
      extremeExtrapolation: true,
      currentPrice: 336.5,
      fairPrice: 11301.25,
      valuePrice075: 8475.94,
      valuePrice066: 7458.82,
      regressionStart: '2023-03-13',
      regressionEnd: '2026-09-11',
      regressionObservations: 853,
      regressionExpectedObservations: 853,
      priceBasis: 'adjusted',
    }

    const markup = renderToStaticMarkup(
      <StrategyCard presentation={strategyPresentations[0]} rows={[proxyRow]} />,
    )

    expect(markup).toContain('代理情境價（PEG=0.75）')
    expect(markup).toContain('代理情境價（PEG=0.66）')
    expect(markup).toContain('高成長不可直接外推')
    expect(markup).toContain('代理情境價為現價 33.6 倍')
    expect(markup).toContain('成長輸入 177.4%')
    expect(markup).toContain('回歸 2023-03-13～2026-09-11（853/853 筆，Adj Close）')
    expect(markup).not.toContain('PEG 0.75 價值帶')
    expect(markup).not.toContain('未知')
  })

  it('shows data freshness warnings on affected stock rows while keeping the release visible', () => {
    const row = {
      ...knownRow,
      code: '6173',
      name: '信昌電',
      dataFreshness: 'stale',
      freshnessWarnings: ['股價資料截至 2026-10-06（目標 2026-10-07）', '投信十日資料不完整'],
    } as RankingRow
    const markup = renderToStaticMarkup(<StrategyCard presentation={strategyPresentations[0]} rows={[row]} />)

    expect(markup).toContain('6173 信昌電')
    expect(markup).toContain('資料提醒：股價資料截至 2026-10-06（目標 2026-10-07）')
    expect(markup).toContain('投信十日資料不完整')
  })
})


it('labels equal director comparison as stable or increasing and preserves partial evidence', () => {
  const markup = renderToStaticMarkup(<ChipReferenceSummary chip={{
    schemaVersion: 'chip-reference-v1', status: 'unknown', displayOnly: true, formulaVersion: 'chip-reference-v1', dataFreshness: 'current',
    largeHolderTrend: { status: 'unknown', value: '40 → 41 → ?', period: '2026-07..2026-09', sourceRefs: ['TDCC'] },
    directorSupervisor12m: { status: 'pass', value: '0% vs 0%', period: '2026-09 vs 2025-09', sourceRefs: ['TWSE'] },
    shareholderCountTrend: { status: 'pass', value: '300 → 200 → 100', period: '2026-07..2026-09', sourceRefs: ['TDCC'] },
    sourceRefs: ['TDCC', 'TWSE'], availableAt: null,
  }} />)
  expect(markup).toContain('董監：較去年同月持平或增加（0% vs 0%）')
  expect(markup).toContain('股東人數：近三個月觀察值逐期減少')
  expect(markup).toContain('未知／待補資料（40 → 41 → ?）')
  expect(markup).toContain('董監期別：2026-09 vs 2025-09')
  expect(markup).not.toContain('可用於')
})

it('shows historical retrieval provenance and official shares without fabricated percentages', () => {
  const empty = { status: 'unknown' as const, value: '—', period: '—', sourceRefs: [] }
  const markup = renderToStaticMarkup(<ChipReferenceSummary chip={{
    schemaVersion: 'chip-reference-v1', status: 'unknown', displayOnly: true, formulaVersion: 'chip-reference-v1', dataFreshness: 'current',
    largeHolderTrend: empty, shareholderCountTrend: empty,
    directorSupervisor12m: { ...empty, value: '官方合計 123456股；比例待補', period: '2026-09 vs 2025-09', sourceDates: ['2026-09'], historicalBackfill: true, retrievedAt: '2026-10-04T11:00:00Z' },
    sourceRefs: ['MOPS'], availableAt: null,
  }} />)
  expect(markup).toContain('官方合計 123456股；比例待補')
  expect(markup).toContain('官方觀察日期：2026-09')
  expect(markup).toContain('歷史資料補取得：2026-10-04T11:00:00Z；發布時間未確認')
  expect(markup).not.toContain('可用於')
})
