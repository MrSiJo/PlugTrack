import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as clientModule from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import SettingsPage from './SettingsPage'

const sample: clientModule.SettingsMap = {
  theme: {
    key: 'theme',
    value: 'system',
    value_type: 'enum',
    group_name: 'display',
    label: 'Theme',
    description: 'UI theme',
    is_secret: false,
  },
  distance_unit: {
    key: 'distance_unit',
    value: 'mi',
    value_type: 'enum',
    group_name: 'display',
    label: 'Distance unit',
    description: null,
    is_secret: false,
  },
  default_home_rate_p_per_kwh: {
    key: 'default_home_rate_p_per_kwh',
    value: '7.5',
    value_type: 'float',
    group_name: 'cost',
    label: 'Home rate',
    description: null,
    is_secret: false,
  },
  cupra_password: {
    key: 'cupra_password',
    value: '***',
    value_type: 'string',
    group_name: 'cupra_connect',
    label: 'Cupra password',
    description: null,
    is_secret: true,
  },
  sync_interval_minutes_idle: {
    key: 'sync_interval_minutes_idle',
    value: '30',
    value_type: 'int',
    group_name: 'sync',
    label: 'Idle sync interval',
    description: null,
    is_secret: false,
  },
}

/** Minimal SyncStatusResponse factory */
function makeSyncStatus(
  overrides: Partial<clientModule.SyncStatusResponse> = {},
): clientModule.SyncStatusResponse {
  return {
    cars: {},
    requests_today: 0,
    request_budget: 800,
    quota_state: 'ok',
    ...overrides,
  }
}

/** Render helper — navigates to the Sync tab so SyncControlsPanel is visible */
async function renderAndOpenSyncTab() {
  render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  )
  await userEvent.click(screen.getByTestId('settings-tab-sync'))
}

beforeEach(() => {
  useSettingsStore.setState({
    settings: sample,
    loaded: true,
    loading: false,
    error: null,
  })
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
})

describe('SettingsPage', () => {
  it('renders settings grouped into tabs by group_name', async () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: /^settings$/i })).toBeInTheDocument()

    // Default tab is the first in groupOrder = cupra_connect.
    expect(screen.getByText('Cupra password')).toBeInTheDocument()
    expect(screen.getByText(/\*\*\*/)).toBeInTheDocument()
    // Other groups not visible until their tab is clicked.
    expect(screen.queryByText('Distance unit')).not.toBeInTheDocument()

    await userEvent.click(screen.getByTestId('settings-tab-display'))
    expect(screen.getByText('Distance unit')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('settings-tab-cost'))
    expect(screen.getByText('Home rate')).toBeInTheDocument()
  })

  describe('Clear cached Cupra tokens button', () => {
    beforeEach(() => {
      vi.restoreAllMocks()
    })
    afterEach(() => {
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
    })

    it('POSTs to clearPycupraTokens after the user confirms', async () => {
      const clearSpy = vi
        .spyOn(clientModule.api, 'clearPycupraTokens')
        .mockResolvedValue({ cleared: true, count: 3 })
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

      render(
        <MemoryRouter>
          <SettingsPage />
        </MemoryRouter>,
      )

      await userEvent.click(screen.getByTestId('clear-pycupra-tokens-button'))
      expect(confirmSpy).toHaveBeenCalled()
      expect(clearSpy).toHaveBeenCalled()

      await waitFor(() => {
        expect(screen.getByTestId('clear-pycupra-tokens-toast')).toHaveTextContent(
          /Tokens cleared/i,
        )
      })
    })

    it('does NOT POST when the user cancels the confirm', async () => {
      const clearSpy = vi
        .spyOn(clientModule.api, 'clearPycupraTokens')
        .mockResolvedValue({ cleared: false, count: 0 })
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

      render(
        <MemoryRouter>
          <SettingsPage />
        </MemoryRouter>,
      )

      await userEvent.click(screen.getByTestId('clear-pycupra-tokens-button'))
      expect(confirmSpy).toHaveBeenCalled()
      expect(clearSpy).not.toHaveBeenCalled()
    })
  })

  it('PUTs setting on Save click', async () => {
    const putSpy = vi
      .spyOn(clientModule.api, 'putSetting')
      .mockResolvedValue({ key: 'distance_unit', status: 'updated' })
    vi.spyOn(clientModule.api, 'getSettings').mockResolvedValue(sample)

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    )

    // Switch to the display tab to expose the distance_unit control.
    await userEvent.click(screen.getByTestId('settings-tab-display'))

    const select = screen.getByLabelText(/^distance unit$/i)
    await userEvent.selectOptions(select, 'km')

    // Find the Save button in the same row as Distance unit. Saves
    // are per-row buttons; the simplest approach is to grab them all.
    const saveButtons = screen.getAllByRole('button', { name: /^save$/i })
    // Distance unit is the second entry alphabetically in display group
    // (Distance unit, Theme). cost group renders first by groupOrder.
    // Click the first matching save and verify the API received our key.
    for (const btn of saveButtons) {
      await userEvent.click(btn)
    }

    expect(putSpy).toHaveBeenCalledWith('distance_unit', 'km')
  })

  describe('Quota indicator', () => {
    beforeEach(() => {
      vi.restoreAllMocks()
      vi.spyOn(clientModule.api, 'getCars').mockResolvedValue([])
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('renders API calls today N / M text from sync status', async () => {
      vi.spyOn(clientModule.api, 'getSyncStatus').mockResolvedValue(
        makeSyncStatus({ requests_today: 350, request_budget: 800, quota_state: 'ok' }),
      )

      await renderAndOpenSyncTab()

      await waitFor(() => {
        expect(screen.getByTestId('quota-indicator')).toBeInTheDocument()
      })
      expect(screen.getByTestId('quota-indicator')).toHaveTextContent('API calls today: 350 / 800')
    })

    it('applies neutral styling when quota_state is ok', async () => {
      vi.spyOn(clientModule.api, 'getSyncStatus').mockResolvedValue(
        makeSyncStatus({ requests_today: 100, request_budget: 800, quota_state: 'ok' }),
      )

      await renderAndOpenSyncTab()

      await waitFor(() => {
        expect(screen.getByTestId('quota-indicator')).toBeInTheDocument()
      })

      const indicator = screen.getByTestId('quota-indicator')
      // Label uses neutral slate colour
      const label = indicator.querySelector('.text-slate-500')
      expect(label).not.toBeNull()
      // Bar uses neutral slate colour
      const bar = indicator.querySelector('.bg-slate-400')
      expect(bar).not.toBeNull()
      // No paused note
      expect(indicator).not.toHaveTextContent(/paused until tomorrow/)
    })

    it('applies amber styling when quota_state is stretching', async () => {
      vi.spyOn(clientModule.api, 'getSyncStatus').mockResolvedValue(
        makeSyncStatus({ requests_today: 640, request_budget: 800, quota_state: 'stretching' }),
      )

      await renderAndOpenSyncTab()

      await waitFor(() => {
        expect(screen.getByTestId('quota-indicator')).toBeInTheDocument()
      })

      const indicator = screen.getByTestId('quota-indicator')
      expect(indicator).toHaveTextContent('API calls today: 640 / 800')
      // Label uses amber colour
      const label = indicator.querySelector('.text-amber-600')
      expect(label).not.toBeNull()
      // Bar uses amber colour
      const bar = indicator.querySelector('.bg-amber-400')
      expect(bar).not.toBeNull()
      // No paused note
      expect(indicator).not.toHaveTextContent(/paused until tomorrow/)
    })

    it('applies red styling and shows paused note when quota_state is paused', async () => {
      vi.spyOn(clientModule.api, 'getSyncStatus').mockResolvedValue(
        makeSyncStatus({ requests_today: 800, request_budget: 800, quota_state: 'paused' }),
      )

      await renderAndOpenSyncTab()

      await waitFor(() => {
        expect(screen.getByTestId('quota-indicator')).toBeInTheDocument()
      })

      const indicator = screen.getByTestId('quota-indicator')
      expect(indicator).toHaveTextContent('API calls today: 800 / 800')
      // Label uses red colour
      const label = indicator.querySelector('.text-red-600')
      expect(label).not.toBeNull()
      // Bar uses red colour
      const bar = indicator.querySelector('.bg-red-500')
      expect(bar).not.toBeNull()
      // Paused note is shown
      expect(indicator).toHaveTextContent(/paused until tomorrow to protect the shared Cupra quota/)
    })

    it('does not render the quota indicator while loading', () => {
      // getSyncStatus never resolves during this test
      vi.spyOn(clientModule.api, 'getSyncStatus').mockReturnValue(new Promise(() => {}))

      render(
        <MemoryRouter>
          <SettingsPage />
        </MemoryRouter>,
      )

      // Don't wait — indicator must not be present while loading
      expect(screen.queryByTestId('quota-indicator')).not.toBeInTheDocument()
    })
  })

  describe('Wake car button removed', () => {
    beforeEach(() => {
      vi.restoreAllMocks()
      vi.spyOn(clientModule.api, 'getCars').mockResolvedValue([
        {
          id: 1,
          make: 'Cupra',
          model: 'Born',
          vin: null,
          battery_kwh: 58,
          nominal_efficiency_mi_per_kwh: 3.5,
          provider: 'cupra_connect',
          provider_vehicle_id: 'VIN001',
          active: true,
        },
      ])
      vi.spyOn(clientModule.api, 'getSyncStatus').mockResolvedValue(
        makeSyncStatus({ requests_today: 100, request_budget: 800, quota_state: 'ok' }),
      )
    })

    afterEach(() => {
      vi.restoreAllMocks()
    })

    it('does not render a Wake car button on the sync tab', async () => {
      await renderAndOpenSyncTab()

      await waitFor(() => {
        // The force sync button is present (confirms cars loaded)
        expect(screen.getByTestId('settings-force-sync-1')).toBeInTheDocument()
      })

      expect(screen.queryByRole('button', { name: /wake/i })).not.toBeInTheDocument()
    })
  })
})
