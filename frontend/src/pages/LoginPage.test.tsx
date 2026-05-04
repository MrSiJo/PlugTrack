import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as clientModule from '@/api/client'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import LoginPage from './LoginPage'

beforeEach(() => {
  useAuthStore.setState({ user: null, loading: false, initialised: false })
})

describe('LoginPage', () => {
  it('logs in and updates auth store', async () => {
    const loginSpy = vi.spyOn(clientModule.api, 'login').mockResolvedValueOnce({
      user_id: 1,
      username: 'admin',
    })

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )
    await userEvent.type(screen.getByLabelText(/username/i), 'admin')
    await userEvent.type(screen.getByLabelText(/password/i), 'pw1234567890')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(loginSpy).toHaveBeenCalledWith({
      username: 'admin',
      password: 'pw1234567890',
    })
    expect(useAuthStore.getState().user).toEqual({ username: 'admin' })
  })

  it('shows error message on 401', async () => {
    vi.spyOn(clientModule.api, 'login').mockRejectedValueOnce(
      new ApiError(401, 'invalid credentials', null),
    )

    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    )
    await userEvent.type(screen.getByLabelText(/username/i), 'wrong')
    await userEvent.type(screen.getByLabelText(/password/i), 'wrongpassword')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid/i)
  })
})
