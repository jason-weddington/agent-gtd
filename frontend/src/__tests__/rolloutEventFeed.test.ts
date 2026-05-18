import { describe, it, expect } from 'vitest'
import { shortId } from '../components/RolloutEventFeed'

describe('shortId', () => {
  it('returns "—" for null input', () => {
    expect(shortId(null)).toBe('—')
  })

  it('returns "—" for empty string', () => {
    expect(shortId('')).toBe('—')
  })

  it('returns an 8-char string as-is', () => {
    expect(shortId('abcd1234')).toBe('abcd1234')
  })

  it('returns first 8 chars of a UUID', () => {
    expect(shortId('4ef39441-867d-4d86-8ab8-d22e0de35ff2')).toBe('4ef39441')
  })
})
