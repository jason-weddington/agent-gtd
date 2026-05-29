import { describe, it, expect } from 'vitest'
import { ENGINE_LABELS, BUILD_ENGINE_OPTIONS } from '../engineLabels'

describe('BUILD_ENGINE_OPTIONS', () => {
  it('has exactly 5 entries', () => {
    expect(BUILD_ENGINE_OPTIONS).toHaveLength(5)
  })

  it('has no duplicate values', () => {
    const values = BUILD_ENGINE_OPTIONS.map((o) => o.value)
    const unique = new Set(values)
    expect(unique.size).toBe(values.length)
  })

  it('each entry has a corresponding ENGINE_LABELS entry with a non-empty label', () => {
    for (const opt of BUILD_ENGINE_OPTIONS) {
      expect(ENGINE_LABELS[opt.value]).toBeDefined()
      expect(ENGINE_LABELS[opt.value].label).toBeTruthy()
    }
  })
})

describe('ENGINE_LABELS', () => {
  it('covers all 5 BuildEngine values', () => {
    const expectedEngines = [
      'claude-code',
      'claude-code-ollama',
      'claude-code-sonnet',
      'claude-code-haiku',
      'kiro',
    ] as const
    for (const engine of expectedEngines) {
      expect(ENGINE_LABELS[engine]).toBeDefined()
      expect(ENGINE_LABELS[engine].label).toBeTruthy()
    }
  })

  it('assigns warning color to claude-code-ollama', () => {
    expect(ENGINE_LABELS['claude-code-ollama'].color).toBe('warning')
  })

  it('assigns default color to claude-code', () => {
    expect(ENGINE_LABELS['claude-code'].color).toBe('default')
  })
})
