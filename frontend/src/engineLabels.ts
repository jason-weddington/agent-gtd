import type { BuildEngine } from './types'

export const ENGINE_LABELS: Record<BuildEngine, { label: string; color: 'warning' | 'default' }> = {
  'claude-code': { label: 'Opus', color: 'default' },
  'claude-code-sonnet': { label: 'Sonnet', color: 'default' },
  'claude-code-haiku': { label: 'Haiku', color: 'default' },
  'claude-code-ollama': { label: 'Ollama', color: 'warning' },
  kiro: { label: 'Kiro', color: 'default' },
}

export const BUILD_ENGINE_OPTIONS: { value: BuildEngine; displayLabel: string }[] = [
  { value: 'claude-code', displayLabel: 'Claude Code (Opus)' },
  { value: 'claude-code-sonnet', displayLabel: 'Claude Code (Sonnet)' },
  { value: 'claude-code-haiku', displayLabel: 'Claude Code (Haiku)' },
  { value: 'claude-code-ollama', displayLabel: 'Claude Code (Ollama)' },
  { value: 'kiro', displayLabel: 'Kiro' },
]
