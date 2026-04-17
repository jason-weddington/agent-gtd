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
