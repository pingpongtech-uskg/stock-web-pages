import type { Coverage, Freshness, Release } from '../domain/types'
import { statusLabels } from './StatusPill'

function freshnessLabel(freshness: Freshness): string {
  return { current: '資料正常', stale: '資料逾期', degraded: '降級發布', unavailable: '資料不可用' }[freshness]
}

function freshnessClass(freshness: Freshness): string {
  return `freshness-${freshness}`
}

export function DataStatus({ release, compact = false }: { release: Release; compact?: boolean }) {
  const coverage: Coverage = release.coverage
  return (
    <div className={`data-status ${compact ? 'data-status-compact' : ''}`}>
      <div className={`freshness-dot ${freshnessClass(release.freshness)}`} aria-hidden="true" />
      <div>
        <strong>{freshnessLabel(release.freshness)}</strong>
        {!compact && <span>{release.statusMessage}{coverage.scopeLabel ? ` · ${coverage.scopeLabel}` : ''}</span>}
      </div>
      <div className="data-status-meta">
        <span>資料日 {release.marketDate ?? '—'}</span>
        <span>Run {release.runId}</span>
        {!compact && <span>完整度 {coverage.completenessPct == null ? '—' : `${coverage.completenessPct.toFixed(1)}%`}</span>}
      </div>
    </div>
  )
}

export function CoverageLine({ release }: { release: Release }) {
  const { coverage } = release
  return (
    <div className="coverage-line" aria-label="資料覆蓋狀態">
      <span>母體 {coverage.universeCount.toLocaleString('zh-TW')}</span>
      <span>已建庫 {coverage.databaseCount.toLocaleString('zh-TW')}（追蹤 {coverage.trackedCompleteCount ?? coverage.databaseCount}/{coverage.trackedCount ?? coverage.databaseCount}）</span>
      <span>待補 {coverage.pendingCount.toLocaleString('zh-TW')}</span>
      <span>財報完整 {coverage.financialCompleteCount.toLocaleString('zh-TW')}</span>
      <span>資料狀態：{coverage.queueStatus || statusLabels.unknown}</span>
    </div>
  )
}
