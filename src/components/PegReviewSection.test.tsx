import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { StockSummary } from '../domain/types'
import { PegReviewSection } from './PegReviewSection'

const stocks = [
  { code: '2330', name: '台積電', pegReview: { status: 'needs_review', reasonCodes: ['nonconsecutive_quarters'], currentPeriod: '2025Q1–2025Q4', priorPeriod: null, sourceRefs: ['FinMind', 'https://example.com/filing'] } },
  { code: '1101', name: '台泥', pegReview: { status: 'not_applicable', reasonCodes: ['nonpositive_growth'], currentPeriod: null, priorPeriod: '2024Q1–2024Q4', sourceRefs: [] } },
  { code: '9999', name: '已可計算', pegReview: { status: 'available', reasonCodes: [], currentPeriod: null, priorPeriod: null, sourceRefs: [] } },
] as unknown as StockSummary[]

describe('PegReviewSection', () => {
  it('separates review-needed from not-applicable, explains TTM EPS YoY and links safe public sources', () => {
    const markup = renderToStaticMarkup(<PegReviewSection stocks={stocks} />)
    expect(markup).toContain('PEG 查核清單')
    expect(markup).toContain('待核對（1 檔）')
    expect(markup).toContain('不適用（1 檔）')
    expect(markup).toContain('季度不連續')
    expect(markup).toContain('TTM EPS 年增率')
    expect(markup).toContain('href="https://example.com/filing"')
    expect(markup).not.toContain('9999')
    expect(markup).not.toContain('href="FinMind"')
  })

  it('renders an empty review state for old snapshots without PEG diagnostics', () => {
    const markup = renderToStaticMarkup(<PegReviewSection stocks={[{ code: '2330', name: '台積電' } as StockSummary]} />)
    expect(markup).toContain('目前發布未提供逐檔 PEG 查核診斷')
  })
})
