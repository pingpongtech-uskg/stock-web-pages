import { useEffect, useState } from 'react'
import type { Coverage, Freshness, Release } from '../domain/types'
import { qualityStatusCounts } from '../domain/coverage'
import { trackEventOnce } from '../domain/events'
import { statusLabels } from './StatusPill'

export function getEffectiveFreshness(release: Pick<Release, 'freshness' | 'nextExpectedUpdateAt'>, now = Date.now()): Freshness {
  if (release.freshness === 'unavailable' || release.freshness === 'stale') return release.freshness
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
  return freshness === 'stale' ? '逾期' : freshness === 'unavailable' ? '不可用' : '正常'
}

function freshnessClass(freshness: Freshness): string {
  return `freshness-${freshness === 'stale' || freshness === 'unavailable' ? freshness : 'current'}`
}

function formatGeneratedAt(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '—'
    : date.toLocaleString('zh-TW', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Taipei' })
}

function formatCompletenessPct(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '—'
}

function formatCount(value: number | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('zh-TW') : '—'
}

export function DataStatus({ release, compact = false, now, source = 'network' }: { release: Release; compact?: boolean; now?: number; source?: 'network' | 'cache' }) {
  const [clockNow, setClockNow] = useState(() => Date.now())
  const renderNow = now ?? clockNow
  useEffect(() => {
    if (now !== undefined) return
    const updateClock = () => {
      const current = Date.now()
      setClockNow(current)
      const expected = release.nextExpectedUpdateAt ? Date.parse(release.nextExpectedUpdateAt) : NaN
      const nextMinute = 60_000 - (current % 60_000)
      const untilDeadline = Number.isFinite(expected) && expected >= current ? expected - current + 1 : Infinity
      timeout = window.setTimeout(updateClock, Math.max(1, Math.min(nextMinute, untilDeadline)))
    }
    const current = Date.now()
    const expected = release.nextExpectedUpdateAt ? Date.parse(release.nextExpectedUpdateAt) : NaN
    const nextMinute = 60_000 - (current % 60_000)
    const untilDeadline = Number.isFinite(expected) && expected >= current ? expected - current + 1 : Infinity
    let timeout = window.setTimeout(updateClock, Math.max(1, Math.min(nextMinute, untilDeadline)))
    return () => window.clearTimeout(timeout)
  }, [now, release.nextExpectedUpdateAt])
  const coverage: Coverage = release.coverage
  const effectiveFreshness = getEffectiveFreshness(release, renderNow)
  const overdue = overdueLabel(release, renderNow)
  const quality = release.freshness === 'degraded' ? '降級發布' : release.freshness === 'unavailable' ? '不可用' : '正常'
  const trustSignalSummary = !compact && typeof release.summary.trustSignalCount === 'number'
    ? ` · 投信 Top10 ${formatCount(release.summary.trustSignalCount)} 檔／新進榜 ${formatCount(release.summary.trustNewEntryCount)} 檔／PEG 可顯示 ${formatCount(release.summary.trustValuationVisibleCount ?? release.summary.candidateRouteCounts.trust)} 檔`
    : ''
  const showOverdue = Boolean(overdue)
  useEffect(() => {
    if (effectiveFreshness === 'stale' || effectiveFreshness === 'degraded') {
      trackEventOnce(`banner:${effectiveFreshness}`, 'stale_or_degraded_banner_view', { freshness: effectiveFreshness })
    }
  }, [effectiveFreshness])
  return (
    <div className={`data-status ${compact ? 'data-status-compact' : ''}`}>
      <div className={`freshness-dot ${freshnessClass(effectiveFreshness)}`} aria-hidden="true" />
      <div>
        <strong>新鮮度：{freshnessLabel(effectiveFreshness)}</strong>
        {!compact && (
          <span>
            資料品質：{quality} · {release.statusMessage}
            {showOverdue && <em className="overdue-note">（{overdue}）</em>}
            {source === 'cache' && <em className="cache-note"> · 瀏覽器快取（網路讀取失敗）</em>}
            {coverage.scopeLabel ? ` · ${coverage.scopeLabel}` : ''}{trustSignalSummary}
          </span>
        )}
      </div>
      <div className="data-status-meta">
        <span>資料日 {release.marketDate ?? '—'}</span>
        <span>更新 UTC+8 {formatGeneratedAt(release.generatedAt)}</span>
        <span>Run {release.runId}</span>
        {!compact && <span>追蹤行情完整度 {formatCompletenessPct(coverage.completenessPct)}</span>}
      </div>
    </div>
  )
}

export function CoverageLine({ release }: { release: Release }) {
  const { coverage } = release
  const quality = qualityStatusCounts(release.stocks ?? [])
  const qualitySummary = release.stocks?.length
    ? `通過 ${quality.pass} · 未通過 ${quality.fail} · 未評估 ${quality.unknown} · 不適用 ${quality.notApplicable} · 未提供 ${quality.unreported}`
    : `逐檔狀態未提供；發布摘要明確通過 ${coverage.financialCompleteCount} 檔`
  return (
    <div className="coverage-line" aria-label="資料覆蓋狀態">
      <span>母體 {formatCount(coverage.universeCount)}</span>
      <span>已建庫 {formatCount(coverage.databaseCount)}（追蹤 {formatCount(coverage.trackedCompleteCount ?? coverage.databaseCount)}/{formatCount(coverage.trackedCount ?? coverage.databaseCount)}）</span>
      <span>待補 {formatCount(coverage.pendingCount)}</span>
      <span>財務品質狀態：{qualitySummary}</span>
      <span>資料狀態：{coverage.queueStatus || statusLabels.unknown}</span>
    </div>
  )
}
