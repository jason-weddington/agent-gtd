import type { RepoMode } from './types'

export function toSnakeCase(str: string): string {
  return str.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`)
}

export function toCamelCase(str: string): string {
  return str.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase())
}

export function convertKeys(obj: unknown, fn: (s: string) => string): unknown {
  if (Array.isArray(obj)) return obj.map((v) => convertKeys(v, fn))
  if (obj !== null && typeof obj === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
      out[fn(k)] = convertKeys(v, fn)
    }
    return out
  }
  return obj
}

/**
 * Returns true if the given blockers array contains at least one item
 * whose status is not 'done'.  Accepts a generic shape so it can be
 * called without importing the full BlockerSummary type.
 */
export function hasUnresolvedBlockers(
  blockers: ReadonlyArray<{ status: string }> | undefined,
): boolean {
  return (blockers ?? []).some((b) => b.status !== 'done')
}

/**
 * Returns true if the dispatch service is fully configured —
 * both a service URL and an API key preview must be present.
 *
 * `serviceApiKeyPreview` is `""` when no key is stored and `"****XXXX"`
 * (or similar masked form) when a key is stored.  The drawer uses this to
 * decide whether to enable the Dispatch button.
 */
export function isDispatchServiceConfigured(
  serviceUrl: string,
  serviceApiKeyPreview: string,
): boolean {
  return serviceUrl.trim() !== '' && serviceApiKeyPreview !== ''
}

/**
 * Returns the placeholder text for the dispatch API key input field.
 * Shows the masked preview when a key is stored, otherwise a "not configured"
 * hint so the field looks empty when no key has been saved.
 */
export function apiKeyFieldPlaceholder(serviceApiKeyPreview: string): string {
  return serviceApiKeyPreview !== '' ? serviceApiKeyPreview : 'Not configured'
}

/**
 * Returns a human-readable relative time string for a given ISO timestamp.
 * Examples: "just now", "5m ago", "2h ago", "3d ago", "Jan 5, 2026".
 */
export function formatRelativeTime(dateStr: string): string {
  const diffMs = Date.now() - new Date(dateStr).getTime()
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return 'just now'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour}h ago`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return new Date(dateStr).toLocaleDateString()
}

/**
 * Formats a list of dispatch service versions into a display label.
 *
 * - Empty array → `{label: 'unknown', mixed: false}`
 * - Single version → `{label: '<version>', mixed: false}`
 * - Multiple versions → `{label: 'mixed (<v1>, <v2>)', mixed: true}`
 *
 * The input versions are displayed in the order provided (callers should
 * pre-sort them if a stable order is desired).
 */
export function formatDispatchVersions(versions: string[]): { label: string; mixed: boolean } {
  if (versions.length === 0) return { label: 'unknown', mixed: false }
  if (versions.length === 1) return { label: versions[0], mixed: false }
  return { label: 'mixed (' + versions.join(', ') + ')', mixed: true }
}

/**
 * Prunes a selected-labels array to only contain labels that still exist in
 * `allLabels`.  The invariant that prevents render loops: returns the SAME
 * `selected` array reference (identity-equal, ===) when nothing was pruned,
 * so React's Object.is bail-out fires and no state update is committed.  A
 * new filtered array is returned only when at least one label was removed.
 *
 * This is the pure helper extracted from ProjectDetail's reconcile effect
 * (the useEffect keyed on [allLabels]).  Keeping the same-reference-return
 * here — not inside an inline arrow — is what makes the invariant testable
 * and guards against the ~239 Hz render loop described in kb-01682 / commit
 * 16f0703.
 */
export function pruneSelectedLabels(selected: string[], allLabels: string[]): string[] {
  const next = selected.filter((label) => allLabels.includes(label))
  return next.length === selected.length ? selected : next
}

/**
 * Formats a byte count as a KB string with one decimal place.
 * Example: formatFileSize(1536) → "1.5 KB".
 */
export function formatFileSize(bytes: number): string {
  return `${(bytes / 1024).toFixed(1)} KB`
}

/**
 * Returns the dispatch source string for a project, or null when dispatch
 * is not possible.
 *
 * - Non-workspace mode (or repoMode undefined) → returns gitOrigin, or null
 *   when gitOrigin is empty/undefined.
 * - Workspace mode → returns 'Workspace (N repos)' when N >= 1, or null when
 *   the workspace has zero repos.
 *
 * Callers coerce null → undefined when passing to optional string props.
 */
export function projectDispatchSource(p: {
  repoMode?: RepoMode
  gitOrigin?: string
  workspaceRepos?: string[]
}): string | null {
  if (p.repoMode !== 'workspace') {
    return p.gitOrigin || null
  }
  const n = (p.workspaceRepos ?? []).length
  if (n === 0) return null
  if (n === 1) return 'Workspace (1 repo)'
  return `Workspace (${n} repos)`
}

/**
 * Returns a human-readable elapsed duration from a given ISO start timestamp
 * to now.  Returns "—" when startedAt is null.
 *
 * Format:
 *   - null → "—"
 *   - < 60 min → "Xm"   (e.g. "14m")
 *   - ≥ 60 min → "Xh Ym" (e.g. "1h 6m")
 *
 * AC-5, AC-6, AC-15, AC-16.
 */
export function formatElapsed(startedAt: string | null): string {
  if (startedAt === null) return '—'
  const diffMs = Date.now() - new Date(startedAt).getTime()
  const totalMinutes = Math.floor(diffMs / (1000 * 60))
  if (totalMinutes < 60) return `${totalMinutes}m`
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${hours}h ${minutes}m`
}
