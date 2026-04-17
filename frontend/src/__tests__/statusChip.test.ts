import { describe, it, expect } from 'vitest'
import { STATUS_CHIP_LABEL, STATUS_CHIP_COLOR } from '../components/review/statusChip'
import type { ItemStatus } from '../types'

/** Statuses that should appear in the Projects review step (step 4). */
const STEP4_STATUSES: ItemStatus[] = [
  'new',
  'ready',
  'next_action',
  'active',
  'review',
  'waiting_for',
  'inbox',
]

describe('STATUS_CHIP_LABEL', () => {
  it('maps new → New', () => {
    expect(STATUS_CHIP_LABEL['new']).toBe('New')
  })

  it('maps ready → Ready', () => {
    expect(STATUS_CHIP_LABEL['ready']).toBe('Ready')
  })

  it('maps next_action → Ready (legacy, same kanban column as ready)', () => {
    expect(STATUS_CHIP_LABEL['next_action']).toBe('Ready')
  })

  it('maps active → In Progress', () => {
    expect(STATUS_CHIP_LABEL['active']).toBe('In Progress')
  })

  it('maps review → Review', () => {
    expect(STATUS_CHIP_LABEL['review']).toBe('Review')
  })

  it('maps waiting_for → Waiting', () => {
    expect(STATUS_CHIP_LABEL['waiting_for']).toBe('Waiting')
  })

  it('has a label for every step-4 status', () => {
    for (const status of STEP4_STATUSES) {
      expect(STATUS_CHIP_LABEL[status]).toBeTruthy()
    }
  })

  it('does not define a label for someday_maybe (someday items never appear in step 4)', () => {
    expect(STATUS_CHIP_LABEL['someday_maybe']).toBeUndefined()
  })

  it('does not define a label for done or cancelled (terminal statuses filtered out)', () => {
    expect(STATUS_CHIP_LABEL['done']).toBeUndefined()
    // 'cancelled' is not in the ItemStatus union but filtered defensively
  })
})

describe('STATUS_CHIP_COLOR', () => {
  it('assigns info color to ready/next_action (actionable queue)', () => {
    expect(STATUS_CHIP_COLOR['ready']).toBe('info')
    expect(STATUS_CHIP_COLOR['next_action']).toBe('info')
  })

  it('assigns primary color to active (in progress)', () => {
    expect(STATUS_CHIP_COLOR['active']).toBe('primary')
  })

  it('assigns warning color to review (needs attention)', () => {
    expect(STATUS_CHIP_COLOR['review']).toBe('warning')
  })

  it('assigns default color to new, waiting_for, inbox (neutral/parked)', () => {
    expect(STATUS_CHIP_COLOR['new']).toBe('default')
    expect(STATUS_CHIP_COLOR['waiting_for']).toBe('default')
    expect(STATUS_CHIP_COLOR['inbox']).toBe('default')
  })

  it('has a color for every step-4 status', () => {
    for (const status of STEP4_STATUSES) {
      expect(STATUS_CHIP_COLOR[status]).toBeTruthy()
    }
  })

  it('does not define a color for someday_maybe', () => {
    expect(STATUS_CHIP_COLOR['someday_maybe']).toBeUndefined()
  })
})
