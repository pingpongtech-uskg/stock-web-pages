import { useMemo, useState } from 'react'
import type { PriceBasis, PricePoint } from '../domain/types'

const colors = {
  price: '#2457d6',
  mid: '#172033',
  oneSigma: '#6b7da8',
  twoSigma: '#c4cedf',
  grid: '#d8dfea',
}

const plot = { left: 8, right: 92, top: 8, bottom: 92 }

function pathFor(points: Array<[number, number]>): string {
  return points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`).join(' ')
}

function formatValue(value: number | null): string {
  return value == null || !Number.isFinite(value)
    ? '—'
    : value.toLocaleString('zh-TW', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
}

function pointSigma(point: PricePoint): number | null {
  if (point.mid == null) return null
  const candidates = [
    point.bands['1'] == null ? null : point.bands['1'] - point.mid,
    point.bands['-1'] == null ? null : point.mid - point.bands['-1'],
    point.bands['2'] == null ? null : (point.bands['2'] - point.mid) / 2,
    point.bands['-2'] == null ? null : (point.mid - point.bands['-2']) / 2,
  ]
  const sigma = candidates.find((value): value is number => value != null && Number.isFinite(value) && value > 0)
  return sigma ?? null
}

function pointZ(point: PricePoint, observed: number | null): number | null {
  const sigma = pointSigma(point)
  if (observed == null || point.mid == null || sigma == null) return null
  const z = (observed - point.mid) / sigma
  return Number.isFinite(z) ? z : null
}

export function LineChart({ points, priceBasis }: { points: PricePoint[]; priceBasis?: PriceBasis }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const usesAdjusted = priceBasis === 'adjusted' || (priceBasis == null && points.some((point) => point.adjustedClose != null))
  const observed = (point: PricePoint) => usesAdjusted ? (point.adjustedClose ?? null) : point.close
  const plotted = points.filter((point) => observed(point) != null)
  const chart = useMemo(() => {
    if (plotted.length < 2) return null
    const series = plotted.flatMap((point) => [
      observed(point),
      point.mid,
      point.bands['-2'],
      point.bands['-1'],
      point.bands['1'],
      point.bands['2'],
    ].filter((value): value is number => value != null && Number.isFinite(value)))
    if (!series.length) return null
    const min = Math.min(...series)
    const max = Math.max(...series)
    const pad = Math.max((max - min) * 0.08, 1)
    const floor = min - pad
    const ceiling = max + pad
    const x = (index: number) => plot.left + (index / Math.max(1, plotted.length - 1)) * (plot.right - plot.left)
    const y = (value: number) => plot.bottom - ((value - floor) / (ceiling - floor)) * (plot.bottom - plot.top)
    const make = (field: (point: PricePoint) => number | null) => plotted.flatMap((point, index) => {
      const value = field(point)
      return value == null || !Number.isFinite(value) ? [] : [[x(index), y(value)] as [number, number]]
    })
    return {
      x,
      y,
      price: make(observed),
      mid: make((point) => point.mid),
      minusTwo: make((point) => point.bands['-2']),
      minusOne: make((point) => point.bands['-1']),
      plusOne: make((point) => point.bands['1']),
      plusTwo: make((point) => point.bands['2']),
      floor,
      ceiling,
    }
  }, [plotted, usesAdjusted])

  if (!chart) return <div className="chart-empty">尚無足夠價格資料繪圖。</div>
  const currentIndex = hoverIndex == null ? plotted.length - 1 : Math.min(hoverIndex, plotted.length - 1)
  const current = plotted[currentIndex]
  const currentPrice = observed(current)
  const currentZ = pointZ(current, currentPrice)

  return (
    <div className="line-chart-wrap">
      <div className="chart-readout" aria-live="polite">
        <span>{current.date}</span>
        <strong>{formatValue(currentPrice)}</strong>
        <span>{usesAdjusted ? 'Adj Close' : '未調整代理'}</span>
        <span>中線 {formatValue(current.mid)}</span>
        <span>Z {currentZ == null ? '—' : currentZ.toFixed(2)}</span>
      </div>
      <svg
        className="line-chart"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        role="img"
        aria-label={`${usesAdjusted ? '調整後價格' : '未調整價格代理'}、回歸中線與正負一至二倍標準差帶線圖。帶線不是機率或合理價。`}
        onPointerMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect()
          const plotLeft = rect.left + rect.width * (plot.left / 100)
          const plotWidth = rect.width * ((plot.right - plot.left) / 100)
          const ratio = Math.max(0, Math.min(1, (event.clientX - plotLeft) / Math.max(1, plotWidth)))
          setHoverIndex(Math.round(ratio * (plotted.length - 1)))
        }}
        onPointerLeave={() => setHoverIndex(null)}
      >
        {[20, 44, 68, 92].map((y) => <line key={y} x1={plot.left} x2={plot.right} y1={y} y2={y} stroke={colors.grid} strokeWidth="0.35" />)}
        <path d={pathFor(chart.minusTwo)} fill="none" stroke={colors.twoSigma} strokeWidth="0.8" strokeDasharray="1.4 1.8" />
        <path d={pathFor(chart.minusOne)} fill="none" stroke={colors.oneSigma} strokeWidth="0.8" strokeDasharray="1.2 1.2" />
        <path d={pathFor(chart.mid)} fill="none" stroke={colors.mid} strokeWidth="1.1" />
        <path d={pathFor(chart.plusOne)} fill="none" stroke={colors.oneSigma} strokeWidth="0.8" strokeDasharray="1.2 1.2" />
        <path d={pathFor(chart.plusTwo)} fill="none" stroke={colors.twoSigma} strokeWidth="0.8" strokeDasharray="1.4 1.8" />
        <path d={pathFor(chart.price)} fill="none" stroke={colors.price} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
        <line x1={chart.x(currentIndex)} x2={chart.x(currentIndex)} y1={plot.top} y2={plot.bottom} stroke={colors.price} strokeOpacity="0.35" strokeWidth="0.5" />
        <circle cx={chart.x(currentIndex)} cy={chart.y(currentPrice ?? chart.floor)} r="2.2" fill={colors.price} />
      </svg>
      <div className="chart-legend" aria-label="圖例">
        <span><i className="legend-swatch price" />價格</span>
        <span><i className="legend-swatch mid" />中線</span>
        <span><i className="legend-swatch one" />±1σ</span>
        <span><i className="legend-swatch two" />±2σ</span>
      </div>
      <div className="chart-axis"><span>{plotted[0].date}</span><span>最新 {plotted[plotted.length - 1].date}</span></div>
      <p className="chart-caption">本期 3.5 年回歸（{usesAdjusted ? '調整後收盤價' : '未調整收盤代理'}）；中線與 ±1σ／±2σ 是描述工具，不是合理價或未來機率。移動游標可查看同日價格與 Z=(價格−中線)／σ。</p>
    </div>
  )
}
