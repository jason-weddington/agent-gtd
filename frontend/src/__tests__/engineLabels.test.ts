import { describe, it, expect } from 'vitest'
import { ENGINE_LABELS, BUILD_ENGINE_OPTIONS } from '../engineLabels'

describe('BUILD_ENGINE_OPTIONS', () => {
  it('has exactly 12 entries', () => {
    expect(BUILD_ENGINE_OPTIONS).toHaveLength(12)
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

  it('all claude-code-prefixed entries use parenthesized Claude Code format', () => {
    const claudeCodeOptions = BUILD_ENGINE_OPTIONS.filter((o) =>
      o.value.startsWith('claude-code')
    )
    expect(claudeCodeOptions.length).toBe(5)
    for (const opt of claudeCodeOptions) {
      expect(opt.displayLabel).toMatch(/^Claude Code \(.+\)$/)
    }
    // Also verify the exact labels for consistency
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'claude-code')?.displayLabel).toBe(
      'Claude Code (Opus)'
    )
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'claude-code-sonnet')?.displayLabel).toBe(
      'Claude Code (Sonnet)'
    )
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'claude-code-haiku')?.displayLabel).toBe(
      'Claude Code (Haiku)'
    )
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'claude-code-ollama')?.displayLabel).toBe(
      'Claude Code (Ollama)'
    )
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'claude-code-glm')?.displayLabel).toBe(
      'Claude Code (GLM)'
    )
  })

  it('talos entries appear after existing entries in the correct order', () => {
    const values = BUILD_ENGINE_OPTIONS.map((o) => o.value)
    const talosStart = values.indexOf('talos-haiku')
    expect(talosStart).toBe(6)
    expect(values[6]).toBe('talos-haiku')
    expect(values[7]).toBe('talos-sonnet')
    expect(values[8]).toBe('talos-opus')
    expect(values[9]).toBe('talos-qwen')
    expect(values[10]).toBe('talos-glm')
    expect(values[11]).toBe('talos-glm-flash')
  })

  it('talos entries use parenthesized Talos format', () => {
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'talos-haiku')?.displayLabel).toBe(
      'Talos (Haiku)'
    )
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'talos-sonnet')?.displayLabel).toBe(
      'Talos (Sonnet)'
    )
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'talos-opus')?.displayLabel).toBe(
      'Talos (Opus)'
    )
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'talos-qwen')?.displayLabel).toBe(
      'Talos (Qwen)'
    )
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'talos-glm')?.displayLabel).toBe(
      'Talos (GLM)'
    )
    expect(BUILD_ENGINE_OPTIONS.find((o) => o.value === 'talos-glm-flash')?.displayLabel).toBe(
      'Talos (GLM Flash)'
    )
  })
})

describe('ENGINE_LABELS', () => {
  it('covers all 12 BuildEngine values', () => {
    const expectedEngines = [
      'claude-code',
      'claude-code-ollama',
      'claude-code-glm',
      'claude-code-sonnet',
      'claude-code-haiku',
      'kiro',
      'talos-haiku',
      'talos-sonnet',
      'talos-opus',
      'talos-qwen',
      'talos-glm',
      'talos-glm-flash',
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

  it('talos-haiku, talos-sonnet, talos-opus use default color', () => {
    expect(ENGINE_LABELS['talos-haiku'].color).toBe('default')
    expect(ENGINE_LABELS['talos-sonnet'].color).toBe('default')
    expect(ENGINE_LABELS['talos-opus'].color).toBe('default')
  })

  it('talos-qwen, talos-glm, talos-glm-flash use warning color (Ollama-routed)', () => {
    expect(ENGINE_LABELS['talos-qwen'].color).toBe('warning')
    expect(ENGINE_LABELS['talos-glm'].color).toBe('warning')
    expect(ENGINE_LABELS['talos-glm-flash'].color).toBe('warning')
  })

  it('talos display labels match spec', () => {
    expect(ENGINE_LABELS['talos-haiku'].label).toBe('Talos Haiku')
    expect(ENGINE_LABELS['talos-sonnet'].label).toBe('Talos Sonnet')
    expect(ENGINE_LABELS['talos-opus'].label).toBe('Talos Opus')
    expect(ENGINE_LABELS['talos-qwen'].label).toBe('Talos Qwen')
    expect(ENGINE_LABELS['talos-glm'].label).toBe('Talos GLM')
    expect(ENGINE_LABELS['talos-glm-flash'].label).toBe('Talos GLM Flash')
  })
})
