import type { BuildEngine } from './types'

export const ENGINE_LABELS: Record<BuildEngine, { label: string; color: 'warning' | 'default' }> = {
  'claude-code': { label: 'Opus', color: 'default' },
  'claude-code-sonnet': { label: 'Sonnet', color: 'default' },
  'claude-code-haiku': { label: 'Haiku', color: 'default' },
  'claude-code-ollama': { label: 'Ollama', color: 'warning' },
  'claude-code-glm': { label: 'GLM', color: 'warning' },
  kiro: { label: 'Kiro', color: 'default' },
  'talos-haiku': { label: 'Talos Haiku', color: 'default' },
  'talos-sonnet': { label: 'Talos Sonnet', color: 'default' },
  'talos-opus': { label: 'Talos Opus', color: 'default' },
  'talos-qwen': { label: 'Talos Qwen', color: 'warning' },
  'talos-glm': { label: 'Talos GLM', color: 'warning' },
  'talos-glm-flash': { label: 'Talos GLM Flash', color: 'warning' },
}

export const BUILD_ENGINE_OPTIONS: { value: BuildEngine; displayLabel: string }[] = [
  { value: 'claude-code', displayLabel: 'Claude Code (Opus)' },
  { value: 'claude-code-sonnet', displayLabel: 'Claude Code (Sonnet)' },
  { value: 'claude-code-haiku', displayLabel: 'Claude Code (Haiku)' },
  { value: 'claude-code-ollama', displayLabel: 'Claude Code (Ollama)' },
  { value: 'claude-code-glm', displayLabel: 'Claude Code (GLM)' },
  { value: 'kiro', displayLabel: 'Kiro' },
  { value: 'talos-haiku', displayLabel: 'Talos (Haiku)' },
  { value: 'talos-sonnet', displayLabel: 'Talos (Sonnet)' },
  { value: 'talos-opus', displayLabel: 'Talos (Opus)' },
  { value: 'talos-qwen', displayLabel: 'Talos (Qwen)' },
  { value: 'talos-glm', displayLabel: 'Talos (GLM)' },
  { value: 'talos-glm-flash', displayLabel: 'Talos (GLM Flash)' },
]
