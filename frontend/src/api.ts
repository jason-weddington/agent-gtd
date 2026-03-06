import type { AuthResponse, Item, Note, Project, UserResponse } from './types'
import { toSnakeCase, toCamelCase, convertKeys } from './utils'

// --- Helpers ---

class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
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
    window.location.href = '/login'
    throw new ApiError(401, 'Unauthorized')
  }

  if (!res.ok) {
    let detail = res.statusText
    try {
      const json = await res.json()
      detail = json.detail || detail
    } catch {
      // use statusText
    }
    throw new ApiError(res.status, detail)
  }

  const json = await res.json()
  return convertKeys(json, toCamelCase) as T
}

// --- Namespaced API ---

export const api = {
  config: {
    get: () => request<{ localMode: boolean }>('GET', '/config'),
  },

  auth: {
    register: (email: string, password: string) =>
      request<AuthResponse>('POST', '/auth/register', { email, password }),
    login: (email: string, password: string) =>
      request<AuthResponse>('POST', '/auth/login', { email, password }),
    logout: () => request<void>('POST', '/auth/logout'),
    me: () => request<UserResponse>('GET', '/auth/me'),
  },

  projects: {
    list: (params?: { status?: string; area?: string }) => {
      const query = new URLSearchParams()
      if (params?.status) query.set('status', params.status)
      if (params?.area) query.set('area', params.area)
      const qs = query.toString()
      return request<Project[]>('GET', `/projects${qs ? `?${qs}` : ''}`)
    },
    create: (data: { name: string; description?: string; status?: string; area?: string }) =>
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
  },

  notes: {
    get: (id: string) => request<Note>('GET', `/notes/${id}`),
    update: (id: string, data: { title?: string; contentMarkdown?: string; labels?: string[] }) =>
      request<Note>('PATCH', `/notes/${id}`, data),
    delete: (id: string) => request<void>('DELETE', `/notes/${id}`),
  },
}

export { ApiError }
