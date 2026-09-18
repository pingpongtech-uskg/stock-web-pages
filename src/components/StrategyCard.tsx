import type { RankingRow } from '../domain/types'
import { statementDogHealthCheckUrl } from '../domain/statementDog'
import type { StrategyKey, StrategyPresentation } from '../domain/strategyPresentation'
import { trackEvent } from '../domain/events'
import { EmptyState } from './EmptyState'

interface StrategyCardProps {
  presentation: StrategyPresentation
  rows: RankingRow[]
}

type KnownRow = RankingRow & {
  currentPrice: number
  fairPrice: number
  valuePrice075: number
  valuePrice066: number
  currentPeg: number
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
        <p className="valuation-formula"><strong>祖魯 PEG 標準：</strong>{presentation.valuationFormula}</p>
      </div>

      {knownRows.length ? (
        <div className="stock-list" aria-label={`${presentation.title}股票清單`}>
          {knownRows.map((row) => (
            <StockRow key={`${presentation.key}-${row.code}`} row={row} metricLabel={presentation.metricLabel} strategy={presentation.key} />
          ))}
        </div>
      ) : (
        <EmptyState title="目前沒有可顯示候選" body={presentation.emptyBody} />
      )}
    </section>
  )
}

function isKnownRow(row: RankingRow): row is KnownRow {
  return row.status !== 'fail'
    && row.status !== 'not_applicable'
    && Number.isFinite(row.currentPrice)
    && Number.isFinite(row.fairPrice)
    && Number.isFinite(row.valuePrice075)
    && Number.isFinite(row.valuePrice066)
    && Number.isFinite(row.currentPeg)
}

function isProxyValuation(row: RankingRow): boolean {
  return row.valuationEvidenceLevel === 'proxy'
    || Boolean(row.valuationGrowthMethod?.includes('proxy'))
    || Boolean(row.valuationGrowthMethodLabel?.includes('代理'))
}

function valuationInputsLabel(row: KnownRow): string | null {
  const parts: string[] = []
  if (Number.isFinite(row.valuationGrowthInput)) parts.push(`成長輸入 ${(Number(row.valuationGrowthInput) * 100).toFixed(1)}%`)
  if (Number.isFinite(row.currentPe)) parts.push(`PE ${Number(row.currentPe).toFixed(2)}`)
  if (Number.isFinite(row.currentEps)) parts.push(`EPS ${Number(row.currentEps).toFixed(2)}（現價÷PE）`)
  return parts.length ? parts.join(' · ') : null
}

function regressionWindowLabel(row: KnownRow): string | null {
  if (!row.regressionStart || !row.regressionEnd) return null
  const observations = Number.isFinite(row.regressionObservations) ? Number(row.regressionObservations) : null
  const expected = Number.isFinite(row.regressionExpectedObservations) ? Number(row.regressionExpectedObservations) : null
  const basisText = row.priceBasis === 'adjusted' ? 'Adj Close' : row.priceBasis === 'raw_proxy' ? '未調整收盤' : ''
  const countText = observations !== null && expected !== null ? `${observations}/${expected} 筆` : null
  const meta = [countText, basisText].filter(Boolean).join('，')
  return meta
    ? `回歸 ${row.regressionStart}～${row.regressionEnd}（${meta}）`
    : `回歸 ${row.regressionStart}～${row.regressionEnd}`
}

function StockRow({ row, metricLabel, strategy }: { row: KnownRow; metricLabel: string; strategy: StrategyKey }) {
  const href = statementDogHealthCheckUrl(row.code)
  const proxy = isProxyValuation(row)
  const observation = row.status !== 'pass'
  const pegThreshold = row.pegBand === 'strict' ? '< 0.66' : '< 0.75'
  const pegBadge = proxy ? `PEG ${pegThreshold}（代理）` : row.pegBand === 'strict' ? 'PEG < 0.66 嚴格' : 'PEG < 0.75 可接受'
  const fairPriceLabel = proxy ? '祖魯基準價（代理情境，PEG=1）' : '祖魯合理價（PEG=1）'
  const band075Label = proxy ? '代理情境價（PEG=0.75）' : 'PEG 0.75 價值帶'
  const band066Label = proxy ? '代理情境價（PEG=0.66）' : 'PEG 0.66 價值帶'
  const extreme = proxy && row.extremeExtrapolation === true
  const ratio = extreme && row.currentPrice > 0 && Number.isFinite(row.fairPrice) ? row.fairPrice / row.currentPrice : null
  const inputsLabel = valuationInputsLabel(row)
  const windowLabel = regressionWindowLabel(row)
  const content = (
    <>
      <span className="stock-rank">{String(row.rank).padStart(2, '0')}</span>
      <span className="stock-main">
        <strong>{row.code} {row.name}</strong>
        <small>{row.sector || '產業未填'}</small>
        <span className="stock-evidence">
          <em className={observation ? 'evidence-badge observation' : 'evidence-badge'}>{observation ? '觀察候選' : '策略條件'}</em>
          <em className={proxy ? 'evidence-badge proxy' : 'evidence-badge formal'}>{proxy ? '估算 PEG' : '正式 EPS PEG'}</em>
        </span>
        <span className="stock-reason">{knownReason(row.reason, row.valuationGrowthMethodLabel, row.status)}</span>
      </span>
      <span className="stock-metric">
        <small>{metricLabel}</small>
        <strong>{formatRankingValue(row)}</strong>
        {Number.isFinite(row.slope) && <small>slope {Number(row.slope).toFixed(3)}</small>}
      </span>
      <span className="stock-peg">
        <small>{proxy ? '目前 PEG（估算）' : '目前 PEG'}</small>
        <strong>{row.currentPeg.toFixed(2)}</strong>
        <em className={row.pegBand === 'strict' ? 'peg-badge strict' : 'peg-badge'}>{pegBadge}</em>
      </span>
      <span className="stock-prices">
        <span><small>現在價格</small><strong>{formatPrice(row.currentPrice)}</strong></span>
        <span><small>{fairPriceLabel}</small><strong>{formatPrice(row.fairPrice)}</strong></span>
        <span><small>{band075Label}</small><strong>{formatPrice(row.valuePrice075)}</strong></span>
        <span><small>{band066Label}</small><strong>{formatPrice(row.valuePrice066)}</strong></span>
        {extreme && (
          <em className="extrapolation-warning">
            高成長不可直接外推{ratio ? `（代理情境價為現價 ${ratio.toFixed(1)} 倍）` : ''}
          </em>
        )}
        {windowLabel && <small className="stock-window">{windowLabel}</small>}
        {inputsLabel && <small className="stock-valuation-inputs">{inputsLabel}</small>}
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
      aria-label={`${row.code} ${row.name}，目前 PEG ${row.currentPeg.toFixed(2)}，開啟財報狗股票健檢`}
      onClick={() => trackEvent('candidate_external_open', { strategy, code: row.code })}
    >
      {content}
    </a>
  )
}

function knownReason(reason: string, methodLabel: string | undefined, status: RankingRow['status']) {
  const visible = reason
    .split(/[；;]/)
    .map((part) => part.trim())
    .filter((part) => part && !/^(unknown|未知|待核對)$/i.test(part))
  if (status !== 'pass') visible.push('資料仍在觀察層級')
  if (methodLabel) visible.push(`成長輸入：${methodLabel}`)
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
