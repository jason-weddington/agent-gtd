import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { toSnakeCase, toCamelCase, convertKeys, isDispatchServiceConfigured, apiKeyFieldPlaceholder, formatRelativeTime, formatFileSize } from '../utils'

describe('toSnakeCase', () => {
  it('converts camelCase to snake_case', () => {
    expect(toSnakeCase('helloWorld')).toBe('hello_world')
  })

  it('leaves already_snake unchanged', () => {
    expect(toSnakeCase('already_snake')).toBe('already_snake')
  })

  it('handles empty string', () => {
    expect(toSnakeCase('')).toBe('')
  })
})

describe('toCamelCase', () => {
  it('converts snake_case to camelCase', () => {
    expect(toCamelCase('hello_world')).toBe('helloWorld')
  })

  it('leaves alreadyCamel unchanged', () => {
    expect(toCamelCase('alreadyCamel')).toBe('alreadyCamel')
  })
})

describe('convertKeys', () => {
  it('converts top-level object keys', () => {
    const result = convertKeys({ hello_world: 1, foo_bar: 2 }, toCamelCase)
    expect(result).toEqual({ helloWorld: 1, fooBar: 2 })
  })

  it('converts nested object keys', () => {
    const result = convertKeys(
      { outer_key: { inner_key: 'value' } },
      toCamelCase,
    )
    expect(result).toEqual({ outerKey: { innerKey: 'value' } })
  })

  it('converts arrays of objects', () => {
    const result = convertKeys(
      [{ my_key: 1 }, { my_key: 2 }],
      toCamelCase,
    )
    expect(result).toEqual([{ myKey: 1 }, { myKey: 2 }])
  })

  it('passes null and primitives through', () => {
    expect(convertKeys(null, toCamelCase)).toBeNull()
    expect(convertKeys(42, toCamelCase)).toBe(42)
    expect(convertKeys('hello', toCamelCase)).toBe('hello')
  })

  it('snake→camel→snake roundtrip preserves keys', () => {
    const original = { hello_world: 1, foo_bar: { baz_qux: 2 } }
    const camel = convertKeys(original, toCamelCase)
    const back = convertKeys(camel, toSnakeCase)
    expect(back).toEqual(original)
  })
})

describe('isDispatchServiceConfigured', () => {
  it('returns false when serviceApiKeyPreview is empty', () => {
    expect(isDispatchServiceConfigured('http://dispatch.example.com', '')).toBe(false)
  })

  it('returns false when serviceUrl is empty', () => {
    expect(isDispatchServiceConfigured('', '****jL54')).toBe(false)
  })

  it('returns false when both are empty', () => {
    expect(isDispatchServiceConfigured('', '')).toBe(false)
  })

  it('returns true when both serviceUrl and serviceApiKeyPreview are set', () => {
    expect(isDispatchServiceConfigured('http://dispatch.example.com', '****jL54')).toBe(true)
  })

  it('returns false when serviceUrl is only whitespace', () => {
    expect(isDispatchServiceConfigured('   ', '****jL54')).toBe(false)
  })
})

describe('apiKeyFieldPlaceholder', () => {
  it('returns "Not configured" when preview is empty', () => {
    expect(apiKeyFieldPlaceholder('')).toBe('Not configured')
  })

  it('returns the preview string when it is non-empty', () => {
    expect(apiKeyFieldPlaceholder('****jL54')).toBe('****jL54')
  })

  it('returns any non-empty preview as-is', () => {
    expect(apiKeyFieldPlaceholder('****XXXX')).toBe('****XXXX')
  })
})

describe('formatRelativeTime', () => {
  const FIXED_NOW = new Date('2026-01-01T12:00:00.000Z').getTime()

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(FIXED_NOW)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns "just now" for a timestamp within the last 60 seconds', () => {
    const ts = new Date(FIXED_NOW - 30 * 1000).toISOString()
    expect(formatRelativeTime(ts)).toBe('just now')
  })

  it('returns minutes-ago for a timestamp 5 minutes ago', () => {
    const ts = new Date(FIXED_NOW - 5 * 60 * 1000).toISOString()
    expect(formatRelativeTime(ts)).toBe('5m ago')
  })

  it('returns hours-ago for a timestamp 2 hours ago', () => {
    const ts = new Date(FIXED_NOW - 2 * 60 * 60 * 1000).toISOString()
    expect(formatRelativeTime(ts)).toBe('2h ago')
  })

  it('returns days-ago for a timestamp 3 days ago', () => {
    const ts = new Date(FIXED_NOW - 3 * 24 * 60 * 60 * 1000).toISOString()
    expect(formatRelativeTime(ts)).toBe('3d ago')
  })

  it('returns a date string for timestamps older than 7 days', () => {
    const ts = new Date(FIXED_NOW - 10 * 24 * 60 * 60 * 1000).toISOString()
    const result = formatRelativeTime(ts)
    // Should be a locale date string, not a relative string
    expect(result).not.toContain('ago')
    expect(result.length).toBeGreaterThan(0)
  })
})

describe('formatFileSize', () => {
  it('formats 1024 bytes as "1.0 KB"', () => {
    expect(formatFileSize(1024)).toBe('1.0 KB')
  })

  it('formats 1536 bytes as "1.5 KB"', () => {
    expect(formatFileSize(1536)).toBe('1.5 KB')
  })

  it('formats 512 bytes as "0.5 KB"', () => {
    expect(formatFileSize(512)).toBe('0.5 KB')
  })

  it('formats 0 bytes as "0.0 KB"', () => {
    expect(formatFileSize(0)).toBe('0.0 KB')
  })

  it('formats large files in KB', () => {
    expect(formatFileSize(10 * 1024)).toBe('10.0 KB')
  })
})
