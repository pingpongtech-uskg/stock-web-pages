import { useMemo, useState } from 'react'
import type { PriceBasis, PricePoint } from '../domain/types'

const colors = {
  price: '#2457d6',
  mid: '#172033',
  plusOne: '#8ca8e8',
  plusTwo: '#c4cedf',
  minusOne: '#8ca8e8',
  minusTwo: '#c4cedf',
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
    const series = plotted.flatMap((point) => [observed(point), point.mid, point.bands['-2'], point.bands['-1'], point.bands['1'], point.bands['2']].filter((value): value is number => value != null))
    const min = Math.min(...series)
    const max = Math.max(...series)
    const pad = Math.max((max - min) * 0.08, 1)
    const floor = min - pad
    const ceiling = max + pad
    // Use almost the full plot width.  The previous 8–92 range made the
    // chart look like a narrow island with large empty gutters on both sides.
    const x = (index: number) => 2 + (index / Math.max(1, plotted.length - 1)) * 96
    const y = (value: number) => 92 - ((value - floor) / (ceiling - floor)) * 84
    const make = (field: (point: PricePoint) => number | null) => plotted.flatMap((point, index) => {
      const value = field(point)
      return value == null ? [] : [[x(index), y(value)] as [number, number]]
    })
    return { x, y, price: make(observed), mid: make((point) => point.mid), plusOne: make((point) => point.bands['1']), plusTwo: make((point) => point.bands['2']), minusOne: make((point) => point.bands['-1']), minusTwo: make((point) => point.bands['-2']), floor, ceiling }
  }, [plotted, usesAdjusted])

  if (!chart) return <div className="chart-empty">尚無足夠價格資料繪圖。</div>
  const current = hoverIndex == null ? plotted[plotted.length - 1] : plotted[Math.min(hoverIndex, plotted.length - 1)]
  const currentIndex = hoverIndex == null ? plotted.length - 1 : Math.min(hoverIndex, plotted.length - 1)
  const currentPrice = observed(current)
  const sigma = current.mid == null ? null : current.bands['1'] == null ? null : current.bands['1'] - current.mid
  const currentZ = currentPrice == null || current.mid == null || sigma == null || sigma === 0 ? null : (currentPrice - current.mid) / sigma

  return (
    <div className="line-chart-wrap">
      <div className="chart-readout">
        <span>{current.date}</span>
        <strong>{observed(current) == null ? '—' : observed(current)!.toLocaleString('zh-TW', { maximumFractionDigits: 2 })}</strong>
        <span>{usesAdjusted ? 'Adj Close' : '未調整代理'}</span>
        <span>中線 {current.mid == null ? '—' : current.mid.toLocaleString('zh-TW', { maximumFractionDigits: 2 })}</span>
        <span>Z {currentZ == null ? '—' : currentZ.toFixed(2)}</span>
      </div>
      <div className="chart-legend" aria-label="五線譜圖例"><span><i className="legend-swatch price" />價格</span><span><i className="legend-swatch mid" />中線</span><span><i className="legend-swatch band" />+1σ／-1σ</span><span><i className="legend-swatch band faint" />+2σ／-2σ</span></div>
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
        {[20, 44, 68, 92].map((y) => <line key={y} x1="2" x2="98" y1={y} y2={y} stroke={colors.grid} strokeWidth="0.25" />)}
        <path d={pathFor(chart.plusTwo)} fill="none" stroke={colors.plusTwo} strokeWidth="0.35" strokeDasharray="1.4 1.8" />
        <path d={pathFor(chart.plusOne)} fill="none" stroke={colors.plusOne} strokeWidth="0.35" strokeDasharray="1.2 1.5" />
        <path d={pathFor(chart.mid)} fill="none" stroke={colors.mid} strokeWidth="0.5" />
        <path d={pathFor(chart.minusOne)} fill="none" stroke={colors.minusOne} strokeWidth="0.35" strokeDasharray="1.2 1.5" />
        <path d={pathFor(chart.minusTwo)} fill="none" stroke={colors.minusTwo} strokeWidth="0.35" strokeDasharray="1.4 1.8" />
        <path d={pathFor(chart.price)} fill="none" stroke={colors.price} strokeWidth="0.65" strokeLinecap="round" strokeLinejoin="round" />
        <line x1={chart.x(currentIndex)} x2={chart.x(currentIndex)} y1="8" y2="92" stroke={colors.price} strokeOpacity="0.35" strokeWidth="0.3" />
        <circle cx={chart.x(currentIndex)} cy={chart.y(observed(current) ?? chart.floor)} r="1.4" fill={colors.price} />
      </svg>
      <div className="chart-axis"><span>{plotted[0].date}</span><span>最新 {plotted[plotted.length - 1].date}</span></div>
      <p className="chart-caption">本期四年五線譜（中線、±1σ、±2σ；{usesAdjusted ? '調整後收盤價' : '未調整收盤代理'}）；回歸線為描述工具，中線不是合理價，σ 帶不是未來機率。游標可查看同日價格與 Z。</p>
    </div>
  )
}
