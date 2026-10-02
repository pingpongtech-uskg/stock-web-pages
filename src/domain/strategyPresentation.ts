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
export const GROWTH_TOTAL_RETURN_FORMULA = '總報酬本益比（本站整理）：保守獲利成長率 = 多年度 EPS 成長 × 0.8；總報酬率（百分點）= 保守獲利成長率 + 已確認現金股利殖利率；總報酬本益比 = 總報酬率 ÷ 目前 PE；Forward EPS = TTM EPS ×（1 + 保守獲利成長率）；總報酬估值參考價（本站整理） = Forward EPS × 總報酬率；總報酬本益比 ≥ 1.2 才列低估研究候選。缺股利、缺多年度 EPS 或極端外推時不發布主合理價。祖魯 PEG 僅作交叉參考。'

export const strategyPresentations: readonly StrategyPresentation[] = [
  {
    key: 'trust',
    title: '投信關注',
    subtitle: '官方十日淨買超新進榜',
    horizon: '數日～數週',
    metricLabel: '十日淨買超（股）',
    description: '只看今天新進入官方投信十日淨買超前 10 的股票；昨天已在前 10 內的續留股不顯示。',
    condition: '母體：兩市場官方十日買賣超前 100；今天榜單與前一交易日完整前 10 做差集。',
    selection: '篩選：TPEx 張數先換算成股；只保留 entryStatus=new，隔天不再新進榜即可消失。',
    valuationNote: '投信新進榜訊號與成長訊號分開；有估值資料才顯示 PEG／情境價，缺資料明示「估值資料不足」。',
    valuationFormula: ZULU_VALUATION_FORMULA,
    emptyBody: '目前沒有官方投信十日淨買超前 10 新進榜股票。續留標的保留在榜單背景資料，不列為新進候選。',
    accent: 'hot',
  },
  {
    key: 'growth',
    title: '成長股',
    subtitle: '總報酬本益比（本站整理）',
    horizon: '6～36 個月',
    metricLabel: '總報酬本益比',
    description: '成長股不另建一個母體，直接在投信十日買超前 100 內尋找成長仍能支撐估值的標的。',
    condition: '母體：同一個投信十日買超前 100；總報酬本益比（本站整理） ≥ 1.2；且五項成長健康檢查至少 4/5（80%）。',
    selection: '篩選：使用可得完整年度 EPS 的多年度 CAGR；營收成長不代替獲利成長。缺已確認股利、多年度 EPS 或遇極端外推時不列為合理價候選。',
    valuationNote: '主估值使用總報酬本益比（本站整理）；祖魯 PEG 保留為交叉參考，不參與成長股主排序。成長股頁不顯示籌碼參考。',
    valuationFormula: GROWTH_TOTAL_RETURN_FORMULA,
    emptyBody: '目前沒有可列入成長股策略的候選；查看上方漏斗，區分缺少估值輸入、門檻未達與成長健康未達 4/5。',
    accent: 'growth',
  },
  {
    key: 'lowPosition',
    title: '低位觀察',
    subtitle: '共同 A 母體／3.5 年回歸',
    horizon: '6～24 個月',
    metricLabel: '3.5年 Z 值',
    description: '在同一個 A 母體內，觀察具有合格調整價歷史、長期趨勢向上，且目前價格位於 3.5 年回歸平均線下方的股票。',
    condition: '價格條件：合格調整價與 3.5 年回歸可用、Z ≤ 0、slope > 0。嚴格低位使用 Z ≤ -1。投信排名不是低位條件；財務健康狀態是旁證，不是價格觀察的必要門檻。',
    selection: '篩選：只列出正式訊號資格通過的調整價回歸觀察。raw proxy 或歷史不足不升級正式訊號；缺 EPS、PEG 或健康證據不會隱藏合格價格觀察。',
    valuationNote: '股票列顯示 3.5 年回歸與成長健康狀態；有可追溯正式／代理成長輸入才顯示 PEG 數值，代理明示估算／代理，缺資料顯示「PEG 不可用」。',
    valuationFormula: ZULU_VALUATION_FORMULA,
    emptyBody: '目前沒有同時具備合格調整價歷史、3.5 年回歸 Z ≤ 0 與 slope > 0 的正式價格觀察。PEG 缺值不會排除低位觀察；健康資料缺值也不會排除價格觀察。',
    accent: 'low',
  },
]
