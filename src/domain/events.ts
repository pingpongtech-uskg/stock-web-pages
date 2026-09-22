export type AppEventName =
  | 'dashboard_view'
  | 'release_load_success'
  | 'release_load_error'
  | 'release_schema_rejected'
  | 'stale_or_degraded_banner_view'
  | 'strategy_tab_select'
  | 'candidate_impression'
  | 'valuation_evidence_view'
  | 'candidate_external_open'
  | 'retry_release'
  | 'history_view'

export interface AppEvent {
  name: AppEventName
  detail: Record<string, string | number | boolean | null>
  at: string
}

declare global {
  interface Window {
    /** QA-inspectable event buffer; never sent to a network endpoint. */
    __appEvents?: AppEvent[]
  }
}

const firedOnce = new Set<string>()

/**
 * Minimal local event layer for the release/dashboard lifecycle.  Events are
 * buffered on `window.__appEvents` (and re-dispatched as an `app-event`
 * CustomEvent) so QA can observe them without any tracking network call and
 * without collecting holdings or personal notes.
 */
export function trackEvent(name: AppEventName, detail: Record<string, string | number | boolean | null> = {}): void {
  if (typeof window === 'undefined') return
  const event: AppEvent = { name, detail, at: new Date().toISOString() }
  window.__appEvents = [...(window.__appEvents ?? []), event]
  window.dispatchEvent(new CustomEvent('app-event', { detail: event }))
}

export function trackEventOnce(key: string, name: AppEventName, detail?: Record<string, string | number | boolean | null>): void {
  if (firedOnce.has(key)) return
  firedOnce.add(key)
  trackEvent(name, detail)
}
