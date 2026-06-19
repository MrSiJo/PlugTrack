import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api, type LocationListPayload } from '@/api/client'
import { LocationsManagement } from './LocationsManagement'

function makeLocation(over: Partial<LocationListPayload> = {}): LocationListPayload {
  return {
    id: 1,
    name: 'Home',
    centroid_lat: 51.5074,
    centroid_lng: -0.1278,
    radius_m: 100,
    is_home: true,
    is_free: false,
    default_cost_per_kwh_p: 7.5,
    default_charge_network: null,
    address: '10 Downing St, London',
    visit_count: 12,
    total_kwh: 234.56,
    total_cost_pence: 17592,
    last_visited_at: '2026-04-01T10:00:00+00:00',
    ...over,
  }
}

describe('LocationsManagement', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('renders location rows for each location', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([
      makeLocation({ id: 1, name: 'Home' }),
      makeLocation({ id: 2, name: 'Tesla Camborne' }),
    ])

    render(
      <MemoryRouter>
        <LocationsManagement />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByTestId('admin-location-row').length).toBe(2)
    })
    // Both names appear as row labels (they also appear in merge dropdowns,
    // so use getAllByText and check count ≥ 1).
    expect(screen.getAllByText('Home').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Tesla Camborne').length).toBeGreaterThanOrEqual(1)
  })

  it('Delete button calls api.deleteLocation after confirm', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([makeLocation({ id: 1, name: 'Home' })])
    const deleteSpy = vi.spyOn(api, 'deleteLocation').mockResolvedValue(undefined)
    vi.stubGlobal('confirm', vi.fn(() => true))

    render(
      <MemoryRouter>
        <LocationsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-delete-button-1')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-delete-button-1'))
    })

    expect(deleteSpy).toHaveBeenCalledWith(1)
  })

  it('Delete does NOT call api if confirm is cancelled', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([makeLocation({ id: 1, name: 'Home' })])
    const deleteSpy = vi.spyOn(api, 'deleteLocation').mockResolvedValue(undefined)
    vi.stubGlobal('confirm', vi.fn(() => false))

    render(
      <MemoryRouter>
        <LocationsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-delete-button-1')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-delete-button-1'))
    })

    expect(deleteSpy).not.toHaveBeenCalled()
  })

  it('selecting a merge target and clicking Merge calls api.mergeLocations', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([
      makeLocation({ id: 1, name: 'Home' }),
      makeLocation({ id: 2, name: 'Work' }),
    ])
    const mergeSpy = vi.spyOn(api, 'mergeLocations').mockResolvedValue({
      sessions_redirected: 3,
      plug_ins_redirected: 1,
      sessions_recomputed_count: 3,
    })
    vi.stubGlobal('confirm', vi.fn(() => true))

    render(
      <MemoryRouter>
        <LocationsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-merge-target-1')).toBeInTheDocument(),
    )

    // Select the merge target (id=2 "Work") in the first row (id=1)
    fireEvent.change(screen.getByTestId('admin-merge-target-1'), {
      target: { value: '2' },
    })

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-merge-button-1'))
    })

    expect(mergeSpy).toHaveBeenCalledWith(1, 2)
  })

  it('clicking "Add location" renders LocationCreateForm', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([])

    render(
      <MemoryRouter>
        <LocationsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-add-location-button')).toBeInTheDocument(),
    )

    fireEvent.click(screen.getByTestId('admin-add-location-button'))

    expect(screen.getByTestId('location-create-form')).toBeInTheDocument()
  })
})
