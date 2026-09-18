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

export const ZULU_VALUATION_FORMULA = 'PEG = 目前 PE ÷ 預估 EPS 成長率（%）；當前 EPS 一律由「現價 ÷ 當期 PE」反推；Forward EPS = 當前 EPS ×（1 + 成長率）；祖魯基準價（PEG=1）= Forward EPS × 成長率（%）；PEG < 0.75 可接受、PEG < 0.66 嚴格。成長率來自營收代理時，價格一律標示「代理情境價」；成長率 >100% 或情境價／現價比 >3 時，標示「高成長不可直接外推」。正式 EPS 與代理 PEG 都顯示，但證據等級不同。'

export const strategyPresentations: readonly StrategyPresentation[] = [
  {
    key: 'trust',
    title: '投信關注',
    subtitle: '共同 A 母體／十日淨買超前 100',
    horizon: '數日～數週',
    metricLabel: '十日淨買超',
    description: '從共同 A 母體找投信資金最近集中的股票，再用祖魯 PEG 排除估值過高者。',
    condition: '母體：投信十日淨買超前 100；PEG < 0.75 可列入，PEG < 0.66 標為嚴格價值帶。',
    selection: '篩選：依投信十日淨買超排名；EPS 成長優先用 LTM EPS，缺少時依序使用淨利／營業利益／毛利 EPS 代理。',
    valuationNote: '三個 tab 使用同一套祖魯 PEG；每檔顯示現在 PEG、PEG=1 合理價與 0.75／0.66 價值帶。',
    valuationFormula: ZULU_VALUATION_FORMULA,
    emptyBody: '目前共同 A 母體沒有同時具備已知價格、PE 與可推算成長率的候選。',
    accent: 'hot',
  },
  {
    key: 'growth',
    title: '成長股',
    subtitle: '共同 A 母體／LTM 成長與 PEG',
    horizon: '6～36 個月',
    metricLabel: 'EPS 成長／代理',
    description: '成長股不另建一個母體，直接在投信十日買超前 100 內尋找成長仍能支撐估值的標的。',
    condition: '母體：同一個投信十日買超前 100；PEG < 0.75，可優先看 PEG < 0.66。',
    selection: '篩選：依 LTM EPS 成長排序；沒有預估 EPS 時，依序用 LTM 淨利、營業利益、營收×毛利率、營收成長代理。',
    valuationNote: '估算方式會直接寫在股票列，不把毛利代理稱為正式淨利 EPS。',
    valuationFormula: ZULU_VALUATION_FORMULA,
    emptyBody: '目前共同 A 母體沒有足夠已知資料形成 PEG 價值候選。',
    accent: 'growth',
  },
  {
    key: 'lowPosition',
    title: '低位觀察',
    subtitle: '共同 A 母體／3.5 年回歸',
    horizon: '6～24 個月',
    metricLabel: '3.5年 Z 值',
    description: '在同一個 A 母體內找長期趨勢仍向上、目前價格落在 3.5 年回歸平均線下方的股票。',
    condition: '條件：3.5 年回歸可用、Z ≤ 0、slope > 0；嚴格低位使用 Z ≤ -1。投信排名不是低位條件。',
    selection: '篩選：先在 A 母體計算 3.5 年回歸 Z 與 slope，再依 Z 由低到高，最後套用 PEG 價值帶。',
    valuationNote: '股票列會同時顯示 3.5 年回歸 Z 值、現在 PEG、祖魯合理價與兩個價值帶。',
    valuationFormula: ZULU_VALUATION_FORMULA,
    emptyBody: '目前共同 A 母體沒有同時具備 3.5 年低位條件與可推算 PEG 的候選。',
    accent: 'low',
  },
]
