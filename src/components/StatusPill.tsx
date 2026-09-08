import type { MetricStatus } from '../domain/types'

const labels: Record<MetricStatus, string> = {
  pass: '通過',
  fail: '未通過',
  unknown: '未知',
  not_applicable: '不適用',
}

export function StatusPill({ status, label }: { status: MetricStatus; label?: string }) {
  return <span className={`status-pill status-${status}`}>{label ?? labels[status]}</span>
}

export { labels as statusLabels }
