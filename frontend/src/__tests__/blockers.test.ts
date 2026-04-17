import { describe, it, expect } from 'vitest'
import { hasUnresolvedBlockers } from '../utils'

describe('hasUnresolvedBlockers', () => {
  it('returns false for undefined', () => {
    expect(hasUnresolvedBlockers(undefined)).toBe(false)
  })

  it('returns false for an empty array', () => {
    expect(hasUnresolvedBlockers([])).toBe(false)
  })

  it('returns false when all blockers are done', () => {
    expect(hasUnresolvedBlockers([{ status: 'done' }, { status: 'done' }])).toBe(false)
  })

  it('returns true when at least one blocker is not done', () => {
    expect(hasUnresolvedBlockers([{ status: 'done' }, { status: 'active' }])).toBe(true)
  })

  it('returns true for a single non-done blocker', () => {
    expect(hasUnresolvedBlockers([{ status: 'next_action' }])).toBe(true)
  })

  it('returns true when no blockers are done', () => {
    expect(hasUnresolvedBlockers([{ status: 'inbox' }, { status: 'review' }])).toBe(true)
  })
})
