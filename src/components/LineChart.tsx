import { useMemo, useState } from 'react'
import type { PriceBasis, PricePoint } from '../domain/types'

const colors = {
  price: '#2457d6',
  mid: '#172033',
  upper: '#c4cedf',
  lower: '#c4cedf',
  grid: '#d8dfea',
}

function pathFor(points: Array<[number, number]>): string {
  return points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`).join(' ')
}

export function LineChart({ points, priceBasis }: { points: PricePoint[]; priceBasis?: PriceBasis }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const usesAdjusted = priceBasis === 'adjusted' || (priceBasis == null && points.some((point) => point.adjustedClose != null))
  const observed = (point: PricePoint) => usesAdjusted ? (point.adjustedClose ?? null) : point.close
  const plotted = points.filter((point) => observed(point) != null)
  const chart = useMemo(() => {
    if (plotted.length < 2) return null
    const series = plotted.flatMap((point) => [observed(point), point.mid, point.bands['-2'], point.bands['2']].filter((value): value is number => value != null))
    const min = Math.min(...series)
    const max = Math.max(...series)
    const pad = Math.max((max - min) * 0.08, 1)
    const floor = min - pad
    const ceiling = max + pad
    const x = (index: number) => 8 + (index / Math.max(1, plotted.length - 1)) * 84
    const y = (value: number) => 92 - ((value - floor) / (ceiling - floor)) * 84
    const make = (field: (point: PricePoint) => number | null) => plotted.flatMap((point, index) => {
      const value = field(point)
      return value == null ? [] : [[x(index), y(value)] as [number, number]]
    })
    return { x, y, price: make(observed), mid: make((point) => point.mid), upper: make((point) => point.bands['2']), lower: make((point) => point.bands['-2']), floor, ceiling }
  }, [plotted, usesAdjusted])

  if (!chart) return <div className="chart-empty">尚無足夠價格資料繪圖。</div>
  const current = hoverIndex == null ? plotted[plotted.length - 1] : plotted[Math.min(hoverIndex, plotted.length - 1)]
  const currentIndex = hoverIndex == null ? plotted.length - 1 : Math.min(hoverIndex, plotted.length - 1)

  return (
    <div className="line-chart-wrap">
      <div className="chart-readout">
        <span>{current.date}</span>
        <strong>{observed(current) == null ? '—' : observed(current)!.toLocaleString('zh-TW', { maximumFractionDigits: 2 })}</strong>
        <span>{usesAdjusted ? 'Adj Close' : '未調整代理'}</span>
        <span>中線 {current.mid == null ? '—' : current.mid.toLocaleString('zh-TW', { maximumFractionDigits: 2 })}</span>
        <span>Z {observed(current) != null && current.mid != null && current.bands['2'] != null && current.bands['-2'] != null ? '見個股摘要' : '—'}</span>
      </div>
      <svg
        className="line-chart"
        viewBox="0 0 100 100"
        role="img"
        aria-label={`${usesAdjusted ? '調整後價格' : '未調整價格代理'}與四年回歸中線圖。上下帶不是機率或合理價。`}
        onPointerMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect()
          const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
          setHoverIndex(Math.round(ratio * (plotted.length - 1)))
        }}
        onPointerLeave={() => setHoverIndex(null)}
      >
        {[20, 44, 68, 92].map((y) => <line key={y} x1="8" x2="92" y1={y} y2={y} stroke={colors.grid} strokeWidth="0.35" />)}
        <path d={pathFor(chart.upper)} fill="none" stroke={colors.upper} strokeWidth="0.8" strokeDasharray="1.4 1.8" />
        <path d={pathFor(chart.lower)} fill="none" stroke={colors.lower} strokeWidth="0.8" strokeDasharray="1.4 1.8" />
        <path d={pathFor(chart.mid)} fill="none" stroke={colors.mid} strokeWidth="1.1" />
        <path d={pathFor(chart.price)} fill="none" stroke={colors.price} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
        <line x1={chart.x(currentIndex)} x2={chart.x(currentIndex)} y1="8" y2="92" stroke={colors.price} strokeOpacity="0.35" strokeWidth="0.5" />
        <circle cx={chart.x(currentIndex)} cy={chart.y(observed(current) ?? chart.floor)} r="2.2" fill={colors.price} />
      </svg>
      <div className="chart-axis"><span>{plotted[0].date}</span><span>最新 {plotted[plotted.length - 1].date}</span></div>
      <p className="chart-caption">本期四年回歸（{usesAdjusted ? '調整後收盤價' : '未調整收盤代理'}）；回歸線為描述工具，中線不是合理價，±2σ 不是未來機率。游標可查看同日價格。</p>
    </div>
  )
}
