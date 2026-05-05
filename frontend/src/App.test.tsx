import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as clientModule from './api/client'
import { ApiError } from './api/client'
import { useAuthStore } from './stores/authStore'
import { useSettingsStore } from './stores/settingsStore'
import App from './App'

beforeEach(() => {
  useAuthStore.setState({ user: null, loading: false, initialised: false })
  useSettingsStore.setState({ settings: {}, loaded: false, loading: false, error: null })
  // SyncStreamSubscriber pings /api/sync/status on mount; stub it to a
  // 401 so the silent-no-op branch is taken in App-routing tests.
  vi.spyOn(clientModule.api, 'getSyncStatus').mockRejectedValue(
    new ApiError(401, 'Authentication required', null),
  )
  // jsdom doesn't ship matchMedia.
  if (!window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: () => ({
        matches: false,
        addEventListener: () => {},
        removeEventListener: () => {},
      }),
    })
  }
  // Ensure routing starts at /login by default for predictable tests.
  window.history.pushState({}, '', '/')
})

describe('App bootstrap routing', () => {
  it('redirects to /setup when setup_needed=true', async () => {
    vi.spyOn(clientModule.api, 'setupStatus').mockResolvedValueOnce({
      setup_needed: true,
    })

    render(<App />)
    expect(
      await screen.findByRole('heading', { name: /^welcome$/i }),
    ).toBeInTheDocument()
  })

  it('redirects to /login when set up but not authed', async () => {
    vi.spyOn(clientModule.api, 'setupStatus').mockResolvedValueOnce({
      setup_needed: false,
    })
    vi.spyOn(clientModule.api, 'getSettings').mockRejectedValueOnce(
      new ApiError(401, 'Authentication required', null),
    )

    render(<App />)
    expect(
      await screen.findByRole('heading', { name: /^sign in$/i }),
    ).toBeInTheDocument()
  })

  it('redirects to /dashboard when authed', async () => {
    vi.spyOn(clientModule.api, 'setupStatus').mockResolvedValueOnce({
      setup_needed: false,
    })
    vi.spyOn(clientModule.api, 'getSettings').mockResolvedValue({
      theme: {
        key: 'theme',
        value: 'system',
        value_type: 'enum',
        group_name: 'display',
        label: 'Theme',
        description: null,
        is_secret: false,
      },
    } as unknown as clientModule.SettingsMap)
    vi.spyOn(clientModule.api, 'getDashboard').mockResolvedValue({
      cars: [],
      recent_sessions: [],
      lifetime_totals: { kwh: 0, cost_pence: 0, distance_km: 0, sessions_count: 0 },
      top_locations: [],
    })

    render(<App />)
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /^dashboard$/i }),
      ).toBeInTheDocument(),
    )
  })
})
