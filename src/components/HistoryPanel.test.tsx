import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { HistoryPanel } from './HistoryPanel'

describe('HistoryPanel', () => {
  it('renders accessible filters and neutral valuation labels', () => {
    const html = renderToStaticMarkup(<HistoryPanel index={null} />)
    expect(html).toContain('歷史篩選')
    expect(html).toContain('aria-label="選擇歷史起始交易日"')
    expect(html).toContain('aria-label="選擇歷史結束交易日"')
    expect(html).toContain('aria-expanded="false"')
    expect(html).toContain('歷史資料同步中／暫不可用')
  })
})
