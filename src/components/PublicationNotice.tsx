import { useEffect, useState } from 'react'
import { comparePublication, loadPublicationFingerprint } from '../data/publication'
import type { LoadedRelease } from '../data/api'
import type { Release } from '../domain/types'

interface Props {
  release: Release
  source: LoadedRelease['source']
  contentHash: string | null
  onReload: () => void
}

export function PublicationNotice({ release, source, contentHash, onReload }: Props) {
  const [notice, setNotice] = useState<'new' | 'unknown' | null>(null)

  useEffect(() => {
    let cancelled = false
    let checking = false
    const check = async () => {
      if (checking || document.visibilityState === 'hidden') return
      checking = true
      try {
        const fingerprint = await loadPublicationFingerprint()
        if (cancelled || !fingerprint) return
        const comparison = comparePublication(fingerprint, release, source, contentHash)
        setNotice(comparison === 'current' ? null : comparison)
      } catch {
        // A missing or unavailable fingerprint does not affect the loaded release.
      } finally {
        checking = false
      }
    }
    const onVisibility = () => { if (document.visibilityState === 'visible') void check() }
    void check()
    const interval = window.setInterval(() => { void check() }, 5 * 60_000)
    window.addEventListener('focus', onVisibility)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelled = true
      window.clearInterval(interval)
      window.removeEventListener('focus', onVisibility)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [release.marketDate, release.runId, release.generatedAt, source, contentHash])

  if (!notice) return null
  if (notice === 'unknown') return <p className="publication-notice" role="status">目前使用瀏覽器快取，尚無法核對伺服器發布版本；網路恢復後會再次檢查。</p>
  return <div className="publication-notice" role="status">
    <span>發現新發布，畫面仍顯示目前版本。</span>
    <button type="button" onClick={onReload}>載入新發布（保留目前篩選）</button>
  </div>
}
