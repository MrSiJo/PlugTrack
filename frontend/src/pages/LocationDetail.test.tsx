import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { api, type LocationListPayload } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import LocationDetail from './LocationDetail'

function makeLocation(over: Partial<LocationListPayload> = {}): LocationListPayload {
  return {
    id: 5, name: 'Home', centroid_lat: 51.5, centroid_lng: -0.12, radius_m: 100,
    is_home: true, is_free: false, default_cost_per_kwh_p: 7.5,
    default_charge_network: null, address: null,
    visit_count: 10, total_kwh: 200, total_cost_pence: 1500,
    last_visited_at: '2026-06-01T10:00:00+00:00', ...over,
  }
}

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/locations/${id}`]}>
      <Routes>
        <Route path="/locations/:id" element={<LocationDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('LocationDetail page', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
  })
  afterEach(() => vi.restoreAllMocks())

  it('renders the stats header + session list + edit form', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([makeLocation()])
    vi.spyOn(api, 'getInsightsByLocation').mockResolvedValue({
      rows: [
        { location_id: 5, name: 'Home', is_home: true, is_free: false,
          spend_pence: 1500, kwh: 200, sessions: 10, avg_p_per_kwh: 7.5,
          first_at: '2026-01-01', last_at: '2026-06-01', pct_of_spend: 100 },
      ],
      totals: { spend_pence: 1500, kwh: 200, sessions: 10 },
    })
    vi.spyOn(api, 'getSessions').mockResolvedValue([])

    renderAt('5')

    await waitFor(() => expect(screen.getByText('Home')).toBeInTheDocument())
    // Stats header: total cost £15.00, sessions 10.
    expect(screen.getByText('£15.00')).toBeInTheDocument()
    // Edit form is collapsed by default — opens via the Edit toggle.
    expect(screen.queryByTestId('save-button-5')).not.toBeInTheDocument()
    await userEvent.click(screen.getByTestId('toggle-edit-location'))
    expect(screen.getByTestId('save-button-5')).toBeInTheDocument()
    // Sessions fetched scoped to this location.
    expect(api.getSessions).toHaveBeenCalledWith('?location_id=5')
  })

  it('renders a 404 view for an unknown id', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([makeLocation({ id: 5 })])
    vi.spyOn(api, 'getInsightsByLocation').mockResolvedValue({
      rows: [
        { location_id: 5, name: 'Home', is_home: true, is_free: false,
          spend_pence: 1500, kwh: 200, sessions: 10, avg_p_per_kwh: 7.5,
          first_at: '2026-01-01', last_at: '2026-06-01', pct_of_spend: 100 },
      ],
      totals: { spend_pence: 1500, kwh: 200, sessions: 10 },
    })
    vi.spyOn(api, 'getSessions').mockResolvedValue([])

    renderAt('999')

    await waitFor(() =>
      expect(screen.getByTestId('location-not-found')).toBeInTheDocument(),
    )
  })
})
