export interface PublicationFingerprint {
  schemaVersion: 'publication-fingerprint-v1'
  marketDate: string | null
  runId: string
  generatedAt: string
  contentHash: string
}

type PublicationRelease = Pick<PublicationFingerprint, 'marketDate' | 'runId' | 'generatedAt'>
type ReleaseSource = 'network' | 'cache'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function validatePublicationFingerprint(value: unknown): PublicationFingerprint {
  if (!isRecord(value)
    || value.schemaVersion !== 'publication-fingerprint-v1'
    || !(value.marketDate === null || (typeof value.marketDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value.marketDate)))
    || typeof value.runId !== 'string' || !value.runId
    || typeof value.generatedAt !== 'string' || !Number.isFinite(Date.parse(value.generatedAt))
    || typeof value.contentHash !== 'string' || !/^[a-f0-9]{64}$/.test(value.contentHash)) {
    throw new Error('發布識別格式錯誤')
  }
  return value as unknown as PublicationFingerprint
}

export function comparePublication(
  fingerprint: PublicationFingerprint,
  release: PublicationRelease,
  source: ReleaseSource,
  contentHash: string | null,
): 'current' | 'new' | 'unknown' {
  if (fingerprint.marketDate !== release.marketDate || fingerprint.runId !== release.runId || fingerprint.generatedAt !== release.generatedAt) return 'new'
  if (source !== 'network' || !contentHash) return 'unknown'
  return fingerprint.contentHash === contentHash ? 'current' : 'new'
}

export async function loadPublicationFingerprint(): Promise<PublicationFingerprint | null> {
  const response = await fetch('/data/publication.json', { headers: { Accept: 'application/json' }, cache: 'no-store' })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`發布識別讀取失敗（${response.status}）`)
  return validatePublicationFingerprint(await response.json())
}
