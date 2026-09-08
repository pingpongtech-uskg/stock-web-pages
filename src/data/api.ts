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
  const detail = await getJson<StockDetail>(`${DATA_ROOT}/releases/${encodeURIComponent(runId)}/stocks/${safeCode}.json`)
  if (detail.code !== code) {
    throw new Error('個股資料代碼與請求不一致')
  }
  return detail
}
