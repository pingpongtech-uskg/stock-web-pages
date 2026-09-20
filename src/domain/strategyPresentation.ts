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

export const ZULU_VALUATION_FORMULA = '正式 PEG = 目前 PE ÷ 可驗證的 EPS／獲利成長率（%）；若成長輸入只有代理，仍顯示「估算／代理 PEG」與方法，但不等同正式 EPS PEG；當前 EPS 一律由「現價 ÷ 當期 PE」反推；Forward EPS = 當前 EPS ×（1 + 成長率）；祖魯基準價（PEG=1）= Forward EPS × 成長率（%）；PEG < 0.75 可接受、PEG < 0.66 嚴格。只有可追溯的正式或代理成長輸入才計算 PEG 與情境價；營收成長僅為觀察代理，不等同 EPS 成長。'

export const strategyPresentations: readonly StrategyPresentation[] = [
  {
    key: 'trust',
    title: '投信關注',
    subtitle: '官方十日淨買超 Top10／新進榜',
    horizon: '數日～數週',
    metricLabel: '十日淨買超（股）',
    description: '看官方 TWSE／TPEx 投信十日累積買超 Top10；新進榜是相對前一交易日完整 Top10 的變化。',
    condition: '母體：兩市場官方十日買賣超前 100；投信榜先看 Top10 與新進榜，PEG 只作估值顯示／警示。',
    selection: '篩選：TPEx 張數先換算成股，合併兩市場最近 10 個交易日；顯示前一交易日名次，不把缺歷史資料冒充新進榜。',
    valuationNote: '投信訊號與成長訊號分開；有估值資料才顯示 PEG／情境價，缺資料明示「估值資料不足」，不影響官方 Top10。',
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
    selection: '篩選：正式 EPS／獲利成長優先；營收成長只作明示代理，極端外推與資料不足不列為正式成長候選。',
    valuationNote: '營收成長不直接代入 EPS PEG；沒有可驗證獲利成長時不計算正式 PEG／情境價。',
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
    selection: '篩選：先在 A 母體計算 3.5 年回歸 Z 與 slope；財務健康另列，資料不足只作價格觀察。',
    valuationNote: '股票列顯示 3.5 年回歸與成長健康狀態；有可追溯正式／代理成長輸入才顯示 PEG 數值，代理明示估算／代理，缺資料顯示「PEG 不可用」。',
    valuationFormula: ZULU_VALUATION_FORMULA,
    emptyBody: '目前共同 A 母體沒有同時具備 3.5 年低位條件與可推算 PEG 的候選。',
    accent: 'low',
  },
]
