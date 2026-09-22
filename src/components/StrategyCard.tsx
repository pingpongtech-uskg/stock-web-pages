import type { ChipReference, RankingRow, MetricStatus } from '../domain/types'
import { statementDogHealthCheckUrl } from '../domain/statementDog'
import type { StrategyKey, StrategyPresentation } from '../domain/strategyPresentation'
import { trackEvent } from '../domain/events'
import { EmptyState } from './EmptyState'

interface StrategyCardProps {
  presentation: StrategyPresentation
  rows: RankingRow[]
}

export function StrategyCard({ presentation, rows }: StrategyCardProps) {
  const visibleRows = rows.filter((row) => isRenderableRow(row, presentation.key))
  return (
    <section className={`strategy-card accent-${presentation.accent}`} data-strategy={presentation.key}>
      <header className="strategy-card-header">
        <div>
          <p className="strategy-eyebrow">{presentation.horizon}</p>
          <h2>{presentation.title}</h2>
          <p className="strategy-subtitle">{presentation.subtitle}</p>
        </div>
        <strong className="strategy-count">{visibleRows.length} 檔</strong>
      </header>

      <div className="strategy-description">
        <p>{presentation.description}</p>
        <p><strong>條件：</strong>{presentation.condition}</p>
        <p><strong>怎麼篩：</strong>{presentation.selection}</p>
        <p><strong>{presentation.valuationNote}</strong></p>
        <p className="valuation-formula"><strong>{presentation.key === 'growth' ? '影片版總報酬本益比：' : '祖魯 PEG 標準：'}</strong>{presentation.valuationFormula}</p>
      </div>

      {visibleRows.length ? (
        <div className="stock-list" aria-label={`${presentation.title}股票清單`}>
          {visibleRows.map((row) => (
            <StockRow key={`${presentation.key}-${row.code}`} row={row} metricLabel={presentation.metricLabel} strategy={presentation.key} />
          ))}
        </div>
      ) : (
        <EmptyState title="目前沒有可顯示候選" body={presentation.emptyBody} />
      )}
    </section>
  )
}

function isRenderableRow(row: RankingRow, strategy: StrategyKey): boolean {
  if (strategy === 'trust') return row.entryStatus === 'new'
  if (strategy === 'lowPosition') {
    return row.status !== 'fail'
      && row.status !== 'not_applicable'
      && Number.isFinite(row.zScore)
      && Number.isFinite(row.slope)
  }
  return row.status !== 'fail' && row.status !== 'not_applicable'
}

function isProxyValuation(row: RankingRow): boolean {
  return row.valuationEvidenceLevel === 'proxy'
    || Boolean(row.valuationGrowthMethod?.includes('proxy'))
    || Boolean(row.valuationGrowthMethodLabel?.includes('代理'))
}

function valuationInputsLabel(row: RankingRow): string | null {
  const parts: string[] = []
  if (Number.isFinite(row.valuationGrowthInput)) parts.push(`成長輸入 ${(Number(row.valuationGrowthInput) * 100).toFixed(1)}%`)
  if (Number.isFinite(row.currentPe)) parts.push(`PE ${Number(row.currentPe).toFixed(2)}`)
  if (Number.isFinite(row.currentEps)) parts.push(`EPS ${Number(row.currentEps).toFixed(2)}（現價÷PE）`)
  return parts.length ? parts.join(' · ') : null
}

function regressionWindowLabel(row: RankingRow): string | null {
  if (!row.regressionStart || !row.regressionEnd) return null
  const observations = Number.isFinite(row.regressionObservations) ? Number(row.regressionObservations) : null
  const expected = Number.isFinite(row.regressionExpectedObservations) ? Number(row.regressionExpectedObservations) : null
  const basisText = row.priceBasis === 'adjusted' ? 'Adj Close' : row.priceBasis === 'raw_proxy' ? '未調整收盤' : ''
  const countText = observations !== null && expected !== null ? `${observations}/${expected} 筆` : null
  const meta = [countText, basisText].filter(Boolean).join('，')
  return meta ? `回歸 ${row.regressionStart}～${row.regressionEnd}（${meta}）` : `回歸 ${row.regressionStart}～${row.regressionEnd}`
}

function formatMaybePrice(value: number | null | undefined): string {
  return Number.isFinite(value) ? formatPrice(Number(value)) : '—'
}

function formatMaybePeg(value: number | null | undefined): string {
  return Number.isFinite(value) ? Number(value).toFixed(2) : 'PEG 不可用'
}

function formatMaybeTotalReturnPe(value: number | null | undefined): string {
  return Number.isFinite(value) ? Number(value).toFixed(2) : '不可用'
}

function growthValuationInputsLabel(row: RankingRow): string | null {
  const parts: string[] = []
  if (Number.isFinite(row.growthConservativeGrowth)) parts.push(`保守成長 ${(Number(row.growthConservativeGrowth) * 100).toFixed(1)}%`)
  if (Number.isFinite(row.growthDividendYield)) parts.push(`股利殖利率 ${(Number(row.growthDividendYield) * 100).toFixed(2)}%`)
  if (Number.isFinite(row.currentPe)) parts.push(`PE ${Number(row.currentPe).toFixed(2)}`)
  if (Number.isFinite(row.growthForwardEps)) parts.push(`Forward EPS ${Number(row.growthForwardEps).toFixed(2)}`)
  return parts.length ? parts.join(' · ') : null
}

function formatZ(value: number | null | undefined): string {
  return Number.isFinite(value) ? `Z ${Number(value).toFixed(2)}` : 'Z —'
}

function growthHealthStatus(row: RankingRow): string {
  return row.lowPositionEvidence?.growthHealthStatus ?? row.growthHealth?.status ?? 'unknown'
}

function healthLabel(row: RankingRow): string {
  const status = growthHealthStatus(row)
  if (status === 'unknown') return '成長健康：未知／未評估'
  if (status === 'pass') return `成長健康：通過${row.growthHealth ? ` ${row.growthHealth.passCount}/${row.growthHealth.total}` : ''}`
  if (status === 'fail') return '成長健康：未通過'
  return '成長健康：不適用'
}

function healthBadgeClass(row: RankingRow): string {
  const status = growthHealthStatus(row)
  if (status === 'pass') return 'evidence-badge formal'
  if (status === 'fail') return 'evidence-badge fail'
  return 'evidence-badge observation'
}

function chipStatusLabel(status: ChipReference['status'], passLabel: string): string {
  if (status === 'pass') return passLabel
  if (status === 'fail') return '未通過'
  return '未知／待補資料'
}

function freshnessLabel(freshness: ChipReference['dataFreshness']): string {
  if (freshness === 'current') return '目前'
  if (freshness === 'stale') return '資料較舊'
  return '資料不可用'
}

export function ChipReferenceSummary({ chip }: { chip: ChipReference }) {
  return (
    <aside className="chip-reference" aria-label="籌碼參考（不影響策略篩選）">
      <strong>籌碼參考（不影響策略篩選）</strong>
      <span>大股東：{chipStatusLabel(chip.largeHolderTrend.status, '連續三月上升')}（{chip.largeHolderTrend.value}）</span>
      <span>董監：較12月前{chipStatusLabel(chip.directorSupervisor12m.status, '上升')}（{chip.directorSupervisor12m.value}）</span>
      <span>股東人數：{chipStatusLabel(chip.shareholderCountTrend.status, '連續三月下降')}（{chip.shareholderCountTrend.value}）</span>
      <small>資料期別：{chip.largeHolderTrend.period} · 資料新鮮度：{freshnessLabel(chip.dataFreshness)}{chip.availableAt ? ` · 可用於 ${chip.availableAt}` : ''}{chip.sourceRefs.length ? ` · 來源：${chip.sourceRefs.join('／')}` : ''}</small>
    </aside>
  )
}

function StockRow({ row, metricLabel, strategy }: { row: RankingRow; metricLabel: string; strategy: StrategyKey }) {
  const href = statementDogHealthCheckUrl(row.code)
  const chipReference = row.chipReference
  const growth = strategy === 'growth'
  const proxy = isProxyValuation(row)
  const observation = row.status !== 'pass'
  const lowPosition = strategy === 'lowPosition'
  const pegAvailable = Number.isFinite(row.currentPeg)
  const growthValuationAvailable = Number.isFinite(row.growthFairPrice) || Number.isFinite(row.growthBuyZonePrice)
  const valuationAvailable = growth
    ? growthValuationAvailable
    : Number.isFinite(row.fairPrice) || Number.isFinite(row.valuePrice075) || Number.isFinite(row.valuePrice066)
  const pegThreshold = row.pegBand === 'strict' ? '< 0.66' : '< 0.75'
  const pegBadge = !pegAvailable ? '估值資料不足' : proxy ? `PEG ${pegThreshold}（代理）` : row.pegBand === 'strict' ? 'PEG < 0.66 嚴格' : 'PEG < 0.75 可接受'
  const fairPriceLabel = proxy ? '祖魯基準價（代理情境，PEG=1）' : '祖魯合理價（PEG=1）'
  const band075Label = proxy ? '代理情境價（PEG=0.75）' : 'PEG 0.75 價值帶'
  const band066Label = proxy ? '代理情境價（PEG=0.66）' : 'PEG 0.66 價值帶'
  const extreme = proxy && row.extremeExtrapolation === true
  const ratio = extreme && Number(row.currentPrice) > 0 && Number.isFinite(row.fairPrice) ? Number(row.fairPrice) / Number(row.currentPrice) : null
  const inputsLabel = valuationInputsLabel(row)
  const growthInputsLabel = growthValuationInputsLabel(row)
  const windowLabel = regressionWindowLabel(row)
  const reason = knownReason(row.reason, row.valuationGrowthMethodLabel, row.status)
  const content = (
    <>
      <span className="stock-rank">{String(row.rank).padStart(2, '0')}</span>
      <span className="stock-main">
        <strong>{row.code} {row.name}</strong>
        <small>{row.sector || '產業未填'}</small>
        <span className="stock-evidence">
          <em className={observation ? 'evidence-badge observation' : 'evidence-badge'}>{lowPosition ? '價格／回歸觀察' : observation ? '觀察候選' : '策略條件'}</em>
          {!lowPosition && !growth && <em className={proxy ? 'evidence-badge proxy' : 'evidence-badge formal'}>{proxy ? '正式／代理證據：代理' : '正式 EPS PEG'}</em>}
          {!lowPosition && growth && <em className="evidence-badge formal">影片版總報酬估值</em>}
          {proxy && row.valuationGrowthMethodLabel?.includes('營收') && <em className="evidence-badge proxy">營收成長僅為代理，不等同 EPS 成長</em>}
          {strategy === 'trust' && row.entryStatus === 'new' && <em className="evidence-badge new-entry">新進榜</em>}
          {strategy === 'trust' && row.entryStatus === 'retained' && <em className="evidence-badge">續留</em>}
          {strategy === 'trust' && row.entryStatus === 'unknown' && <em className="evidence-badge observation">前日排行待補</em>}
          {lowPosition && <em className={healthBadgeClass(row)}>{healthLabel(row)}</em>}
        </span>
        <span className="stock-reason">{reason}</span>
      </span>
      <span className="stock-metric">
        <small>{metricLabel}</small>
        <strong>{lowPosition ? formatZ(row.zScore) : formatRankingValue(row)}</strong>
        {Number.isFinite(row.slope) && <small>slope {Number(row.slope).toFixed(3)}</small>}
      </span>
      {growth ? (
        <span className="stock-peg">
          <small>總報酬本益比</small>
          <strong>{formatMaybeTotalReturnPe(row.growthTotalReturnPe)}</strong>
          <em className={Number(row.growthTotalReturnPe) >= 1.2 ? 'peg-badge strict' : 'peg-badge'}>{Number(row.growthTotalReturnPe) >= 1.2 ? '≥ 1.20 低估研究' : row.growthValuationStatus === 'extreme' ? '極端外推' : '估值不可用'}</em>
          <small>祖魯 PEG 交叉參考</small>
          <strong>{formatMaybePeg(row.currentPeg)}</strong>
        </span>
      ) : (
        <span className="stock-peg">
          <small>目前 PEG</small>
          <strong>{formatMaybePeg(row.currentPeg)}</strong>
          <em className={row.pegBand === 'strict' ? 'peg-badge strict' : 'peg-badge'}>{pegBadge}</em>
        </span>
      )}
      <span className="stock-prices">
        <span><small>現在價格</small><strong>{formatMaybePrice(row.currentPrice)}</strong></span>
        {!lowPosition && growth && <>
          <span><small>影片版情境合理價</small><strong>{formatMaybePrice(row.growthFairPrice)}</strong></span>
          <span><small>低估參考價</small><strong>{formatMaybePrice(row.growthBuyZonePrice)}</strong></span>
          {!valuationAvailable && <small className="valuation-unavailable">{row.growthValuationReason || '合理價暫不可用'}</small>}
        </>}
        {!lowPosition && !growth && <>
          <span><small>{fairPriceLabel}</small><strong>{formatMaybePrice(row.fairPrice)}</strong></span>
          <span><small>{band075Label}</small><strong>{formatMaybePrice(row.valuePrice075)}</strong></span>
          <span><small>{band066Label}</small><strong>{formatMaybePrice(row.valuePrice066)}</strong></span>
          {!valuationAvailable && <small className="valuation-unavailable">估值資料不足</small>}
        </>}
        {extreme && <em className="extrapolation-warning">高成長不可直接外推{ratio ? `（代理情境價為現價 ${ratio.toFixed(1)} 倍）` : ''}</em>}
        {windowLabel && <small className="stock-window">{windowLabel}</small>}
        {growth && growthInputsLabel && <small className="stock-valuation-inputs">{growthInputsLabel}</small>}
        {!growth && inputsLabel && <small className="stock-valuation-inputs">{inputsLabel}</small>}
      </span>
      {chipReference && strategy !== 'growth' && <ChipReferenceSummary chip={chipReference} />}
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
      aria-label={`${row.code} ${row.name}${lowPosition ? '，價格／回歸觀察' : growth ? `，總報酬本益比 ${formatMaybeTotalReturnPe(row.growthTotalReturnPe)}` : pegAvailable ? `，目前 PEG ${Number(row.currentPeg).toFixed(2)}` : '，PEG 不可用'}，開啟財報狗股票健檢`}
      onClick={() => trackEvent('candidate_external_open', { strategy, code: row.code })}
    >
      {content}
    </a>
  )
}

function knownReason(reason: string, methodLabel: string | undefined, status: RankingRow['status']) {
  const visible = reason.split(/[；;]/).map((part) => part.trim()).filter((part) => part && !/^(unknown|未知|待核對)$/i.test(part))
  if (status !== 'pass') visible.push('資料仍在觀察層級')
  if (methodLabel) visible.push(`成長輸入：${methodLabel}`)
  return visible.join('；') || '符合已知篩選條件'
}

function formatPrice(value: number) {
  return value.toLocaleString('zh-TW', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
}

function formatRankingValue(row: RankingRow) {
  if (row.value == null || !Number.isFinite(row.value)) return '—'
  return `${row.value.toLocaleString('zh-TW', { maximumFractionDigits: 2 })}${row.valueLabel}`
}
