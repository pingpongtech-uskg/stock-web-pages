import type { MarketVolumeMultipleIndicator } from '../domain/types'
interface Props { indicator?: MarketVolumeMultipleIndicator }
function formatVolume(value: number | null): string { return value === null ? '—' : new Intl.NumberFormat('zh-TW', { maximumFractionDigits: 0 }).format(value) }
export function MarketVolumeIndicator({ indicator }: Props) {
 const available=indicator?.status==='available' && indicator.multiple!==null; const signal=available?indicator.signal:'unknown'; const label=signal==='green'?'綠燈':signal==='yellow'?'黃燈':'資料不足'; const multiple=available?`${indicator.multiple!.toFixed(2)} 倍`:'—'
 return <section className={`market-volume-indicator signal-${signal}`} aria-label="大盤成交量觀察"><div className="market-volume-copy"><p className="site-kicker">MARKET VOLUME / TWSE</p><h2>00631L 成交量動能</h2><p>今日成交量 ÷ 前五個完成交易日平均成交量（不含今日）</p></div><div className="market-volume-reading"><strong>{multiple}</strong><span className="market-volume-signal">{label}</span><small>分水嶺：2.00 倍以上綠燈，以下黃燈</small></div><dl className="market-volume-detail"><div><dt>交易日</dt><dd>{indicator?.marketDate ?? '—'}</dd></div><div><dt>今日成交量</dt><dd>{formatVolume(indicator?.currentVolume ?? null)} 股</dd></div><div><dt>前五日均量</dt><dd>{formatVolume(indicator?.previous5AverageVolume ?? null)} 股</dd></div></dl></section>
}
