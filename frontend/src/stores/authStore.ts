/**
 * Auth store.
 *
 * The "session" is the signed `plugtrack_session` HttpOnly cookie that
 * the backend sets on /api/auth/login. There is no token in JS-land —
 * presence of a valid cookie is detected by attempting an authenticated
 * call (`api.getSettings()`), which returns 200 if we're logged in.
 *
 * No localStorage. No persistence. The cookie IS the session.
 */
import { create } from 'zustand'
import { ApiError, api, type LoginRequest } from '@/api/client'

export interface AuthUser {
  username: string
}

export interface AuthState {
  user: AuthUser | null
  loading: boolean
  initialised: boolean
  bootstrap: () => Promise<void>
  login: (creds: LoginRequest) => Promise<AuthUser>
  logout: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  loading: false,
  initialised: false,

  /**
   * Probe the session by calling getSettings(). 200 → logged in.
   * 401 → not logged in. Any other error rethrown so callers can
   * decide what to do.
   */
  bootstrap: async () => {
    set({ loading: true })
    try {
      await api.getSettings()
      // We don't know the username here (backend doesn't expose it on
      // /api/settings). Use a placeholder; pages can show "logged in"
      // without needing the literal username.
      set({ user: { username: '' }, loading: false, initialised: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        set({ user: null, loading: false, initialised: true })
        return
      }
      set({ loading: false, initialised: true })
      throw err
    }
  },

  login: async (creds) => {
    const result = await api.login(creds)
    const user: AuthUser = { username: result.username }
    set({ user })
    return user
  },

  logout: async () => {
    try {
      await api.logout()
    } finally {
      set({ user: null })
    }
  },
}))
