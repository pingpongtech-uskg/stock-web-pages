import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { StockSummary } from '../domain/types'
import { PegReviewSection } from './PegReviewSection'

const stocks = [
  { code: '2330', name: '台積電', pegReview: { status: 'needs_review', reasonCodes: ['nonconsecutive_quarters'], currentPeriod: '2025Q1–2025Q4', priorPeriod: null, sourceRefs: ['FinMind', 'https://example.com/filing'] } },
  { code: '1101', name: '台泥', pegReview: { status: 'not_applicable', reasonCodes: ['declining_growth'], currentPeriod: '2025Q1–2025Q4', priorPeriod: '2024Q1–2024Q4', currentTtmEps: 2, priorTtmEps: 4, epsGrowthPct: -50, asOf: '2026-03-01', quoteAsOf: '2026-03-01', latestEvidencePublishedAt: '2026-02-15', sourceRefs: [] } },
  { code: '9999', name: '已可計算', pegReview: { status: 'available', reasonCodes: [], currentPeriod: '2025Q3–2026Q2', priorPeriod: '2024Q3–2025Q2', expectedLatestQuarter: null, quoteAsOf: '2026-11-03', sourceRefs: [] } },
] as unknown as StockSummary[]

describe('PegReviewSection', () => {
  it('separates review-needed from not-applicable, explains TTM EPS YoY and links safe public sources', () => {
    const markup = renderToStaticMarkup(<PegReviewSection stocks={stocks} />)
    expect(markup).toContain('PEG 查核清單')
    expect(markup).toContain('待核對（1 檔）')
    expect(markup).toContain('不適用（1 檔）')
    expect(markup).toContain('季度不連續')
    expect(markup).toContain('TTM EPS 年增率')
    expect(markup).toContain('TTM EPS 年增率為負')
    expect(markup).toContain('本期 TTM EPS：2')
    expect(markup).toContain('前期 TTM EPS：4')
    expect(markup).toContain('年增率：-50.0%')
    expect(markup).toContain('計算截止日：2026-03-01（非行情日期）')
    expect(markup).toContain('最新財報發布：2026-02-15')
    expect(markup).toContain('實際行情日期：2026-03-01')
    expect(markup).toContain('href="https://example.com/filing"')
    expect(markup).toContain('9999 已可計算')
    expect(markup).not.toContain('href="FinMind"')
  })

  it('renders an empty review state for old snapshots without PEG diagnostics', () => {
    const markup = renderToStaticMarkup(<PegReviewSection stocks={[{ code: '2330', name: '台積電' } as StockSummary]} />)
    expect(markup).toContain('目前發布未提供逐檔 PEG 查核診斷')
  })

  it('lists verified PEG rows with EPS period and quote date', () => {
    const markup = renderToStaticMarkup(<PegReviewSection stocks={stocks} />)
    expect(markup).toContain('已核對可計算（1 檔）')
    expect(markup).toContain('最新已驗證 EPS 期別：2025Q3–2026Q2')
    expect(markup).toContain('實際行情日期：2026-11-03')
  })

  it('explains a behind-target statement without claiming the issuer failed to file', () => {
    const markup = renderToStaticMarkup(<PegReviewSection stocks={[
      { code: '2330', name: '台積電', pegReview: {
        status: 'needs_review', reasonCodes: ['latest_statement_unverified'],
        currentPeriod: '2025Q3–2026Q2', priorPeriod: '2024Q3–2025Q2',
        expectedLatestQuarter: '2026Q3', currentTtmEps: 100, priorTtmEps: 80,
        latestSourcePeriod: '2026Q2', financialCheckSource: 'FinMind:TaiwanStockFinancialStatements',
        financialCheckAt: '2026-11-03', epsGrowthPct: 25, asOf: '2026-11-03', quoteAsOf: '2026-11-03', sourceRefs: [],
      } },
    ] as unknown as StockSummary[]} />)
    expect(markup).toContain('已取得至 2026Q2，尚未確認最新季報，暫不顯示 PEG')
    expect(markup).not.toContain('來源已確認至 2026Q2')
    expect(markup).toContain('預期查核期別：2026Q3')
    expect(markup).toContain('本期 TTM EPS：100')
    expect(markup).toContain('年增率：25.0%')
  })

  it('reports a confirmed source quarter as missing EPS only when it is newer than the used window', () => {
    const markup = renderToStaticMarkup(<PegReviewSection stocks={[
      { code: '2330', name: '台積電', pegReview: {
        status: 'needs_review', reasonCodes: ['latest_statement_unverified'],
        currentPeriod: '2025Q2–2026Q1', priorPeriod: '2024Q2–2025Q1',
        latestSourcePeriod: '2026Q2', expectedLatestQuarter: '2026Q2',
        currentTtmEps: 90, priorTtmEps: 70, epsGrowthPct: 28.6, sourceRefs: [],
      } },
    ] as unknown as StockSummary[]} />)
    expect(markup).toContain('來源已確認至 2026Q2，該季 EPS 尚未納入計算，暫不顯示 PEG')
  })

  it('explains insufficient evidence count and malformed evidence dates', () => {
    const markup = renderToStaticMarkup(<PegReviewSection stocks={[
      { code: '1', name: '不足資料', pegReview: { status: 'needs_review', reasonCodes: ['insufficient_quarters'], currentPeriod: null, priorPeriod: null, availableQuarterCount: 3, sourceRefs: [] } },
      { code: '2', name: '日期錯誤', pegReview: { status: 'needs_review', reasonCodes: ['invalid_evidence_date'], currentPeriod: '2025Q1–2025Q1', priorPeriod: null, sourceRefs: [] } },
    ] as unknown as StockSummary[]} />)
    expect(markup).toContain('可用季度：3/8')
    expect(markup).toContain('財報證據日期格式無效')
  })
})
