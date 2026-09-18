export const STATEMENT_DOG_HEALTH_CHECK_BASE = 'https://statementdog.com/analysis'

const STOCK_CODE_PATTERN = /^\d{4,6}$/

export function statementDogHealthCheckUrl(code: string): string | null {
  const normalized = code.trim()
  if (!STOCK_CODE_PATTERN.test(normalized)) return null
  return `${STATEMENT_DOG_HEALTH_CHECK_BASE}/${normalized}/stock-health-check`
}
