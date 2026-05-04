import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { useSyncStore } from '@/stores/syncStore'
import AuthFailureBanner from './AuthFailureBanner'

describe('AuthFailureBanner', () => {
  beforeEach(() => {
    useSyncStore.setState({ lastErrorByCarId: {} })
  })
  afterEach(() => {
    useSyncStore.setState({ lastErrorByCarId: {} })
  })

  it('does not render when no auth errors are present', () => {
    render(
      <MemoryRouter>
        <AuthFailureBanner />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('auth-failure-banner')).not.toBeInTheDocument()
  })

  it('does not render when only non-auth errors are present', () => {
    useSyncStore.setState({ lastErrorByCarId: { 1: 'network' } })
    render(
      <MemoryRouter>
        <AuthFailureBanner />
      </MemoryRouter>,
    )
    expect(screen.queryByTestId('auth-failure-banner')).not.toBeInTheDocument()
  })

  it('renders when at least one car has credentials_invalid', () => {
    useSyncStore.setState({ lastErrorByCarId: { 7: 'credentials_invalid' } })
    render(
      <MemoryRouter>
        <AuthFailureBanner />
      </MemoryRouter>,
    )
    const banner = screen.getByTestId('auth-failure-banner')
    expect(banner).toBeInTheDocument()
    expect(banner).toHaveTextContent(/Cupra Connect credentials invalid/i)
    expect(banner).toHaveTextContent(/car #7/)
    expect(screen.getByTestId('auth-failure-open-settings')).toBeInTheDocument()
  })

  it('summarises when multiple cars are failing', () => {
    useSyncStore.setState({
      lastErrorByCarId: {
        1: 'credentials_invalid',
        2: 'credentials_invalid',
      },
    })
    render(
      <MemoryRouter>
        <AuthFailureBanner />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('auth-failure-banner')).toHaveTextContent(/2 cars/)
  })
})
