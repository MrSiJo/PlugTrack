import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { ChargingSessionPayload } from '@/api/client'
import { SessionsTable } from './SessionsTable'

function makeSession(over: Partial<ChargingSessionPayload> = {}): ChargingSessionPayload {
  return {
    id: 1, user_id: 1, car_id: 1, plug_in_record_id: null,
    date: '2026-05-27', charge_start_at: null, charge_end_at: null,
    start_soc: 20, end_soc: 80, kwh_added: 10, kwh_calculated: null,
    odometer_at_session_km: null, charging_type: 'ac', charging_mode: 'unknown',
    battery_care: null, max_charge_current: null, actual_charge_seconds: null,
    interrupted: false, cost_pence: 250, cost_basis: 'home_rate',
    tariff_p_per_kwh: 25, cost_per_kwh_override_p: null, total_cost_pence_override: null,
    location_id: 3, location_name: 'Home', location_address: null,
    location_lat: null, location_lng: null, user_label: null, charge_network: null,
    notes: null, source: 'manual', telematics_session_id: null,
    saved_vs_petrol_p: 120, comparison_basis: 'measured', breakeven_p_per_kwh: 30,
    power_curve: null, metrics: null,
    ...over,
  }
}

describe('SessionsTable', () => {
  it('renders a row per session with cost', () => {
    render(
      <MemoryRouter>
        <SessionsTable sessions={[makeSession()]} currency="GBP" />
      </MemoryRouter>,
    )
    expect(screen.getAllByTestId('session-row')).toHaveLength(1)
    expect(screen.getByText('Home')).toBeInTheDocument()
  })

  it('renders sortable headers and fires onSort when controls provided', () => {
    const onSort = vi.fn()
    render(
      <MemoryRouter>
        <SessionsTable
          sessions={[makeSession()]}
          currency="GBP"
          sortControls={{ sort: 'date', dir: 'desc', onSort }}
        />
      </MemoryRouter>,
    )
    fireEvent.click(screen.getByRole('button', { name: /Cost/i }))
    expect(onSort).toHaveBeenCalledWith('cost')
  })

  it('renders plain headers (no sort buttons) when sortControls omitted', () => {
    render(
      <MemoryRouter>
        <SessionsTable sessions={[makeSession()]} currency="GBP" />
      </MemoryRouter>,
    )
    expect(screen.queryByRole('button', { name: /Cost/i })).toBeNull()
  })
})
