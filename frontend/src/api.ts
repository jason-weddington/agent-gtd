import type { ActivityEvent, AdminUser, ApiKeyInfo, AttachmentResponse, AuthResponse, BlockerSummary, Comment, CreatedInvite, DispatchCapabilities, DispatchHost, FailedRun, Invite, Item, MemberSummary, Note, PasswordResetIssued, PlanRolloutResponse, Project, Rollout, RolloutEvent, RolloutFailureFeed, Run, StaleRun, UserResponse } from './types'
import { toSnakeCase, toCamelCase, convertKeys } from './utils'

// --- Helpers ---

class ApiError extends Error {
  status: number
  detail: string
  blockers?: Array<{ id: string; title: string; status: string }>

  constructor(
    status: number,
    detail: string,
    blockers?: Array<{ id: string; title: string; status: string }>,
  ) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.blockers = blockers
  }
}

function getToken(): string | null {
  return localStorage.getItem('agent_gtd-token')
}

// --- Core request ---

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  let fetchBody: BodyInit | undefined
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    fetchBody = JSON.stringify(convertKeys(body, toSnakeCase))
  }

  const res = await fetch(`/api${path}`, { method, headers, body: fetchBody })

  if (res.status === 204) return undefined as T

  if (res.status === 401) {
    localStorage.removeItem('agent_gtd-token')
    localStorage.removeItem('agent_gtd-user')
    // Defense in depth: don't redirect when already on /login, otherwise any
    // unauth API call from the login page (e.g. a global provider that forgot
    // to gate on auth state) will hard-reload and infinite-loop.
    if (window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
    throw new ApiError(401, 'Unauthorized')
  }

  if (!res.ok) {
    let detail = res.statusText
    let blockers: Array<{ id: string; title: string; status: string }> | undefined
    try {
      const json = await res.json()
      if (typeof json.detail === 'string') {
        detail = json.detail
      } else if (json.detail && typeof json.detail === 'object' && 'message' in json.detail) {
        detail = String((json.detail as { message: unknown }).message)
      }
      if (Array.isArray(json.blockers)) {
        blockers = json.blockers as Array<{ id: string; title: string; status: string }>
      }
    } catch {
      // use statusText
    }
    throw new ApiError(res.status, detail, blockers)
  }

  const json = await res.json()
  return convertKeys(json, toCamelCase) as T
}

// --- Upload request (FormData, no JSON body serialisation) ---

async function uploadRequest<T>(method: string, path: string, formData: FormData): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`/api${path}`, { method, headers, body: formData })

  if (res.status === 204) return undefined as T

  if (res.status === 401) {
    localStorage.removeItem('agent_gtd-token')
    localStorage.removeItem('agent_gtd-user')
    if (window.location.pathname !== '/login') {
      window.location.href = '/login'
    }
    throw new ApiError(401, 'Unauthorized')
  }

  if (!res.ok) {
    let detail = res.statusText
    let blockers: Array<{ id: string; title: string; status: string }> | undefined
    try {
      const json = await res.json()
      if (typeof json.detail === 'string') {
        detail = json.detail
      } else if (json.detail && typeof json.detail === 'object' && 'message' in json.detail) {
        detail = String((json.detail as { message: unknown }).message)
      }
      if (Array.isArray(json.blockers)) {
        blockers = json.blockers as Array<{ id: string; title: string; status: string }>
      }
    } catch {
      // use statusText
    }
    throw new ApiError(res.status, detail, blockers)
  }

  const json = await res.json()
  return convertKeys(json, toCamelCase) as T
}

// --- Blob download (raw bytes with auth, returns object URL) ---

async function fetchBlobUrl(path: string): Promise<string> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`/api${path}`, { headers })
  if (!res.ok) {
    throw new ApiError(res.status, res.statusText)
  }
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

// --- Namespaced API ---

export const api = {
  config: {
    get: () => request<{ localMode: boolean; version: string }>('GET', '/config'),
  },

  auth: {
    register: (email: string, password: string, inviteToken: string) =>
      request<AuthResponse>('POST', '/auth/register', { email, password, inviteToken }),
    login: (email: string, password: string) =>
      request<AuthResponse>('POST', '/auth/login', { email, password }),
    logout: () => request<void>('POST', '/auth/logout'),
    me: () => request<UserResponse>('GET', '/auth/me'),
    changePassword: (currentPassword: string, newPassword: string) =>
      request<void>('POST', '/auth/password', { currentPassword, newPassword }),
    passwordReset: (token: string, newPassword: string) =>
      request<void>('POST', '/auth/password-reset', { token, newPassword }),
  },

  apiKeys: {
    create: (name: string) =>
      request<{ apiKey: string; name: string }>('POST', '/auth/api-keys', { name }),
    list: () => request<{ keys: ApiKeyInfo[] }>('GET', '/auth/api-keys'),
    revoke: (id: string) => request<void>('DELETE', `/auth/api-keys/${id}`),
  },

  projects: {
    list: (params?: { status?: string; area?: string }) => {
      const query = new URLSearchParams()
      if (params?.status) query.set('status', params.status)
      if (params?.area) query.set('area', params.area)
      const qs = query.toString()
      return request<Project[]>('GET', `/projects${qs ? `?${qs}` : ''}`)
    },
    create: (data: { name: string; description?: string; status?: string; area?: string; gitOrigin?: string; kbProjectRef?: string }) =>
      request<Project>('POST', '/projects', data),
    get: (id: string) => request<Project>('GET', `/projects/${id}`),
    update: (id: string, data: Partial<Omit<Project, 'id' | 'createdAt' | 'updatedAt'>>) =>
      request<Project>('PATCH', `/projects/${id}`, data),
    delete: (id: string) => request<void>('DELETE', `/projects/${id}`),
    items: (id: string) => request<Item[]>('GET', `/projects/${id}/items`),
    createItem: (id: string, data: { title: string; description?: string; status?: string; priority?: string }) =>
      request<Item>('POST', `/projects/${id}/items`, data),
    notes: (id: string) => request<Note[]>('GET', `/projects/${id}/notes`),
    createNote: (id: string, data: { title?: string; contentMarkdown?: string; labels?: string[] }) =>
      request<Note>('POST', `/projects/${id}/notes`, data),
    comments: (id: string) => request<Comment[]>('GET', `/projects/${id}/comments`),
    createComment: (id: string, data: { contentMarkdown: string }) =>
      request<Comment>('POST', `/projects/${id}/comments`, data),
    members: {
      list: (id: string) => request<MemberSummary[]>('GET', `/projects/${id}/members`),
      add: (id: string, email: string) =>
        request<MemberSummary & { blockersPurged?: number }>('POST', `/projects/${id}/members`, { email }),
      remove: (id: string, userId: string) =>
        request<void>('DELETE', `/projects/${id}/members/${userId}`),
    },
  },

  items: {
    list: (params?: { status?: string; projectId?: string; priority?: string }) => {
      const query = new URLSearchParams()
      if (params?.status) query.set('status', params.status)
      if (params?.projectId) query.set('project_id', params.projectId)
      if (params?.priority) query.set('priority', params.priority)
      const qs = query.toString()
      return request<Item[]>('GET', `/items${qs ? `?${qs}` : ''}`)
    },
    inbox: () => request<Item[]>('GET', '/inbox'),
    capture: (title: string) => request<Item>('POST', '/inbox', { title }),
    create: (data: { title: string; description?: string; projectId?: string; status?: string; priority?: string }) =>
      request<Item>('POST', '/items', data),
    get: (id: string) => request<Item>('GET', `/items/${id}`),
    update: (id: string, data: Record<string, unknown>) =>
      request<Item>('PATCH', `/items/${id}`, data),
    delete: (id: string) => request<void>('DELETE', `/items/${id}`),
    comments: (id: string) => request<Comment[]>('GET', `/items/${id}/comments`),
    createComment: (id: string, data: { contentMarkdown: string }) =>
      request<Comment>('POST', `/items/${id}/comments`, data),
    dispatch: (id: string, data?: { maxTurns?: number; mode?: string; dispatchHostId?: string }) =>
      request<Run>('POST', `/items/${id}/dispatch`, data ?? {}),
    runs: (id: string) => request<Run[]>('GET', `/items/${id}/runs`),
    search: (q: string, limit = 10) =>
      request<BlockerSummary[]>('GET', `/items/search?q=${encodeURIComponent(q)}&limit=${limit}`),
    blockers: {
      list: (id: string) => request<BlockerSummary[]>('GET', `/items/${id}/blockers`),
      add: (id: string, blockerItemId: string) =>
        request<BlockerSummary>('POST', `/items/${id}/blockers`, { blockerItemId }),
      remove: (id: string, blockerItemId: string) =>
        request<void>('DELETE', `/items/${id}/blockers/${blockerItemId}`),
    },
  },

  runs: {
    list: (params?: { status?: string; itemId?: string; projectId?: string; scope?: string }) => {
      const query = new URLSearchParams()
      if (params?.status) query.set('status', params.status)
      if (params?.itemId) query.set('item_id', params.itemId)
      if (params?.projectId) query.set('project_id', params.projectId)
      if (params?.scope) query.set('scope', params.scope)
      const qs = query.toString()
      return request<Run[]>('GET', `/runs${qs ? `?${qs}` : ''}`)
    },
    get: (id: string) => request<Run>('GET', `/runs/${id}`),
    cancel: (id: string) => request<void>('DELETE', `/runs/${id}`),
    /** GET /api/runs/failures — failed and timeout runs across accessible projects. */
    failures: (params?: { limit?: number }) => {
      const query = new URLSearchParams()
      if (params?.limit !== undefined) query.set('limit', String(params.limit))
      const qs = query.toString()
      return request<FailedRun[]>('GET', `/runs/failures${qs ? `?${qs}` : ''}`)
    },
    /** GET /api/runs/stale — successful build-mode runs whose item wasn't advanced. */
    stale: (params?: { hours?: number; limit?: number }) => {
      const query = new URLSearchParams()
      if (params?.hours !== undefined) query.set('hours', String(params.hours))
      if (params?.limit !== undefined) query.set('limit', String(params.limit))
      const qs = query.toString()
      return request<StaleRun[]>('GET', `/runs/stale${qs ? `?${qs}` : ''}`)
    },
  },

  notes: {
    get: (id: string) => request<Note>('GET', `/notes/${id}`),
    update: (id: string, data: { title?: string; contentMarkdown?: string; labels?: string[] }) =>
      request<Note>('PATCH', `/notes/${id}`, data),
    delete: (id: string) => request<void>('DELETE', `/notes/${id}`),
  },

  comments: {
    get: (id: string) => request<Comment>('GET', `/comments/${id}`),
    update: (id: string, data: { contentMarkdown?: string }) =>
      request<Comment>('PATCH', `/comments/${id}`, data),
    delete: (id: string) => request<void>('DELETE', `/comments/${id}`),
  },

  rollouts: {
    /** POST /api/rollouts — plan a new rollout from selected ready items. */
    planRollout: (itemIds: string[]) =>
      request<PlanRolloutResponse>('POST', '/rollouts', { itemIds }),
    /** GET /api/rollouts/{id} — fetch a single rollout by ID. */
    get: (rolloutId: string) => request<Rollout>('GET', `/rollouts/${rolloutId}`),
    /** GET /api/projects/{projectId}/active-rollout — 404 if none active. */
    getActiveForProject: (projectId: string) =>
      request<Rollout>('GET', `/projects/${projectId}/active-rollout`),
    /** GET /api/rollouts/{id}/events?limit=N — newest first. */
    events: (rolloutId: string, limit = 50) =>
      request<{ events: RolloutEvent[] }>('GET', `/rollouts/${rolloutId}/events?limit=${limit}`),
    /** GET /api/rollouts/{id}/activity?limit=N&before_seq=N — enriched activity log. */
    activity: (rolloutId: string, limit = 200, beforeSeq?: number) => {
      const params = new URLSearchParams({ limit: String(limit) })
      if (beforeSeq !== undefined) params.set('before_seq', String(beforeSeq))
      return request<{ events: ActivityEvent[]; hasMore: boolean }>(
        'GET',
        `/rollouts/${rolloutId}/activity?${params.toString()}`,
      )
    },
    /** POST /api/rollouts/{id}/complete-item */
    completeItem: (rolloutId: string, itemId: string, outcome: string) =>
      request<unknown>('POST', `/rollouts/${rolloutId}/complete-item`, { itemId, outcome }),
    /** POST /api/rollouts/{id}/halt */
    halt: (rolloutId: string, reason: string) =>
      request<unknown>('POST', `/rollouts/${rolloutId}/halt`, { reason }),
    /** POST /api/rollouts/{id}/cancel */
    cancel: (rolloutId: string, reason: string) =>
      request<unknown>('POST', `/rollouts/${rolloutId}/cancel`, { reason }),
    /** POST /api/rollouts/{id}/dismiss — dismiss a halted rollout (no body, transitions to cancelled) */
    dismiss: (rolloutId: string) =>
      request<Rollout>('POST', `/rollouts/${rolloutId}/dismiss`),
    /** POST /api/rollouts/{id}/resume */
    resume: (rolloutId: string, answer: string) =>
      request<Rollout>('POST', `/rollouts/${rolloutId}/resume`, { answer }),
    /** POST /api/rollouts/{id}/dispatch — launch the manage agent */
    dispatchRollout: (rolloutId: string) =>
      request<Run>('POST', `/rollouts/${rolloutId}/dispatch`),
    /** GET /api/rollouts/{id}/rollout_failures — wave halts and failed runs. */
    failures: (rolloutId: string) =>
      request<RolloutFailureFeed>('GET', `/rollouts/${rolloutId}/rollout_failures`),
    /** GET /api/rollouts — list rollouts with optional filters. */
    list: (params?: { projectId?: string; status?: string; limit?: number }) => {
      const query = new URLSearchParams()
      if (params?.projectId) query.set('project_id', params.projectId)
      if (params?.status) query.set('status', params.status)
      if (params?.limit !== undefined) query.set('limit', String(params.limit))
      const qs = query.toString()
      return request<Rollout[]>('GET', `/rollouts${qs ? `?${qs}` : ''}`)
    },
    /** GET /api/rollouts/{id}/plan — latest plan with per-item progress. */
    plan: (rolloutId: string) => request<unknown>('GET', `/rollouts/${rolloutId}/plan`),
  },

  dispatch: {
    capabilities: () =>
      request<DispatchCapabilities>('GET', '/dispatch/capabilities'),
  },

  dispatchHosts: {
    list: () => request<DispatchHost[]>('GET', '/settings/dispatch/hosts'),
    add: (label: string, url: string, apiKey: string) =>
      request<DispatchHost>('POST', '/settings/dispatch/hosts', { label, url, apiKey }),
    remove: (hostId: string) => request<void>('DELETE', `/settings/dispatch/hosts/${hostId}`),
  },

  settings: {
    getDispatch: () =>
      request<{
        engine: string
        planAgentName: string
        buildAgentName: string
        defaultMaxTurns: number
        defaultTimeoutMinutes: number
        managerDefaultTimeoutMinutes: number
        serviceUrl: string
        serviceApiKeyPreview: string
      }>('GET', '/settings/dispatch'),
    updateDispatch: (data: {
      engine?: string
      planAgentName?: string
      buildAgentName?: string
      serviceUrl?: string
      serviceApiKey?: string
      defaultMaxTurns?: number
      defaultTimeoutMinutes?: number
      managerDefaultTimeoutMinutes?: number
    }) =>
      request<{
        engine: string
        planAgentName: string
        buildAgentName: string
        defaultMaxTurns: number
        defaultTimeoutMinutes: number
        managerDefaultTimeoutMinutes: number
        serviceUrl: string
        serviceApiKeyPreview: string
      }>('PATCH', '/settings/dispatch', data),
  },

  admin: {
    invites: {
      list: () => request<Invite[]>('GET', '/admin/invites'),
      create: (note: string) => request<CreatedInvite>('POST', '/admin/invites', { note }),
      revoke: (token: string) => request<void>('DELETE', `/admin/invites/${token}`),
    },
    issuePasswordReset: (userId: string) =>
      request<PasswordResetIssued>('POST', `/admin/users/${userId}/password-reset`),
    users: {
      list: () => request<AdminUser[]>('GET', '/admin/users'),
      promote: (userId: string) => request<AdminUser>('POST', `/admin/users/${userId}/promote`),
      deleteUser: (userId: string) => request<void>('DELETE', `/admin/users/${userId}`),
    },
  },

  attachments: {
    list: (itemId: string) =>
      request<AttachmentResponse[]>('GET', `/items/${itemId}/attachments`),
    upload: (itemId: string, file: File) => {
      const formData = new FormData()
      formData.append('file', file)
      return uploadRequest<AttachmentResponse>('POST', `/items/${itemId}/attachments`, formData)
    },
    /** Fetches the attachment bytes with auth and returns a blob URL for use in <img src>. */
    downloadBlobUrl: (attachmentId: string) =>
      fetchBlobUrl(`/attachments/${attachmentId}`),
    delete: (attachmentId: string) =>
      request<void>('DELETE', `/attachments/${attachmentId}`),
  },
}

export { ApiError }
