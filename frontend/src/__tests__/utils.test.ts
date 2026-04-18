import { describe, it, expect } from 'vitest'
import { toSnakeCase, toCamelCase, convertKeys, isDispatchServiceConfigured, apiKeyFieldPlaceholder } from '../utils'

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
