import { describe, expect, it } from 'vitest'
import { statementDogHealthCheckUrl } from './statementDog'

describe('Statement Dog health check URL', () => {
  it('builds the exact URL for 1736', () => {
    expect(statementDogHealthCheckUrl('1736')).toBe('https://statementdog.com/analysis/1736/stock-health-check')
  })

  it('trims a valid code', () => {
    expect(statementDogHealthCheckUrl(' 2330 ')).toBe('https://statementdog.com/analysis/2330/stock-health-check')
  })

  it('rejects malformed codes', () => {
    expect(statementDogHealthCheckUrl('javascript:alert(1)')).toBeNull()
    expect(statementDogHealthCheckUrl('ABC')).toBeNull()
  })
})
