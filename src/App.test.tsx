import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { RankingRow, Release } from './domain/types'
import { CoverageFunnelView, dashboardStrategyRows } from './App'

const row: RankingRow = {
  rank: 1,
  code: '2330',
  name: '台積電',
  sector: '半導體業',
  value: 4.23,
  valueLabel: '%',
  status: 'pass',
  reason: '測試理由',
  currentPrice: 1000,
  fairPrice: 1450,
  valuePrice075: 1087.5,
  valuePrice066: 957,
  currentPeg: 0.52,
  pegBand: 'strict',
  valuationMethod: 'zulu-peg',
}

describe('dashboardStrategyRows', () => {
  it('maps the three tabs to their published ranking arrays', () => {
    const rankings: Release['rankings'] = {
      trust: [row],
      growth: [],
      lowPosition: [],
      lowBase: [],
      lowBaseGrowth: [],
      lowBaseQuality: [],
    }

    const blocks = dashboardStrategyRows({ rankings })

    expect(blocks.map((block) => block.presentation.key)).toEqual([
      'trust',
      'growth',
      'lowPosition',
    ])
    expect(blocks[0].rows).toBe(rankings.trust)
    expect(blocks[1].rows).toBe(rankings.growth)
    expect(blocks[2].rows).toBe(rankings.lowPosition)
  })
})

describe('growth coverage UI', () => {
  it('separates complete inputs from zero qualifying candidates and names missing inputs', () => {
    const markup = renderToStaticMarkup(<CoverageFunnelView strategy="growth" funnel={{
      universe: 100, priceComplete: 0, valuationComplete: 0, growthInputComplete: 12,
      growthValuationComplete: 8, growthThresholdCandidates: 0, growthHealthCandidates: 0,
      growthMissingReasons: [{ reason: 'dividendYield', count: 20 }], pegCandidates: 0,
      strategyCandidates: 0, formalValuations: 0, proxyValuations: 0,
    }} />)
    expect(markup).toContain('估值輸入完整')
    expect(markup).toContain('<strong>12</strong>')
    expect(markup).toContain('已計算 8 檔，但總報酬本益比門檻合格 0 檔')
    expect(markup).toContain('已確認股利 20 檔')
    expect(markup).toContain('成長健康 ≥ 4/5')
  })

  it('does not present absent legacy input coverage as zero', () => {
    const markup = renderToStaticMarkup(<CoverageFunnelView strategy="growth" funnel={{
      universe: 100, priceComplete: 10, valuationComplete: 4, growthInputComplete: null,
      growthValuationComplete: null, growthThresholdCandidates: null, growthHealthCandidates: null,
      growthMissingReasons: null, pegCandidates: 2, strategyCandidates: 1, formalValuations: 0, proxyValuations: 4,
    }} />)
    expect(markup).toContain('此發布未提供成長估值輸入覆蓋統計')
    expect(markup).toContain('不代表 0 檔合格')
  })

  it('does not describe missing all inputs as a fully evaluated zero-result strategy', () => {
    const markup = renderToStaticMarkup(<CoverageFunnelView strategy="growth" funnel={{
      universe: 100, priceComplete: 10, valuationComplete: 4, growthInputComplete: 0,
      growthValuationComplete: 0, growthThresholdCandidates: 0, growthHealthCandidates: 0,
      growthMissingReasons: [{ reason: 'dividendYield', count: 100 }], pegCandidates: 2,
      strategyCandidates: 0, formalValuations: 0, proxyValuations: 4,
    }} />)
    expect(markup).toContain('成長估值輸入完整 0 檔，可計算 0 檔')
    expect(markup).not.toContain('已計算 0 檔，但總報酬本益比門檻合格 0 檔')
    expect(markup).toContain('已確認股利 100 檔')
  })
})
