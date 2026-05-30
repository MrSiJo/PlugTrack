import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import SessionDetail from './SessionDetail'
import { api, type ChargingSessionPayload } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'

function makeSession(
  over: Partial<ChargingSessionPayload> = {},
): ChargingSessionPayload {
  return {
    id: 1,
    user_id: 1,
    car_id: 1,
    plug_in_record_id: null,
    date: '2026-04-12',
    charge_start_at: null,
    charge_end_at: null,
    start_soc: 20,
    end_soc: 80,
    kwh_added: 46.2,
    kwh_calculated: null,
    odometer_at_session_km: 12345,
    charging_type: 'ac',
    charging_mode: 'manual',
    battery_care: null,
    max_charge_current: null,
    interrupted: false,
    cost_pence: 347,
    cost_basis: 'home_rate',
    tariff_p_per_kwh: 7.5,
    cost_per_kwh_override_p: null,
    total_cost_pence_override: null,
    location_id: null,
    location_name: null,
    location_address: null,
    location_lat: null,
    location_lng: null,
    user_label: null,
    charge_network: null,
    notes: null,
    source: 'synthesis',
    telematics_session_id: null,
    power_curve: null,
    metrics: null,
    ...over,
  }
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/sessions/1']}>
      <Routes>
        <Route path="/sessions/:id" element={<SessionDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SessionDetail — charge context', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
  })

  it('renders a Charge context section with mode/type/battery-care/max-current', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        charging_mode: 'timer',
        charging_type: 'ac',
        battery_care: true,
        max_charge_current: 'maximum',
      }),
    )

    renderDetail()

    const section = await screen.findByTestId('charge-context')
    expect(section).toHaveTextContent('Charge context')
    expect(section).toHaveTextContent('Timer')
    expect(section).toHaveTextContent('AC')
    expect(section).toHaveTextContent('Battery care')
    expect(section).toHaveTextContent('Maximum')
  })

  it('omits the Charge context section when nothing useful is known', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        charging_mode: 'unknown',
        charging_type: 'unknown',
        battery_care: null,
        max_charge_current: null,
      }),
    )

    renderDetail()

    await waitFor(() => {
      expect(screen.getByTestId('toggle-edit')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('charge-context')).not.toBeInTheDocument()
  })

  it('edit form has battery-care and max-current inputs and submits them', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        charging_mode: 'timer',
        charging_type: 'ac',
        battery_care: false,
        max_charge_current: 'reduced',
      }),
    )
    const updateSpy = vi
      .spyOn(api, 'updateSession')
      .mockResolvedValue(makeSession())

    const user = (await import('@testing-library/user-event')).default.setup()
    renderDetail()

    await screen.findByTestId('toggle-edit')
    await user.click(screen.getByTestId('toggle-edit'))

    const careInput = screen.getByTestId('edit-battery-care') as HTMLInputElement
    const currentInput = screen.getByTestId(
      'edit-max-charge-current',
    ) as HTMLSelectElement
    expect(careInput.checked).toBe(false)
    expect(currentInput.value).toBe('reduced')

    await user.click(careInput)
    await user.click(screen.getByTestId('edit-save'))

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalled()
    })
    const body = updateSpy.mock.calls[0]![1]
    expect(body.battery_care).toBe(true)
    expect(body.max_charge_current).toBe('reduced')
  })
})
