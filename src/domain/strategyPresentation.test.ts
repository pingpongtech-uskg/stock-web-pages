import { describe, expect, it } from 'vitest'
import { strategyPresentations, ZULU_VALUATION_FORMULA } from './strategyPresentation'

describe('strategy presentation', () => {
  it('keeps exactly three tabs in stable order', () => {
    expect(strategyPresentations.map((item) => item.key)).toEqual(['trust', 'growth', 'lowPosition'])
  })

  it('uses one identical Zulu valuation formula in every tab description', () => {
    expect(strategyPresentations.every((item) => item.valuationFormula === ZULU_VALUATION_FORMULA)).toBe(true)
    expect(ZULU_VALUATION_FORMULA).toContain('祖魯合理價 = Forward EPS × 合理本益比')
  })
})
