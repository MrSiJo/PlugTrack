import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, beforeEach, vi } from 'vitest'
import CommandPalette, { useCommandPalette } from './CommandPalette'

vi.mock('@/theme', () => ({
  useTheme: () => ({ theme: 'light', setTheme: vi.fn() }),
}))

describe('CommandPalette', () => {
  beforeEach(() => {
    useCommandPalette.setState({ isOpen: false })
  })

  it('does not render dialog when closed', () => {
    render(
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('renders the navigation entries when open', () => {
    useCommandPalette.setState({ isOpen: true })
    render(
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>,
    )
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
    expect(screen.getByText('Sessions')).toBeInTheDocument()
  })

  it('opens on Cmd/Ctrl+K', () => {
    render(
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>,
    )
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    expect(useCommandPalette.getState().isOpen).toBe(true)
  })
})
