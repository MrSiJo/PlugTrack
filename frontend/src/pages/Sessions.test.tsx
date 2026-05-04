import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Sessions from './Sessions'
import { api, type ChargingSessionPayload } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import { useSyncStore } from '@/stores/syncStore'

function makeSession(over: Partial<ChargingSessionPayload> = {}): ChargingSessionPayload {
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
    odometer_at_session_km: 12345,
    charging_type: 'ac',
    charging_mode: 'manual',
    interrupted: false,
    cost_pence: 347,
    cost_basis: 'home_rate',
    tariff_p_per_kwh: 7.5,
    cost_per_kwh_override_p: null,
    total_cost_pence_override: null,
    location_id: null,
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
    // Mock /api/settings so the useDistanceUnit hook's ensureLoaded
    // doesn't throw "Invalid URL" in the jsdom env.
    vi.spyOn(api, 'getSettings').mockResolvedValue({})
    // Reset settings so distance unit defaults to 'mi'.
    useSettingsStore.setState({ settings: {}, loaded: true })
  })

  it('renders source badge, distance, location pill, cost pill', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([
      makeSession({ source: 'manual', cost_basis: 'override_total', cost_pence: 1840 }),
      makeSession({
        id: 2,
        source: 'synthesis',
        cost_basis: 'location_free',
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

    // Source badges (one per session).
    expect(screen.getByTestId('source-badge-manual')).toBeInTheDocument()
    expect(screen.getByTestId('source-badge-synthesis')).toBeInTheDocument()

    // Cost pills colour-coded by basis.
    expect(screen.getByTestId('cost-pill-override_total')).toHaveTextContent('£18.40')
    expect(screen.getByTestId('cost-pill-location_free')).toHaveTextContent('£0.00')

    // Distance — default 'mi' unit. 12345 km ≈ 7671 mi
    const distances = screen.getAllByTestId('distance')
    expect(distances[0]).toHaveTextContent('mi')

    // Location pill — first row has no location, second is unlabelled.
    const pills = screen.getAllByTestId('location-pill')
    expect(pills[0]).toHaveTextContent('No location')
    expect(pills[1]).toHaveTextContent(/Unlabelled/)
  })

  it('renders distance in km when distance_unit setting is km', async () => {
    useSettingsStore.setState({
      settings: {
        distance_unit: {
          key: 'distance_unit',
          value: 'km',
          value_type: 'enum',
          group_name: 'display',
          label: 'Distance unit',
          description: null,
          is_secret: false,
        },
      },
      loaded: true,
    })

    vi.spyOn(api, 'getSessions').mockResolvedValue([makeSession()])

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      const dist = screen.getByTestId('distance')
      expect(dist).toHaveTextContent(/km/)
      expect(dist).toHaveTextContent('12345')
    })
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

  it('Force-sync button calls api.syncCar and starts a stream', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([])
    const syncSpy = vi.spyOn(api, 'syncCar').mockResolvedValue({
      job_id: 'abc',
      stream_url: '/api/sync/stream/abc',
      kind: 'force',
      status: 'running',
    })

    // Mock EventSource so startStream doesn't throw.
    class MockEventSource {
      url: string
      addEventListener = vi.fn()
      close = vi.fn()
      constructor(url: string) {
        this.url = url
      }
    }
    vi.stubGlobal('EventSource', MockEventSource)

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('force-sync-button')).toBeInTheDocument()
    })

    await act(async () => {
      fireEvent.click(screen.getByTestId('force-sync-button'))
    })

    expect(syncSpy).toHaveBeenCalledWith(1)
    vi.unstubAllGlobals()
  })
})
