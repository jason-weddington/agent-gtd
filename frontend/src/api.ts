import type { AuthResponse, Note, UserResponse } from './types'
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
  auth: {
    register: (email: string, password: string) =>
      request<AuthResponse>('POST', '/auth/register', { email, password }),
    login: (email: string, password: string) =>
      request<AuthResponse>('POST', '/auth/login', { email, password }),
    logout: () => request<void>('POST', '/auth/logout'),
    me: () => request<UserResponse>('GET', '/auth/me'),
  },

  notes: {
    list: () => request<Note[]>('GET', '/notes'),
    create: (data: { title?: string; content?: string; tags?: string[] }) =>
      request<Note>('POST', '/notes', data),
    get: (id: string) => request<Note>('GET', `/notes/${id}`),
    update: (id: string, data: { title?: string; content?: string; tags?: string[] }) =>
      request<Note>('PATCH', `/notes/${id}`, data),
    delete: (id: string) => request<void>('DELETE', `/notes/${id}`),
  },
}

export { ApiError }
