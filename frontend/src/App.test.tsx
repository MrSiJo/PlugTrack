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
      await screen.findByRole('heading', { name: /welcome to plugtrack/i }),
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
      await screen.findByRole('heading', { name: /sign in to plugtrack/i }),
    ).toBeInTheDocument()
  })

  it('redirects to /settings when authed', async () => {
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

    render(<App />)
    await waitFor(() =>
      expect(
        screen.getByRole('heading', { name: /^settings$/i }),
      ).toBeInTheDocument(),
    )
  })
})
