import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { toSnakeCase, toCamelCase, convertKeys, isDispatchServiceConfigured, apiKeyFieldPlaceholder, formatRelativeTime, formatFileSize, formatElapsed, formatDispatchVersions, pruneSelectedLabels, projectDispatchSource } from '../utils'

describe('toSnakeCase', () => {
  it('converts camelCase to snake_case', () => {
    expect(toSnakeCase('helloWorld')).toBe('hello_world')
  })

  it('leaves already_snake unchanged', () => {
    expect(toSnakeCase('already_snake')).toBe('already_snake')
  })

  it('handles empty string', () => {
    expect(toSnakeCase('')).toBe('')
  })
})

describe('toCamelCase', () => {
  it('converts snake_case to camelCase', () => {
    expect(toCamelCase('hello_world')).toBe('helloWorld')
  })

  it('leaves alreadyCamel unchanged', () => {
    expect(toCamelCase('alreadyCamel')).toBe('alreadyCamel')
  })
})

describe('convertKeys', () => {
  it('converts top-level object keys', () => {
    const result = convertKeys({ hello_world: 1, foo_bar: 2 }, toCamelCase)
    expect(result).toEqual({ helloWorld: 1, fooBar: 2 })
  })

  it('converts nested object keys', () => {
    const result = convertKeys(
      { outer_key: { inner_key: 'value' } },
      toCamelCase,
    )
    expect(result).toEqual({ outerKey: { innerKey: 'value' } })
  })

  it('converts arrays of objects', () => {
    const result = convertKeys(
      [{ my_key: 1 }, { my_key: 2 }],
      toCamelCase,
    )
    expect(result).toEqual([{ myKey: 1 }, { myKey: 2 }])
  })

  it('passes null and primitives through', () => {
    expect(convertKeys(null, toCamelCase)).toBeNull()
    expect(convertKeys(42, toCamelCase)).toBe(42)
    expect(convertKeys('hello', toCamelCase)).toBe('hello')
  })

  it('snake→camel→snake roundtrip preserves keys', () => {
    const original = { hello_world: 1, foo_bar: { baz_qux: 2 } }
    const camel = convertKeys(original, toCamelCase)
    const back = convertKeys(camel, toSnakeCase)
    expect(back).toEqual(original)
  })

  it('converts the key but leaves string-array elements untouched (workspaceRepos passthrough)', () => {
    expect(convertKeys({ workspaceRepos: ['a', 'b'] }, toSnakeCase)).toEqual({ workspace_repos: ['a', 'b'] })
  })
})

describe('isDispatchServiceConfigured', () => {
  it('returns false when serviceApiKeyPreview is empty', () => {
    expect(isDispatchServiceConfigured('http://dispatch.example.com', '')).toBe(false)
  })

  it('returns false when serviceUrl is empty', () => {
    expect(isDispatchServiceConfigured('', '****jL54')).toBe(false)
  })

  it('returns false when both are empty', () => {
    expect(isDispatchServiceConfigured('', '')).toBe(false)
  })

  it('returns true when both serviceUrl and serviceApiKeyPreview are set', () => {
    expect(isDispatchServiceConfigured('http://dispatch.example.com', '****jL54')).toBe(true)
  })

  it('returns false when serviceUrl is only whitespace', () => {
    expect(isDispatchServiceConfigured('   ', '****jL54')).toBe(false)
  })
})

describe('apiKeyFieldPlaceholder', () => {
  it('returns "Not configured" when preview is empty', () => {
    expect(apiKeyFieldPlaceholder('')).toBe('Not configured')
  })

  it('returns the preview string when it is non-empty', () => {
    expect(apiKeyFieldPlaceholder('****jL54')).toBe('****jL54')
  })

  it('returns any non-empty preview as-is', () => {
    expect(apiKeyFieldPlaceholder('****XXXX')).toBe('****XXXX')
  })
})

describe('formatRelativeTime', () => {
  const FIXED_NOW = new Date('2026-01-01T12:00:00.000Z').getTime()

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(FIXED_NOW)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns "just now" for a timestamp within the last 60 seconds', () => {
    const ts = new Date(FIXED_NOW - 30 * 1000).toISOString()
    expect(formatRelativeTime(ts)).toBe('just now')
  })

  it('returns minutes-ago for a timestamp 5 minutes ago', () => {
    const ts = new Date(FIXED_NOW - 5 * 60 * 1000).toISOString()
    expect(formatRelativeTime(ts)).toBe('5m ago')
  })

  it('returns hours-ago for a timestamp 2 hours ago', () => {
    const ts = new Date(FIXED_NOW - 2 * 60 * 60 * 1000).toISOString()
    expect(formatRelativeTime(ts)).toBe('2h ago')
  })

  it('returns days-ago for a timestamp 3 days ago', () => {
    const ts = new Date(FIXED_NOW - 3 * 24 * 60 * 60 * 1000).toISOString()
    expect(formatRelativeTime(ts)).toBe('3d ago')
  })

  it('returns a date string for timestamps older than 7 days', () => {
    const ts = new Date(FIXED_NOW - 10 * 24 * 60 * 60 * 1000).toISOString()
    const result = formatRelativeTime(ts)
    // Should be a locale date string, not a relative string
    expect(result).not.toContain('ago')
    expect(result.length).toBeGreaterThan(0)
  })
})

describe('formatFileSize', () => {
  it('formats 1024 bytes as "1.0 KB"', () => {
    expect(formatFileSize(1024)).toBe('1.0 KB')
  })

  it('formats 1536 bytes as "1.5 KB"', () => {
    expect(formatFileSize(1536)).toBe('1.5 KB')
  })

  it('formats 512 bytes as "0.5 KB"', () => {
    expect(formatFileSize(512)).toBe('0.5 KB')
  })

  it('formats 0 bytes as "0.0 KB"', () => {
    expect(formatFileSize(0)).toBe('0.0 KB')
  })

  it('formats large files in KB', () => {
    expect(formatFileSize(10 * 1024)).toBe('10.0 KB')
  })
})

describe('formatDispatchVersions', () => {
  it('returns {label: "unknown", mixed: false} for an empty array', () => {
    expect(formatDispatchVersions([])).toEqual({ label: 'unknown', mixed: false })
  })

  it('returns {label: version, mixed: false} for a single version', () => {
    expect(formatDispatchVersions(['1.9.0'])).toEqual({ label: '1.9.0', mixed: false })
  })

  it('returns {label: "mixed (...)", mixed: true} for two versions', () => {
    expect(formatDispatchVersions(['1.8.5', '1.9.0'])).toEqual({
      label: 'mixed (1.8.5, 1.9.0)',
      mixed: true,
    })
  })

  it('returns {label: "mixed (...)", mixed: true} for three or more versions', () => {
    expect(formatDispatchVersions(['1.7.0', '1.8.0', '1.9.0'])).toEqual({
      label: 'mixed (1.7.0, 1.8.0, 1.9.0)',
      mixed: true,
    })
  })
})

describe('formatElapsed', () => {
  const FIXED_NOW = new Date('2026-01-01T12:00:00.000Z').getTime()

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(FIXED_NOW)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns "—" for null startedAt (AC-16)', () => {
    expect(formatElapsed(null)).toBe('—')
  })

  it('returns minutes format for durations under 1 hour (AC-6)', () => {
    const start = new Date(FIXED_NOW - 14 * 60 * 1000).toISOString()
    expect(formatElapsed(start)).toBe('14m')
  })

  it('returns hours+minutes format for durations of 1 hour or more (AC-6)', () => {
    const start = new Date(FIXED_NOW - 66 * 60 * 1000).toISOString()
    expect(formatElapsed(start)).toBe('1h 6m')
  })

  it('returns "1h 0m" at the exact 60-minute boundary (AC-6)', () => {
    const start = new Date(FIXED_NOW - 60 * 60 * 1000).toISOString()
    expect(formatElapsed(start)).toBe('1h 0m')
  })

  it('returns "59m" just below the 1-hour boundary', () => {
    const start = new Date(FIXED_NOW - 59 * 60 * 1000).toISOString()
    expect(formatElapsed(start)).toBe('59m')
  })
})

// Regression guard for the ~239 Hz ProjectDetail render loop (kb-01682, commit 16f0703).
//
// The loop arose because the reconcile effect called setSelectedLabels with
// Array.prototype.filter, which always returns a NEW array — even when nothing
// is pruned.  React compares state via Object.is: a new array !== the previous
// array, so the state committed every render, which churned the allLabels
// identity, which re-ran the effect… ad infinitum.
//
// The fix: pruneSelectedLabels MUST return the SAME `selected` reference
// (===) when every selected label is still present in allLabels.  That
// identity equality lets React bail out of the state update, breaking the
// loop.  The tests below assert this invariant directly.
describe('pruneSelectedLabels', () => {
  it('(a) returns the SAME array reference when no labels are pruned', () => {
    const selected = ['bug', 'frontend']
    const allLabels = ['bug', 'frontend', 'backend']
    const result = pruneSelectedLabels(selected, allLabels)
    // Must be reference-equal (===), not just deep-equal — this is what
    // triggers React's Object.is bail-out and prevents the render loop.
    expect(result).toBe(selected)
  })

  it('(b) returns a new array with the missing label removed when one label is absent', () => {
    const selected = ['bug', 'obsolete']
    const allLabels = ['bug', 'frontend']
    const result = pruneSelectedLabels(selected, allLabels)
    expect(result).not.toBe(selected)
    expect(result).toEqual(['bug'])
  })

  it('(c) returns an empty array when all selected labels are absent from allLabels', () => {
    const selected = ['gone', 'also-gone']
    const allLabels = ['bug', 'frontend']
    const result = pruneSelectedLabels(selected, allLabels)
    expect(result).toEqual([])
  })

  it('(d) returns the SAME empty array reference when selected is already empty', () => {
    const selected: string[] = []
    const allLabels = ['bug', 'frontend']
    const result = pruneSelectedLabels(selected, allLabels)
    expect(result).toBe(selected)
  })

  it('(e) returns an empty array when allLabels is empty and selected is non-empty', () => {
    const selected = ['bug', 'frontend']
    const allLabels: string[] = []
    const result = pruneSelectedLabels(selected, allLabels)
    expect(result).toEqual([])
  })
})

describe('projectDispatchSource', () => {
  it('monorepo + origin → returns the origin string', () => {
    expect(projectDispatchSource({ repoMode: 'monorepo', gitOrigin: 'git@github.com:org/repo.git' })).toBe('git@github.com:org/repo.git')
  })

  it('monorepo + empty origin → null', () => {
    expect(projectDispatchSource({ repoMode: 'monorepo', gitOrigin: '' })).toBeNull()
  })

  it('repoMode undefined + origin → returns the origin string (monorepo fallback)', () => {
    expect(projectDispatchSource({ gitOrigin: 'git@github.com:org/repo.git' })).toBe('git@github.com:org/repo.git')
  })

  it('workspace + 0 repos → null', () => {
    expect(projectDispatchSource({ repoMode: 'workspace', workspaceRepos: [] })).toBeNull()
  })

  it('workspace + 1 repo → "Workspace (1 repo)"', () => {
    expect(projectDispatchSource({ repoMode: 'workspace', workspaceRepos: ['git@github.com:org/a.git'] })).toBe('Workspace (1 repo)')
  })

  it('workspace + 3 repos → "Workspace (3 repos)"', () => {
    expect(projectDispatchSource({ repoMode: 'workspace', workspaceRepos: ['a', 'b', 'c'] })).toBe('Workspace (3 repos)')
  })

  it('workspace + undefined workspaceRepos → null', () => {
    expect(projectDispatchSource({ repoMode: 'workspace' })).toBeNull()
  })
})
