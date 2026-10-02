import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import type { Release } from '../domain/types'
import { PublicationNotice } from './PublicationNotice'

describe('PublicationNotice', () => {
  it('announces same-date corrections and reloads without replacing history filters', async () => {
    const previousFetch = globalThis.fetch
    const previousUrl = window.location.href
    const originalPath = '/?view=history&strategy=lowPosition&from=2026-10-01'
    window.history.replaceState({ historyView: true }, '', originalPath)
    globalThis.fetch = vi.fn(async () => ({
      ok: true, status: 200,
      json: async () => ({
        schemaVersion: 'publication-fingerprint-v1', marketDate: '2026-10-02',
        runId: 'same-run', generatedAt: '2026-10-02T10:00:00Z', contentHash: 'b'.repeat(64),
      }),
    }) as Response)
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    let reloads = 0
    const release = { marketDate: '2026-10-02', runId: 'same-run', generatedAt: '2026-10-02T10:00:00Z' } as Release
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

    try {
      await act(async () => { root.render(<PublicationNotice release={release} source="network" contentHash={'a'.repeat(64)} onReload={() => { reloads += 1 }} />) })
      await vi.waitFor(() => expect(host.textContent).toContain('發現新發布'))
      expect(host.textContent).toContain('載入新發布（保留目前篩選）')
      expect(window.location.search).toBe('?view=history&strategy=lowPosition&from=2026-10-01')
      await act(async () => { host.querySelector('button')?.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
      expect(reloads).toBe(1)
      expect(window.location.search).toBe('?view=history&strategy=lowPosition&from=2026-10-01')
    } finally {
      await act(async () => root.unmount())
      host.remove()
      globalThis.fetch = previousFetch
      window.history.replaceState({}, '', new URL(previousUrl).pathname + new URL(previousUrl).search)
    }
  })
})
