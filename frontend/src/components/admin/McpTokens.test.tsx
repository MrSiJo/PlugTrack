/**
 * Tests for McpTokens admin panel (TDD — written before the component).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { api } from '@/api/client'

// Mock the api module
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      listMcpTokens: vi.fn(),
      createMcpToken: vi.fn(),
      revokeMcpToken: vi.fn(),
    },
  }
})

// Lazy import after mock is set up
const { McpTokens } = await import('./McpTokens')

const MOCK_TOKEN_ROW = {
  id: 1,
  name: 'Claude Desktop',
  scope: 'readwrite',
  created_at: '2026-06-20T10:00:00Z',
  last_used_at: null,
}

const MOCK_TOKEN_ROW_2 = {
  id: 2,
  name: 'Read Only Client',
  scope: 'read',
  created_at: '2026-06-20T11:00:00Z',
  last_used_at: '2026-06-20T12:00:00Z',
}

describe('McpTokens', () => {
  beforeEach(() => {
    vi.mocked(api.listMcpTokens).mockResolvedValue([])
    vi.mocked(api.createMcpToken).mockResolvedValue({
      id: 99,
      name: 'New Token',
      scope: 'read',
      created_at: '2026-06-20T10:00:00Z',
      token: 'plaintext-token-value-abc123',
    })
    vi.mocked(api.revokeMcpToken).mockResolvedValue(undefined)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  it('renders the panel with the mcp-tokens-panel testid', async () => {
    render(<McpTokens />)
    expect(screen.getByTestId('mcp-tokens-panel')).toBeInTheDocument()
  })

  it('renders the create form with name input and scope select', async () => {
    render(<McpTokens />)
    expect(screen.getByTestId('mcp-token-create')).toBeInTheDocument()
    expect(screen.getByTestId('mcp-token-name')).toBeInTheDocument()
    expect(screen.getByTestId('mcp-token-scope')).toBeInTheDocument()
  })

  it('renders an empty state when no tokens exist', async () => {
    vi.mocked(api.listMcpTokens).mockResolvedValue([])
    render(<McpTokens />)
    await waitFor(() => {
      expect(vi.mocked(api.listMcpTokens)).toHaveBeenCalledOnce()
    })
    // No token rows rendered
    expect(screen.queryByTestId(`mcp-token-revoke-1`)).not.toBeInTheDocument()
  })

  it('lists existing tokens without exposing secret fields', async () => {
    vi.mocked(api.listMcpTokens).mockResolvedValue([MOCK_TOKEN_ROW, MOCK_TOKEN_ROW_2])
    render(<McpTokens />)

    await waitFor(() => {
      expect(screen.getByText('Claude Desktop')).toBeInTheDocument()
    })

    expect(screen.getByText('Read Only Client')).toBeInTheDocument()
    // Revoke buttons per row
    expect(screen.getByTestId('mcp-token-revoke-1')).toBeInTheDocument()
    expect(screen.getByTestId('mcp-token-revoke-2')).toBeInTheDocument()
    // No secret values rendered
    expect(screen.queryByText('plaintext')).not.toBeInTheDocument()
    expect(screen.queryByText('token_hash')).not.toBeInTheDocument()
  })

  // ---------------------------------------------------------------------------
  // Create flow
  // ---------------------------------------------------------------------------

  it('calls createMcpToken with name and scope on form submit', async () => {
    const user = userEvent.setup()
    render(<McpTokens />)

    const nameInput = screen.getByTestId('mcp-token-name')
    const scopeSelect = screen.getByTestId('mcp-token-scope')
    const submitBtn = within(screen.getByTestId('mcp-token-create')).getByRole('button', { name: /create/i })

    await user.type(nameInput, 'My Client')
    await user.selectOptions(scopeSelect, 'readwrite')
    await user.click(submitBtn)

    await waitFor(() => {
      expect(vi.mocked(api.createMcpToken)).toHaveBeenCalledWith('My Client', 'readwrite')
    })
  })

  it('shows the plaintext token once after creation with a store-it-now warning', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createMcpToken).mockResolvedValue({
      id: 99,
      name: 'My Client',
      scope: 'readwrite',
      created_at: '2026-06-20T10:00:00Z',
      token: 'plaintext-token-value-abc123',
    })
    render(<McpTokens />)

    const nameInput = screen.getByTestId('mcp-token-name')
    const submitBtn = within(screen.getByTestId('mcp-token-create')).getByRole('button', { name: /create/i })

    await user.type(nameInput, 'My Client')
    await user.click(submitBtn)

    await waitFor(() => {
      expect(screen.getByTestId('mcp-token-new-value')).toBeInTheDocument()
    })
    expect(screen.getByTestId('mcp-token-new-value')).toHaveTextContent('plaintext-token-value-abc123')
    // Warning text about one-time display
    expect(screen.getByText(/store this token now/i)).toBeInTheDocument()
  })

  it('refreshes the token list after creation', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listMcpTokens)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ id: 99, name: 'My Client', scope: 'readwrite', created_at: '2026-06-20T10:00:00Z', last_used_at: null }])

    render(<McpTokens />)
    const nameInput = screen.getByTestId('mcp-token-name')
    const submitBtn = within(screen.getByTestId('mcp-token-create')).getByRole('button', { name: /create/i })

    await user.type(nameInput, 'My Client')
    await user.click(submitBtn)

    await waitFor(() => {
      expect(vi.mocked(api.listMcpTokens)).toHaveBeenCalledTimes(2)
    })
  })

  // ---------------------------------------------------------------------------
  // Revoke flow
  // ---------------------------------------------------------------------------

  it('calls revokeMcpToken with the token id on revoke click', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listMcpTokens).mockResolvedValue([MOCK_TOKEN_ROW])
    render(<McpTokens />)

    await waitFor(() => {
      expect(screen.getByTestId('mcp-token-revoke-1')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('mcp-token-revoke-1'))

    await waitFor(() => {
      expect(vi.mocked(api.revokeMcpToken)).toHaveBeenCalledWith(1)
    })
  })

  it('refreshes the token list after revoke', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listMcpTokens)
      .mockResolvedValueOnce([MOCK_TOKEN_ROW])
      .mockResolvedValueOnce([])

    render(<McpTokens />)

    await waitFor(() => {
      expect(screen.getByTestId('mcp-token-revoke-1')).toBeInTheDocument()
    })

    await user.click(screen.getByTestId('mcp-token-revoke-1'))

    await waitFor(() => {
      expect(vi.mocked(api.listMcpTokens)).toHaveBeenCalledTimes(2)
    })
  })
})

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function within(el: HTMLElement) {
  return {
    getByRole: (role: string, opts?: { name: RegExp | string }) => {
      const buttons = el.querySelectorAll(`[role="${role}"], ${role}`)
      if (opts?.name) {
        const nameRe = opts.name instanceof RegExp ? opts.name : new RegExp(opts.name, 'i')
        for (const btn of Array.from(buttons)) {
          if (nameRe.test((btn as HTMLElement).textContent ?? '')) {
            return btn as HTMLElement
          }
        }
        // Fallback: search by accessible name using the full text match in the element
        const allButtons = el.querySelectorAll('button')
        for (const btn of Array.from(allButtons)) {
          if (nameRe.test(btn.textContent ?? '')) {
            return btn as HTMLElement
          }
        }
      }
      return buttons[0] as HTMLElement
    },
  }
}
