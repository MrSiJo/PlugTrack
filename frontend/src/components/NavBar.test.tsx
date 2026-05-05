import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import NavBar from './NavBar'

vi.mock('@/stores/authStore', () => ({
  useAuthStore: (sel: (s: { logout: () => void }) => unknown) =>
    sel({ logout: vi.fn() }),
}))

describe('NavBar', () => {
  it('renders gradient PlugTrack wordmark', () => {
    render(
      <MemoryRouter>
        <NavBar />
      </MemoryRouter>,
    )
    const logo = screen.getByText(/PlugTrack/)
    expect(logo.className).toMatch(/text-gradient-electric/)
  })

  it('renders all five primary links', () => {
    render(
      <MemoryRouter>
        <NavBar />
      </MemoryRouter>,
    )
    for (const label of [
      'Dashboard',
      'Cars',
      'Sessions',
      'Locations',
      'Settings',
    ]) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    }
  })

  it('exposes a command-palette trigger button', () => {
    render(
      <MemoryRouter>
        <NavBar />
      </MemoryRouter>,
    )
    expect(
      screen.getByRole('button', { name: /search/i }),
    ).toBeInTheDocument()
  })
})
