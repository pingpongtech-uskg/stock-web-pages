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
  valuationMethod: 'zulu',
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
    expect(markup).toContain('https://statementdog.com/analysis/2330/stock-health-check')
    expect(markup).not.toContain('通過')
    expect(markup).not.toContain('未知')
  })

  it('does not render rows without known valuation inputs', () => {
    const markup = renderToStaticMarkup(
      <StrategyCard presentation={strategyPresentations[1]} rows={[knownRow, unavailableRow]} />,
    )

    expect(markup).toContain('1 檔')
    expect(markup).toContain('2330')
    expect(markup).not.toContain('9999')
    expect(markup).not.toContain('未知')
  })

  it('renders a useful empty state when no known rows remain', () => {
    const markup = renderToStaticMarkup(
      <StrategyCard presentation={strategyPresentations[2]} rows={[unavailableRow]} />,
    )

    expect(markup).toContain('目前沒有同時具備低位條件')
    expect(markup).not.toContain('9999')
  })
})
