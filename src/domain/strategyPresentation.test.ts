import { describe, expect, it } from 'vitest'
import { strategyPresentations, GROWTH_TOTAL_RETURN_FORMULA, ZULU_VALUATION_FORMULA } from './strategyPresentation'

describe('strategy presentation', () => {
  it('keeps exactly three tabs in stable order', () => {
    expect(strategyPresentations.map((item) => item.key)).toEqual(['trust', 'growth', 'lowPosition'])
  })

  it('keeps Zulu as the shared cross-check and the 總報酬本益比（本站整理） as growth primary', () => {
    expect(strategyPresentations.filter((item) => item.key !== 'growth').every((item) => item.valuationFormula === ZULU_VALUATION_FORMULA)).toBe(true)
    expect(strategyPresentations.find((item) => item.key === 'growth')?.valuationFormula).toBe(GROWTH_TOTAL_RETURN_FORMULA)
    expect(ZULU_VALUATION_FORMULA).toContain('PEG < 0.66')
    expect(ZULU_VALUATION_FORMULA).toContain('祖魯基準價（PEG=1）')
    expect(ZULU_VALUATION_FORMULA).toContain('營收成長僅為觀察代理')
    expect(ZULU_VALUATION_FORMULA).toContain('估算／代理 PEG')
    expect(strategyPresentations.find((item) => item.key === 'growth')?.condition).toContain('總報酬本益比')
    expect(strategyPresentations.find((item) => item.key === 'lowPosition')?.condition).toContain('4/5')
    expect(strategyPresentations.find((item) => item.key === 'lowPosition')?.valuationNote).toContain('PEG 不可用')
  })
})
