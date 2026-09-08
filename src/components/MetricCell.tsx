import type { MetricStatus } from '../domain/types'
import { StatusPill } from './StatusPill'

export function MetricCell({
  label,
  value,
  unit = '',
  status = 'unknown',
  detail,
}: {
  label: string
  value: string | number | null | undefined
  unit?: string
  status?: MetricStatus
  detail?: string
}) {
  const rendered = value == null || value === '' ? '—' : `${value}${unit}`
  return (
    <div className="metric-cell" title={detail}>
      <span className="metric-label">{label}</span>
      <strong className={value == null ? 'metric-missing' : ''}>{rendered}</strong>
      <StatusPill status={status} />
    </div>
  )
}
