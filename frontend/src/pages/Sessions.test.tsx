import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Sessions from './Sessions'
import { api, type ChargingSessionPayload } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import { useSyncStore } from '@/stores/syncStore'

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
    source: 'manual',
    telematics_session_id: null,
    ...over,
  }
}

describe('Sessions page', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'getSettings').mockResolvedValue({})
    useSettingsStore.setState({ settings: {}, loaded: true })
    useSyncStore.setState({
      ...useSyncStore.getState(),
      recentlyImportedSessionIds: [],
    })
  })

  it('renders source badges and gradient cost', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([
      makeSession({ source: 'manual', cost_pence: 1840 }),
      makeSession({
        id: 2,
        source: 'synthesis',
        cost_pence: 0,
        location_id: 99,
      }),
    ])

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByTestId('session-row').length).toBe(2)
    })

    expect(screen.getByTestId('source-badge-manual')).toBeInTheDocument()
    expect(screen.getByTestId('source-badge-synthesis')).toBeInTheDocument()

    const costs = screen.getAllByTestId('session-cost')
    expect(costs[0]).toHaveTextContent('£18.40')
    expect(costs[1]).toHaveTextContent('£0.00')
  })

  it('groups sessions by month with totals', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([
      makeSession({ id: 1, date: '2026-05-05', cost_pence: 400 }),
      makeSession({ id: 2, date: '2026-05-01', cost_pence: 600 }),
      makeSession({ id: 3, date: '2026-04-28', cost_pence: 800 }),
    ])

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText(/May 2026/)).toBeInTheDocument()
      expect(screen.getByText(/Apr 2026/)).toBeInTheDocument()
    })

    expect(screen.getByText(/2 sessions · £10\.00/)).toBeInTheDocument()
    expect(screen.getByText(/1 session · £8\.00/)).toBeInTheDocument()
  })

  it('shows empty state when there are no sessions', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([])
    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(screen.getByText(/No sessions yet/i)).toBeInTheDocument()
    })
  })

  it('renders a "Timer · AC" mode/type hint in the row subtext', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([
      makeSession({
        id: 1,
        source: 'synthesis',
        charging_mode: 'timer',
        charging_type: 'ac',
      }),
    ])

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('session-row')).toBeInTheDocument()
    })

    expect(screen.getByText(/Timer · AC/)).toBeInTheDocument()
  })

  it('omits the mode/type hint when both are unknown', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([
      makeSession({
        id: 1,
        source: 'manual',
        charging_mode: 'unknown',
        charging_type: 'unknown',
      }),
    ])

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('session-row')).toBeInTheDocument()
    })

    expect(screen.queryByText(/Timer|Manual ·|· AC/)).not.toBeInTheDocument()
  })

  it('highlights rows whose ids are in syncStore.recentlyImportedSessionIds', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([
      makeSession({ id: 1 }),
      makeSession({ id: 2 }),
    ])
    useSyncStore.setState({
      ...useSyncStore.getState(),
      recentlyImportedSessionIds: [2],
    })

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const rows = screen.getAllByTestId('session-row')
      expect(rows).toHaveLength(2)
      expect(rows[0]).toHaveAttribute('data-highlighted', 'false')
      expect(rows[1]).toHaveAttribute('data-highlighted', 'true')
    })
  })
})
