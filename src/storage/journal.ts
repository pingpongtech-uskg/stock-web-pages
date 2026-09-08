export interface TradeEntry {
  id: string
  decisionId: string
  code: string
  name: string
  action: 'buy' | 'add' | 'sell' | 'dividend' | 'fee' | 'deposit' | 'withdrawal' | 'split'
  date: string
  shares: number | null
  price: number | null
  amount: number | null
  note: string
}

export interface JournalState {
  watchlist: string[]
  notes: Record<string, string>
  trades: TradeEntry[]
  scenario: {
    valuation: string
    stopLossPct: number
    note: string
  }
}

const DB_NAME = 'taiwan-stock-screener'
const DB_VERSION = 1
const STORE = 'journal'
const STATE_KEY = 'current'
const FALLBACK_KEY = 'taiwan-stock-screener-journal'

export const emptyJournal: JournalState = {
  watchlist: [],
  notes: {},
  trades: [],
  scenario: { valuation: '', stopLossPct: 12, note: '' },
}

function cloneDefault(): JournalState {
  return JSON.parse(JSON.stringify(emptyJournal)) as JournalState
}

function normalise(value: Partial<JournalState> | null | undefined): JournalState {
  return {
    watchlist: Array.from(new Set(value?.watchlist ?? [])).filter((code) => /^\d{4,6}[A-Z-]*$/.test(code)),
    notes: value?.notes ?? {},
    trades: value?.trades ?? [],
    scenario: { ...emptyJournal.scenario, ...(value?.scenario ?? {}) },
  }
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in window)) {
      reject(new Error('IndexedDB unavailable'))
      return
    }
    const request = window.indexedDB.open(DB_NAME, DB_VERSION)
    request.onerror = () => reject(request.error ?? new Error('IndexedDB open failed'))
    request.onsuccess = () => resolve(request.result)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE)
    }
  })
}

export async function loadJournal(): Promise<JournalState> {
  try {
    const db = await openDb()
    const value = await new Promise<JournalState | undefined>((resolve, reject) => {
      const request = db.transaction(STORE, 'readonly').objectStore(STORE).get(STATE_KEY)
      request.onsuccess = () => resolve(request.result as JournalState | undefined)
      request.onerror = () => reject(request.error)
    })
    db.close()
    return normalise(value)
  } catch {
    try {
      const raw = window.localStorage.getItem(FALLBACK_KEY)
      return normalise(raw ? JSON.parse(raw) : undefined)
    } catch {
      return cloneDefault()
    }
  }
}

export async function saveJournal(state: JournalState): Promise<void> {
  const value = normalise(state)
  try {
    const db = await openDb()
    await new Promise<void>((resolve, reject) => {
      const request = db.transaction(STORE, 'readwrite').objectStore(STORE).put(value, STATE_KEY)
      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
    db.close()
  } catch {
    window.localStorage.setItem(FALLBACK_KEY, JSON.stringify(value))
  }
}

export function exportJournal(state: JournalState): string {
  return JSON.stringify({ schemaVersion: '1.0', exportedAt: new Date().toISOString(), ...normalise(state) }, null, 2)
}

export function parseJournalImport(raw: string): JournalState {
  if (raw.length > 2_000_000) throw new Error('匯入檔過大')
  const parsed = JSON.parse(raw) as Partial<JournalState>
  if (!parsed || typeof parsed !== 'object') throw new Error('匯入格式錯誤')
  return normalise(parsed)
}
