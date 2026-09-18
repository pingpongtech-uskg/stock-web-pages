import type { Release } from './types'

export type StrategyKey = Extract<keyof Release['rankings'], 'trust' | 'growth' | 'lowPosition'>
export type StrategyAccent = 'hot' | 'growth' | 'low'

export interface StrategyPresentation {
  key: StrategyKey
  title: string
  subtitle: string
  horizon: string
  metricLabel: string
  description: string
  condition: string
  selection: string
  valuationNote: string
  valuationFormula: string
  emptyBody: string
  accent: StrategyAccent
}

export const ZULU_VALUATION_FORMULA = '保守成長率 = 三月營收年增 × 0.8；合理本益比 =（保守成長率 + 現金股利殖利率）× 100；Forward EPS = 現在價格 ÷ 目前 PE ×（1 + 保守成長率）；祖魯合理價 = Forward EPS × 合理本益比。'

export const strategyPresentations: readonly StrategyPresentation[] = [
  {
    key: 'trust',
    title: '投信關注',
    subtitle: 'A 母體／十日淨買超前 100',
    horizon: '數日～數週',
    metricLabel: '十日成交占比',
    description: '找投信資金最近集中、且有完整價格與估值輸入的股票。',
    condition: '母體：投信十日淨買超前 100 檔；先保留已知流動性與價格資料。',
    selection: '篩選：依十日淨買超股數排序，成交占比作為同一檔股票的資金參考。',
    valuationNote: '價格：現在價格＋祖魯合理價；三個 tab 使用完全相同的估值標準。',
    valuationFormula: ZULU_VALUATION_FORMULA,
    emptyBody: '目前沒有同時具備已知價格、PE、股利與成長輸入的投信候選。',
    accent: 'hot',
  },
  {
    key: 'growth',
    title: '成長改善',
    subtitle: '三月合計營收年增代理',
    horizon: '6～36 個月',
    metricLabel: '三月營收年增',
    description: '用已公布營收成長找改善入口，再只保留能計算估值情境的股票。',
    condition: '條件：三月合計營收年增至少 15%；正式營業利益成長不是用營收代理替代。',
    selection: '篩選：在 A 母體內按三月合計營收年增排序，只列已知價格與估值輸入。',
    valuationNote: '價格：現在價格＋祖魯合理價；三個 tab 使用完全相同的估值標準。',
    valuationFormula: ZULU_VALUATION_FORMULA,
    emptyBody: '目前沒有同時具備營收成長、價格、PE、股利與成長輸入的候選。',
    accent: 'growth',
  },
  {
    key: 'lowPosition',
    title: '低位觀察',
    subtitle: '調整價四年回歸／正向 slope',
    horizon: '6～24 個月',
    metricLabel: '四年 Z 值',
    description: '找長期趨勢仍向上、目前價格落在相對低位的研究標的。',
    condition: '代理入口：調整價四年回歸可用、Z ≤ 0、slope > 0；嚴格低基期路徑改用 Z ≤ -1。',
    selection: '篩選：先在 A 母體計算回歸，再按 Z 由低到高；品質／成長是另外的嚴格路徑。',
    valuationNote: '價格：現在價格＋祖魯合理價；三個 tab 使用完全相同的估值標準。',
    valuationFormula: ZULU_VALUATION_FORMULA,
    emptyBody: '目前沒有同時具備低位條件、已知價格與合理價輸入的候選。',
    accent: 'low',
  },
]
