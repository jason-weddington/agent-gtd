/**
 * Tests for WaveBanner pure helper functions.
 *
 * AC-3, AC-4, AC-5 (pure helper coverage).
 */
import { describe, it, expect } from 'vitest'
import { getStatusColor, getTitleText, getProgressFraction } from '../components/WaveBanner'
import type { WaveRunStatus } from '../types'

// ---------------------------------------------------------------------------
// getStatusColor (AC-4)
// ---------------------------------------------------------------------------

describe('getStatusColor', () => {
  const cases: Array<[WaveRunStatus, string]> = [
    ['pending', 'default'],
    ['planning', 'default'],
    ['running', 'info'],
    ['halted', 'warning'],
    ['crashed', 'error'],
    ['completed', 'success'],
  ]

  for (const [status, expected] of cases) {
    it(`returns '${expected}' for status '${status}'`, () => {
      expect(getStatusColor(status)).toBe(expected)
    })
  }
})

// ---------------------------------------------------------------------------
// getTitleText (AC-3)
// ---------------------------------------------------------------------------

describe('getTitleText', () => {
  it('returns "Autonomous Dispatch Management in Progress" for pending', () => {
    expect(getTitleText('pending')).toBe('Autonomous Dispatch Management in Progress')
  })

  it('returns "Autonomous Dispatch Management in Progress" for planning', () => {
    expect(getTitleText('planning')).toBe('Autonomous Dispatch Management in Progress')
  })

  it('returns "Autonomous Dispatch Management in Progress" for running', () => {
    expect(getTitleText('running')).toBe('Autonomous Dispatch Management in Progress')
  })

  it('returns "Wave Halted — Review Needed" for halted', () => {
    expect(getTitleText('halted')).toBe('Wave Halted — Review Needed')
  })

  it('returns "Wave Crashed" for crashed', () => {
    expect(getTitleText('crashed')).toBe('Wave Crashed')
  })

  it('returns "Wave Completed" for completed', () => {
    expect(getTitleText('completed')).toBe('Wave Completed')
  })
})

// ---------------------------------------------------------------------------
// getProgressFraction (AC-5)
// ---------------------------------------------------------------------------

describe('getProgressFraction', () => {
  it('returns 0 when totalCount is 0', () => {
    expect(getProgressFraction(0, 0)).toBe(0)
  })

  it('returns 0 when doneCount is 0', () => {
    expect(getProgressFraction(0, 10)).toBe(0)
  })

  it('returns 0.5 when half done', () => {
    expect(getProgressFraction(5, 10)).toBe(0.5)
  })

  it('returns 1 when all done', () => {
    expect(getProgressFraction(10, 10)).toBe(1)
  })

  it('clamps to 1 when doneCount exceeds totalCount', () => {
    expect(getProgressFraction(12, 10)).toBe(1)
  })

  it('handles single item done', () => {
    expect(getProgressFraction(1, 5)).toBeCloseTo(0.2)
  })
})
