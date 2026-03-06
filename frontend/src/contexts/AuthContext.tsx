import { createContext, useContext, useState, useCallback, useMemo, useEffect, type ReactNode } from 'react'
import { api } from '../api'
import type { UserResponse } from '../types'

interface AuthContextValue {
  isAuthenticated: boolean
  user: UserResponse | null
  loading: boolean
  localMode: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(() => {
    try {
      const raw = localStorage.getItem('agent_gtd-user')
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  })
  const [loading, setLoading] = useState(true)
  const [localMode, setLocalMode] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function init() {
      try {
        const config = await api.config.get()
        if (cancelled) return

        if (config.localMode) {
          setLocalMode(true)
          // In local mode, fetch user without token (dependency override on backend)
          const u = await api.auth.me()
          if (cancelled) return
          setUser(u)
        } else {
          // Normal auth flow
          const token = localStorage.getItem('agent_gtd-token')
          if (token) {
            const u = await api.auth.me()
            if (cancelled) return
            setUser(u)
            localStorage.setItem('agent_gtd-user', JSON.stringify(u))
          }
        }
      } catch {
        if (cancelled) return
        localStorage.removeItem('agent_gtd-token')
        localStorage.removeItem('agent_gtd-user')
        setUser(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    init()
    return () => { cancelled = true }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.auth.login(email, password)
    localStorage.setItem('agent_gtd-token', res.token)
    localStorage.setItem('agent_gtd-user', JSON.stringify(res.user))
    setUser(res.user)
  }, [])

  const register = useCallback(async (email: string, password: string) => {
    const res = await api.auth.register(email, password)
    localStorage.setItem('agent_gtd-token', res.token)
    localStorage.setItem('agent_gtd-user', JSON.stringify(res.user))
    setUser(res.user)
  }, [])

  const logout = useCallback(() => {
    api.auth.logout().catch(() => {})
    localStorage.removeItem('agent_gtd-token')
    localStorage.removeItem('agent_gtd-user')
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({
      isAuthenticated: user !== null,
      user,
      loading,
      localMode,
      login,
      register,
      logout,
    }),
    [user, loading, localMode, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
