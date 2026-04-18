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
