import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { RankingRow } from '../domain/types'
import { strategyPresentations } from '../domain/strategyPresentation'
import { StrategyCard } from './StrategyCard'

const knownRow: RankingRow = {
  rank: 1,
  code: '2330',
  name: '台積電',
  sector: '半導體業',
  value: 12.3,
  valueLabel: '%',
  status: 'pass',
  reason: '已知營收成長條件符合',
  currentPrice: 1000,
  fairPrice: 1450,
  valuePrice075: 1087.5,
  valuePrice066: 957,
  currentPeg: 0.52,
  pegBand: 'strict',
  valuationMethod: 'zulu-peg',
  valuationGrowthMethod: 'ltm_reported_eps',
  valuationGrowthMethodLabel: 'LTM 已公布 EPS 成長',
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
    expect(markup).not.toContain('通過')
    expect(markup).not.toContain('未知')
  })

  it('renders an official trust row when valuation is unavailable', () => {
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

    expect(markup).toContain('2 檔')
    expect(markup).toContain('2330')
    expect(markup).toContain('9999')
    expect(markup).toContain('PEG 不可用')
    expect(markup).toContain('估值資料不足')
    expect(markup).toContain('現在價格')
    expect(markup).toContain('<strong>—</strong>')
    expect(markup).not.toContain('<strong>0.00</strong>')
  })

  it('labels growth proxy evidence and never fabricates unavailable prices', () => {
    const row: RankingRow = { ...knownRow, code: '2888', name: '營收代理股', currentPrice: 80, fairPrice: null, valuePrice075: null, valuePrice066: null, currentPeg: null, valuationEvidenceLevel: 'proxy', valuationGrowthMethodLabel: '營收成長代理', growthHealth: { status: 'pass', passCount: 3, total: 4, reason: '成長健康證據' } }
    const markup = renderToStaticMarkup(<StrategyCard presentation={strategyPresentations[1]} rows={[row]} />)
    expect(markup).toContain('營收成長僅為代理，不等同 EPS 成長')
    expect(markup).toContain('正式／代理證據：代理')
    expect(markup).toContain('估值資料不足')
    expect(markup).toContain('PEG 不可用')
    expect(markup).not.toContain('<strong>0.00</strong>')
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
    expect(markup).not.toContain('通過')
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

    expect(markup).toContain('目前共同 A 母體沒有同時具備')
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
})
