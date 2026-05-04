import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as clientModule from '@/api/client'
import { ApiError } from '@/api/client'
import { useAuthStore } from './authStore'

describe('authStore', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, loading: false, initialised: false })
  })

  it('login() sets user on success', async () => {
    vi.spyOn(clientModule.api, 'login').mockResolvedValueOnce({
      user_id: 1,
      username: 'admin',
    })

    const user = await useAuthStore.getState().login({
      username: 'admin',
      password: 'pw',
    })

    expect(user.username).toBe('admin')
    expect(useAuthStore.getState().user).toEqual({ username: 'admin' })
  })

  it('bootstrap() with valid session marks user logged in', async () => {
    vi.spyOn(clientModule.api, 'getSettings').mockResolvedValueOnce({})

    await useAuthStore.getState().bootstrap()

    const state = useAuthStore.getState()
    expect(state.initialised).toBe(true)
    expect(state.user).not.toBeNull()
  })

  it('bootstrap() with 401 leaves user null', async () => {
    vi.spyOn(clientModule.api, 'getSettings').mockRejectedValueOnce(
      new ApiError(401, 'Authentication required', { detail: 'Authentication required' }),
    )

    await useAuthStore.getState().bootstrap()

    const state = useAuthStore.getState()
    expect(state.initialised).toBe(true)
    expect(state.user).toBeNull()
  })

  it('logout() clears user', async () => {
    useAuthStore.setState({ user: { username: 'admin' } })
    vi.spyOn(clientModule.api, 'logout').mockResolvedValueOnce({ ok: true })

    await useAuthStore.getState().logout()

    expect(useAuthStore.getState().user).toBeNull()
  })
})
