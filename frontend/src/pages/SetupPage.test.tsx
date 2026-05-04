import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as clientModule from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import SetupPage from './SetupPage'

beforeEach(() => {
  useAuthStore.setState({ user: null, loading: false, initialised: false })
})

describe('SetupPage', () => {
  it('submits username + password and creates the user', async () => {
    const setupSpy = vi.spyOn(clientModule.api, 'setup').mockResolvedValueOnce({
      user_id: 1,
      username: 'admin',
    })
    const loginSpy = vi.spyOn(clientModule.api, 'login').mockResolvedValueOnce({
      user_id: 1,
      username: 'admin',
    })

    render(
      <MemoryRouter>
        <SetupPage />
      </MemoryRouter>,
    )
    await userEvent.type(screen.getByLabelText(/username/i), 'admin')
    await userEvent.type(
      screen.getByLabelText(/password/i),
      'super-strong-pass',
    )
    await userEvent.click(screen.getByRole('button', { name: /create account/i }))

    expect(setupSpy).toHaveBeenCalledWith({
      username: 'admin',
      password: 'super-strong-pass',
    })
    expect(loginSpy).toHaveBeenCalled()
  })
})
