import { describe, expect, it } from 'vitest'
import type { RankingRow, Release } from './domain/types'
import { dashboardStrategyRows } from './App'

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
