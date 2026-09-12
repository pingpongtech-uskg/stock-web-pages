import type { Release, StockDetail } from '../domain/types'

const DATA_ROOT = '/data'

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    throw new Error(`資料讀取失敗（${response.status}）`)
  }
  return response.json() as Promise<T>
}

export async function loadLatestRelease(): Promise<Release> {
  const release = await getJson<Release>(`${DATA_ROOT}/latest.json`)
  if (!release.runId || !release.schemaVersion) {
    throw new Error('發布快照缺少版本識別，拒絕混用資料')
  }
  return release
}

export async function loadStockDetail(runId: string, code: string): Promise<StockDetail> {
  const safeCode = encodeURIComponent(code)
  try {
    const detail = await getJson<StockDetail>(`${DATA_ROOT}/releases/${encodeURIComponent(runId)}/stocks/${safeCode}.json`)
    if (detail.code !== code) {
      throw new Error('個股資料代碼與請求不一致')
    }
    return detail
  } catch (error) {
    // Rankings are still useful while a large per-stock evidence file is
    // propagating through Pages.  Render the same release summary instead of
    // turning the whole stock page into a 404; the page clearly shows that
    // its detailed chart/evidence is waiting for the next data sync.
    const release = await loadLatestRelease()
    const summary = release.stocks.find((stock) => stock.code === code)
    if (!summary) throw error
    return {
      ...summary,
      priceSeries: [],
      regression: {
        status: 'unknown', method: 'pending-detail-sync', label: '明細同步中',
        intercept: null, slope: summary.slope, lastMid: null, sigma: null, z: summary.zScore,
        bands: { '-2': null, '-1': null, '0': null, '1': null, '2': null }, coveragePct: null,
        historyStart: null, historyEnd: null, signalEligible: false, reason: '排行榜快照可用，個股明細尚未同步。', sourceRefs: summary.sourceRefs,
      },
      institutionalDaily: [], revenueMonthly: [], qualityChecks: [], historySnapshots: [], notes: [],
      detailLimitations: ['個股明細尚未同步；排行榜數值仍來自同一發布快照。'],
    }
  }
}
