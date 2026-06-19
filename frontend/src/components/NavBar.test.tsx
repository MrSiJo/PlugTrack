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

  it('renders the four primary nav links', () => {
    render(
      <MemoryRouter>
        <NavBar />
      </MemoryRouter>,
    )
    for (const label of ['Dashboard', 'Sessions', 'Insights', 'Locations']) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    }
    // Cars, Planner, Settings removed from main nav
    expect(screen.queryByRole('link', { name: 'Cars' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Planner' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Settings' })).toBeNull()
  })

  it('renders the gear icon link to /admin', () => {
    render(
      <MemoryRouter>
        <NavBar />
      </MemoryRouter>,
    )
    const gearLink = screen.getByRole('link', { name: 'Administration' })
    expect(gearLink).toBeInTheDocument()
    expect(gearLink).toHaveAttribute('href', '/admin')
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
