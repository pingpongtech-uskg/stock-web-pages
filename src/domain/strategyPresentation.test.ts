import { describe, expect, it } from 'vitest'
import { strategyPresentations, ZULU_VALUATION_FORMULA } from './strategyPresentation'

describe('strategy presentation', () => {
  it('keeps exactly three tabs in stable order', () => {
    expect(strategyPresentations.map((item) => item.key)).toEqual(['trust', 'growth', 'lowPosition'])
  })

  it('uses one identical Zulu valuation formula in every tab description', () => {
    expect(strategyPresentations.every((item) => item.valuationFormula === ZULU_VALUATION_FORMULA)).toBe(true)
    expect(ZULU_VALUATION_FORMULA).toContain('PEG < 0.66')
    expect(ZULU_VALUATION_FORMULA).toContain('祖魯基準價（PEG=1）')
    expect(ZULU_VALUATION_FORMULA).toContain('正式 EPS 與代理 PEG 都顯示')
  })
})
