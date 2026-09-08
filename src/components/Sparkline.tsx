export function Sparkline({ values, tone = 'blue' }: { values: Array<number | null>; tone?: 'blue' | 'red' | 'green' }) {
  const usable = values.filter((value): value is number => value != null && Number.isFinite(value))
  if (usable.length < 2) return <span className="sparkline-empty">—</span>
  const min = Math.min(...usable)
  const max = Math.max(...usable)
  const range = max - min || 1
  const points = values
    .map((value, index) => value == null ? null : `${(index / (values.length - 1)) * 100},${92 - ((value - min) / range) * 84}`)
    .filter(Boolean)
    .join(' ')
  return (
    <svg className={`sparkline sparkline-${tone}`} viewBox="0 0 100 100" role="img" aria-label="趨勢折線">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
