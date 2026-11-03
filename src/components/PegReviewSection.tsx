import type { PegReview, StockSummary } from '../domain/types'

const PEG_REASON_LABELS: Record<string, string> = {
  insufficient_quarters: '可用季度不足 8 季',
  nonconsecutive_quarters: '季度不連續',
  incomparable_quarters: '季度口徑或股數基礎不可比',
  incomparable_eps_basis: 'EPS 口徑或股數基礎不可比',
  missing_eps: '缺少 EPS',
  missing_quarter_eps: '季度 EPS 缺漏',
  missing_or_unavailable_quarter_eps: '季度 EPS 缺漏或不可用',
  missing_quarters: '缺少季度資料',
  conflicting_duplicate_quarter: '同季 EPS 資料互相衝突',
  nonpositive_ttm_eps: '目前 TTM EPS 非正值',
  nonpositive_prior_eps: '前期 TTM EPS 非正值',
  nonpositive_eps: '目前或前期 TTM EPS 非正值',
  nonpositive_growth: 'TTM EPS 年增率非正值',
  basis_conflict: '現價與本益比口徑不一致',
  stale_quote: '行情日期過舊',
  missing_same_day_price: '缺少同日價格',
  missing_positive_pe: '缺少有效本益比',
  missing_as_of: '缺少計算基準日',
  invalid_peg: 'PEG 計算結果無效',
}

export function pegReviewReasonLabel(code: string): string {
  return PEG_REASON_LABELS[code] ?? `資料需核對（${code.replaceAll('_', ' ')}）`
}

function isPublicHttpsUrl(value: string): boolean {
  try {
    const url = new URL(value)
    const host = url.hostname.toLowerCase()
    return url.protocol === 'https:'
      && !['localhost', '127.0.0.1', '::1'].includes(host)
      && !/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host)
      && !host.endsWith('.local')
      && !host.endsWith('.test')
      && !host.endsWith('.example')
      && host.includes('.')
      && !url.username && !url.password
  } catch {
    return false
  }
}

function ReviewStock({ stock, review }: { stock: StockSummary; review: PegReview }) {
  return (
    <li>
      <strong>{stock.code} {stock.name}</strong>
      <span>{review.reasonCodes.length ? review.reasonCodes.map(pegReviewReasonLabel).join('；') : '計算證據待確認'}</span>
      {(review.currentPeriod || review.priorPeriod) && (
        <small>本期：{review.currentPeriod ?? '未提供'} · 前期：{review.priorPeriod ?? '未提供'}</small>
      )}
      {review.sourceRefs.length > 0 && (
        <small className="peg-review-sources">
          來源：{review.sourceRefs.map((source, index) => (
            <span key={`${source}-${index}`}>
              {index > 0 ? '／' : ''}
              {isPublicHttpsUrl(source)
                ? <a href={source} target="_blank" rel="noopener noreferrer">來源連結</a>
                : source}
            </span>
          ))}
        </small>
      )}
    </li>
  )
}

export function PegReviewSection({ stocks }: { stocks: StockSummary[] }) {
  const needsReview = stocks.filter((stock) => stock.pegReview?.status === 'needs_review')
  const notApplicable = stocks.filter((stock) => stock.pegReview?.status === 'not_applicable')
  const reported = needsReview.length + notApplicable.length

  return (
    <details className="peg-review-section" id="peg-review">
      <summary>
        PEG 查核清單：待核對 {needsReview.length} 檔 · 不適用 {notApplicable.length} 檔
      </summary>
      <p>主要 PEG 使用同一公司連續、可比的兩組四季 TTM EPS 年增率；營收成長或多年 EPS 成長不會代替這項計算。</p>
      {reported === 0 && <p>目前發布未提供逐檔 PEG 查核診斷；舊版快照可能沒有此欄位。</p>}
      {needsReview.length > 0 && (
        <section aria-label="PEG 待核對股票">
          <h3>待核對（{needsReview.length} 檔）</h3>
          <ul>{needsReview.map((stock) => <ReviewStock key={stock.code} stock={stock} review={stock.pegReview!} />)}</ul>
        </section>
      )}
      {notApplicable.length > 0 && (
        <section aria-label="PEG 不適用股票">
          <h3>不適用（{notApplicable.length} 檔）</h3>
          <ul>{notApplicable.map((stock) => <ReviewStock key={stock.code} stock={stock} review={stock.pegReview!} />)}</ul>
        </section>
      )}
    </details>
  )
}
