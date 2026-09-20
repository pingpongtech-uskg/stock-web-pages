import { useEffect } from 'react'
import type { Coverage, Freshness, Release } from '../domain/types'
import { trackEventOnce } from '../domain/events'
import { statusLabels } from './StatusPill'

export function getEffectiveFreshness(release: Pick<Release, 'freshness' | 'nextExpectedUpdateAt'>, now = Date.now()): Freshness {
  if (release.freshness === 'unavailable' || release.freshness === 'degraded' || release.freshness === 'stale') return release.freshness
  const expected = release.nextExpectedUpdateAt ? Date.parse(release.nextExpectedUpdateAt) : NaN
  return Number.isFinite(expected) && now > expected ? 'stale' : release.freshness
}

export function overdueLabel(release: Pick<Release, 'nextExpectedUpdateAt'>, now = Date.now()): string | null {
  const expected = release.nextExpectedUpdateAt ? Date.parse(release.nextExpectedUpdateAt) : NaN
  if (!Number.isFinite(expected) || now <= expected) return null
  const hours = Math.max(1, Math.floor((now - expected) / 3_600_000))
  return `逾期約 ${hours} 小時`
}

function freshnessLabel(freshness: Freshness): string {
  return { current: '資料正常', stale: '資料逾期', degraded: '降級發布', unavailable: '資料不可用' }[freshness]
}

function freshnessClass(freshness: Freshness): string {
  return `freshness-${freshness}`
}

function formatCompletenessPct(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '—'
}

function formatCount(value: number | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-TW') : '—'
}

export function DataStatus({ release, compact = false, now = Date.now() }: { release: Release; compact?: boolean; now?: number }) {
  const coverage: Coverage = release.coverage
  const effectiveFreshness = getEffectiveFreshness(release, now)
  const overdue = overdueLabel(release, now)
  const staleFromCurrent = effectiveFreshness === 'stale' && release.freshness === 'current'
  const statusMessage = staleFromCurrent
    ? `發布快照已逾期${overdue ? `（${overdue}）` : ''}`
    : release.statusMessage
  const trustSignalSummary = !compact && typeof release.summary.trustSignalCount === 'number'
    ? ` · 投信 Top10 ${formatCount(release.summary.trustSignalCount)} 檔／新進榜 ${formatCount(release.summary.trustNewEntryCount)} 檔／PEG 可顯示 ${formatCount(release.summary.trustValuationVisibleCount ?? release.summary.candidateRouteCounts.trust)} 檔`
    : ''
  // Data quality (degraded/stale) and time freshness are separate dimensions:
  // a degraded release that is also past its expected update still shows how
  // long ago the market data should have been refreshed.
  const showOverdue = Boolean(overdue) && !staleFromCurrent && effectiveFreshness !== 'current'
  useEffect(() => {
    if (effectiveFreshness === 'stale' || effectiveFreshness === 'degraded') {
      trackEventOnce(`banner:${effectiveFreshness}`, 'stale_or_degraded_banner_view', { freshness: effectiveFreshness })
    }
  }, [effectiveFreshness])
  return (
    <div className={`data-status ${compact ? 'data-status-compact' : ''}`}>
      <div className={`freshness-dot ${freshnessClass(effectiveFreshness)}`} aria-hidden="true" />
      <div>
        <strong>{freshnessLabel(effectiveFreshness)}</strong>
        {!compact && (
          <span>
            {statusMessage}
            {showOverdue && <em className="overdue-note">（{overdue}）</em>}
            {coverage.scopeLabel ? ` · ${coverage.scopeLabel}` : ''}{trustSignalSummary}
          </span>
        )}
      </div>
      <div className="data-status-meta">
        <span>資料日 {release.marketDate ?? '—'}</span>
        <span>Run {release.runId}</span>
        {!compact && <span>完整度 {formatCompletenessPct(coverage.completenessPct)}</span>}
      </div>
    </div>
  )
}

export function CoverageLine({ release }: { release: Release }) {
  const { coverage } = release
  return (
    <div className="coverage-line" aria-label="資料覆蓋狀態">
      <span>母體 {formatCount(coverage.universeCount)}</span>
      <span>已建庫 {formatCount(coverage.databaseCount)}（追蹤 {formatCount(coverage.trackedCompleteCount ?? coverage.databaseCount)}/{formatCount(coverage.trackedCount ?? coverage.databaseCount)}）</span>
      <span>待補 {formatCount(coverage.pendingCount)}</span>
      <span>財報完整 {formatCount(coverage.financialCompleteCount)}</span>
      <span>資料狀態：{coverage.queueStatus || statusLabels.unknown}</span>
    </div>
  )
}
