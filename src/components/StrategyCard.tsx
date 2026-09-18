import type { RankingRow } from '../domain/types'
import { statementDogHealthCheckUrl } from '../domain/statementDog'
import type { StrategyPresentation } from '../domain/strategyPresentation'
import { EmptyState } from './EmptyState'

interface StrategyCardProps {
  presentation: StrategyPresentation
  rows: RankingRow[]
}

export function StrategyCard({ presentation, rows }: StrategyCardProps) {
  const knownRows = rows.filter(isKnownRow)
  return (
    <section className={`strategy-card accent-${presentation.accent}`} data-strategy={presentation.key}>
      <header className="strategy-card-header">
        <div>
          <p className="strategy-eyebrow">{presentation.horizon}</p>
          <h2>{presentation.title}</h2>
          <p className="strategy-subtitle">{presentation.subtitle}</p>
        </div>
        <strong className="strategy-count">{knownRows.length} 檔</strong>
      </header>

      <div className="strategy-description">
        <p>{presentation.description}</p>
        <p><strong>條件：</strong>{presentation.condition}</p>
        <p><strong>怎麼篩：</strong>{presentation.selection}</p>
        <p><strong>{presentation.valuationNote}</strong></p>
        <p className="valuation-formula"><strong>祖魯合理價標準：</strong>{presentation.valuationFormula}</p>
      </div>

      {knownRows.length ? (
        <div className="stock-list" aria-label={`${presentation.title}股票清單`}>
          {knownRows.map((row) => <StockRow key={`${presentation.key}-${row.code}`} row={row} metricLabel={presentation.metricLabel} />)}
        </div>
      ) : (
        <EmptyState title="目前沒有可顯示候選" body={presentation.emptyBody} />
      )}
    </section>
  )
}

function isKnownRow(row: RankingRow): row is RankingRow & { currentPrice: number; fairPrice: number } {
  return row.status === 'pass'
    && Number.isFinite(row.currentPrice)
    && Number.isFinite(row.fairPrice)
}

function StockRow({ row, metricLabel }: { row: RankingRow & { currentPrice: number; fairPrice: number }; metricLabel: string }) {
  const href = statementDogHealthCheckUrl(row.code)
  const content = (
    <>
      <span className="stock-rank">{String(row.rank).padStart(2, '0')}</span>
      <span className="stock-main">
        <strong>{row.code} {row.name}</strong>
        <small>{row.sector || '產業未填'}</small>
        <span className="stock-reason">{knownReason(row.reason)}</span>
      </span>
      <span className="stock-metric">
        <small>{metricLabel}</small>
        <strong>{formatRankingValue(row)}</strong>
      </span>
      <span className="stock-prices">
        <span><small>現在價格</small><strong>{formatPrice(row.currentPrice)}</strong></span>
        <span><small>祖魯合理價</small><strong>{formatPrice(row.fairPrice)}</strong></span>
      </span>
      <span className="health-link-label">財報狗健檢 ↗</span>
    </>
  )

  if (!href) return <div className="stock-link stock-link-invalid" data-stock-code={row.code}>{content}</div>
  return (
    <a
      className="stock-link"
      data-stock-code={row.code}
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`${row.code} ${row.name}，開啟財報狗股票健檢`}
    >
      {content}
    </a>
  )
}

function knownReason(reason: string) {
  const visible = reason
    .split(/[；;]/)
    .map((part) => part.trim())
    .filter((part) => part && !/(unknown|未知|待核對|待驗證|尚無)/i.test(part))
  return visible.join('；') || '符合已知篩選條件'
}

function formatPrice(value: number) {
  return value.toLocaleString('zh-TW', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
}

function formatRankingValue(row: RankingRow) {
  if (row.value == null || !Number.isFinite(row.value)) return '—'
  const value = row.value.toLocaleString('zh-TW', { maximumFractionDigits: 2 })
  return `${value}${row.valueLabel}`
}
