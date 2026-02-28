import { describe, it, expect } from 'vitest'
import { toSnakeCase, toCamelCase, convertKeys } from '../utils'

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
