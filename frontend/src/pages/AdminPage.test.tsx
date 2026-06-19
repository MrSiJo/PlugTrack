import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import * as settingsStoreModule from '@/stores/settingsStore'
import { INTEGRATIONS } from '@/config/integrations'
import AdminPage from './AdminPage'
import type { SettingsMap } from '@/api/client'

// Mock api.getOpenAiModels so ModelSelect doesn't error in tests
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      getOpenAiModels: vi.fn().mockRejectedValue(new Error('no key')),
      testTelegram: vi.fn(),
    },
  }
})

/** Minimal settings map covering every integration masterKey. */
function makeSettings(): SettingsMap {
  const entries: SettingsMap = {}

  // Integration master keys
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
    // Stub out member setting keys so IntegrationCard renders them
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

describe('AdminPage', () => {
  it('renders the Administration heading', () => {
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>,
    )
    expect(
      screen.getByRole('heading', { name: /administration/i }),
    ).toBeInTheDocument()
  })

  it('renders one IntegrationCard per INTEGRATIONS entry', () => {
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>,
    )
    for (const def of INTEGRATIONS) {
      expect(screen.getByTestId(`integration-${def.key}`)).toBeInTheDocument()
    }
    // Confirm all four integration keys explicitly
    expect(screen.getByTestId('integration-cupra')).toBeInTheDocument()
    expect(screen.getByTestId('integration-telegram')).toBeInTheDocument()
    expect(screen.getByTestId('integration-ai')).toBeInTheDocument()
    expect(screen.getByTestId('integration-geocoding')).toBeInTheDocument()
  })

  it('renders a Preferences section', () => {
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('preferences-panel')).toBeInTheDocument()
  })

  it('renders Maintenance, Locations, and Cars section shells', () => {
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('admin-section-maintenance')).toBeInTheDocument()
    expect(screen.getByTestId('admin-section-locations')).toBeInTheDocument()
    expect(screen.getByTestId('admin-section-cars')).toBeInTheDocument()
  })

  it('renders MaintenancePanel inside the maintenance section', () => {
    render(
      <MemoryRouter>
        <AdminPage />
      </MemoryRouter>,
    )
    const section = screen.getByTestId('admin-section-maintenance')
    const panel = screen.getByTestId('maintenance-panel')
    expect(section).toContainElement(panel)
    expect(
      screen.getByText('python -m plugtrack.scripts.import_mycupra_csv'),
    ).toBeInTheDocument()
  })
})
