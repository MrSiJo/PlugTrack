import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import * as settingsStoreModule from '@/stores/settingsStore'
import { INTEGRATIONS } from '@/config/integrations'
import AdminPage from './AdminPage'
import type { SettingsMap } from '@/api/client'

// Mock api methods that panels call on mount
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      getOpenAiModels: vi.fn().mockRejectedValue(new Error('no key')),
      testTelegram: vi.fn(),
      getLocations: vi.fn().mockResolvedValue([]),
      getCars: vi.fn().mockResolvedValue([]),
      listMcpTokens: vi.fn().mockResolvedValue([]),
    },
  }
})

/** Minimal settings map covering every integration masterKey. */
function makeSettings(): SettingsMap {
  const entries: SettingsMap = {}

  for (const def of INTEGRATIONS) {
    entries[def.masterKey] = {
      key: def.masterKey,
      value: 'false',
      value_type: 'bool',
      group_name: 'test',
      label: `${def.label} enabled`,
      description: null,
      is_secret: false,
    }
    for (const key of def.settingKeys) {
      entries[key] = {
        key,
        value: '',
        value_type: 'string',
        group_name: 'test',
        label: key,
        description: null,
        is_secret: false,
      }
    }
  }

  return entries
}

function renderAdminPage(initialEntry = '/admin') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <AdminPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  settingsStoreModule.useSettingsStore.setState({
    settings: makeSettings(),
    loaded: true,
    loading: false,
    error: null,
    ensureLoaded: vi.fn().mockResolvedValue(undefined),
    set: vi.fn().mockResolvedValue(undefined),
  } as unknown as Parameters<typeof settingsStoreModule.useSettingsStore.setState>[0])
})

describe('AdminPage — master-detail layout', () => {
  it('renders the Administration heading', () => {
    renderAdminPage()
    expect(screen.getByRole('heading', { name: /administration/i })).toBeInTheDocument()
  })

  it('renders all 9 left-rail nav items', () => {
    renderAdminPage()
    const expectedKeys = ['cupra', 'telegram', 'ai', 'geocoding', 'preferences', 'maintenance', 'locations', 'cars', 'mcp']
    for (const key of expectedKeys) {
      expect(screen.getByTestId(`admin-nav-${key}`)).toBeInTheDocument()
    }
  })

  it('shows the cupra integration card by default (no hash)', () => {
    renderAdminPage('/admin')
    expect(screen.getByTestId('integration-cupra')).toBeInTheDocument()
  })

  it('shows the correct integration when hash is present on mount', () => {
    renderAdminPage('/admin#telegram')
    expect(screen.getByTestId('integration-telegram')).toBeInTheDocument()
    expect(screen.queryByTestId('integration-cupra')).not.toBeInTheDocument()
  })

  it('switches to telegram integration when nav item is clicked', async () => {
    const user = userEvent.setup()
    renderAdminPage()

    await user.click(screen.getByTestId('admin-nav-telegram'))

    expect(screen.getByTestId('integration-telegram')).toBeInTheDocument()
    expect(screen.queryByTestId('integration-cupra')).not.toBeInTheDocument()
  })

  it('shows only one integration card at a time', async () => {
    const user = userEvent.setup()
    renderAdminPage()

    // Default: cupra visible, others not
    expect(screen.getByTestId('integration-cupra')).toBeInTheDocument()
    expect(screen.queryByTestId('integration-telegram')).not.toBeInTheDocument()
    expect(screen.queryByTestId('integration-ai')).not.toBeInTheDocument()
    expect(screen.queryByTestId('integration-geocoding')).not.toBeInTheDocument()

    await user.click(screen.getByTestId('admin-nav-ai'))
    expect(screen.getByTestId('integration-ai')).toBeInTheDocument()
    expect(screen.queryByTestId('integration-cupra')).not.toBeInTheDocument()
  })

  it('shows PreferencesPanel when preferences nav item is clicked', async () => {
    const user = userEvent.setup()
    renderAdminPage()

    await user.click(screen.getByTestId('admin-nav-preferences'))

    expect(screen.getByTestId('preferences-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('integration-cupra')).not.toBeInTheDocument()
  })

  it('shows MaintenancePanel when maintenance nav item is clicked', async () => {
    const user = userEvent.setup()
    renderAdminPage()

    await user.click(screen.getByTestId('admin-nav-maintenance'))

    expect(screen.getByTestId('maintenance-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('preferences-panel')).not.toBeInTheDocument()
  })

  it('shows locations management when locations nav item is clicked', async () => {
    const user = userEvent.setup()
    renderAdminPage()

    await user.click(screen.getByTestId('admin-nav-locations'))

    expect(screen.getByTestId('locations-management')).toBeInTheDocument()
    expect(screen.getByTestId('admin-add-location-button')).toBeInTheDocument()
  })

  it('shows cars management when cars nav item is clicked', async () => {
    const user = userEvent.setup()
    renderAdminPage()

    await user.click(screen.getByTestId('admin-nav-cars'))

    expect(screen.getByTestId('cars-management')).toBeInTheDocument()
  })

  it('shows MCP tokens panel when mcp nav item is clicked', async () => {
    const user = userEvent.setup()
    renderAdminPage()

    await user.click(screen.getByTestId('admin-nav-mcp'))

    expect(screen.getByTestId('mcp-tokens-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('integration-cupra')).not.toBeInTheDocument()
  })

  it('falls back to cupra for an unknown hash', () => {
    renderAdminPage('/admin#nonexistent')
    expect(screen.getByTestId('integration-cupra')).toBeInTheDocument()
  })
})
