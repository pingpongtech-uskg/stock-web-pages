import { describe, expect, it, vi } from 'vitest'
import { comparePublication, loadPublicationFingerprint, validatePublicationFingerprint } from './publication'

const current = {
  schemaVersion: 'publication-fingerprint-v1' as const,
  marketDate: '2026-10-02',
  runId: 'same-run',
  generatedAt: '2026-10-02T10:00:00Z',
  contentHash: 'a'.repeat(64),
}
const release = {
  marketDate: '2026-10-02', runId: 'same-run', generatedAt: '2026-10-02T10:00:00Z',
}

describe('publication fingerprint', () => {
  it('detects a same-date and same-run correction by exact content hash', () => {
    expect(comparePublication({ ...current, contentHash: 'b'.repeat(64) }, release, 'network', 'a'.repeat(64))).toBe('new')
    expect(comparePublication(current, release, 'network', 'a'.repeat(64))).toBe('current')
  })

  it('returns unknown when the visible release came from cache or has no exact byte hash', () => {
    expect(comparePublication(current, release, 'cache', null)).toBe('unknown')
    expect(comparePublication(current, release, 'network', null)).toBe('unknown')
  })

  it('validates the fingerprint fields and tolerates an absent pre-rollout file', async () => {
    expect(validatePublicationFingerprint(current)).toEqual(current)
    expect(() => validatePublicationFingerprint({ ...current, contentHash: 'short' })).toThrow('發布識別格式錯誤')
    const previousFetch = globalThis.fetch
    globalThis.fetch = vi.fn(async () => ({ ok: false, status: 404 })) as unknown as typeof fetch
    try {
      await expect(loadPublicationFingerprint()).resolves.toBeNull()
    } finally {
      globalThis.fetch = previousFetch
    }
  })
})
