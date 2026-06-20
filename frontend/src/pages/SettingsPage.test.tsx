import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
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

    // Default tab is the first present group in groupOrder = cost.
    expect(screen.getByText('Home rate')).toBeInTheDocument()
    // Other groups not visible until their tab is clicked.
    expect(screen.queryByText('Distance unit')).not.toBeInTheDocument()

    await userEvent.click(screen.getByTestId('settings-tab-display'))
    expect(screen.getByText('Distance unit')).toBeInTheDocument()
    expect(screen.getByText('Theme')).toBeInTheDocument()
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
})
