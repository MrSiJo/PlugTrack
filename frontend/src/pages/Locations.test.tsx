import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api, type LocationListPayload } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import Locations from './Locations'

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

describe('Locations page', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'getSettings').mockResolvedValue({})
    useSettingsStore.setState({ settings: {}, loaded: true })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders rows with name + aggregates and a Needs labelling badge for unlabelled', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([
      makeLocation({ id: 1, name: 'Home', visit_count: 12 }),
      makeLocation({
        id: 2,
        name: null,
        is_home: false,
        is_free: false,
        default_cost_per_kwh_p: null,
        address: null,
        visit_count: 0,
        total_kwh: 0,
        total_cost_pence: 0,
        last_visited_at: null,
      }),
    ])

    render(
      <MemoryRouter>
        <Locations />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByTestId('location-row').length).toBe(2)
    })
    expect(screen.getByRole('heading', { name: 'Home' })).toBeInTheDocument()
    expect(screen.getByText(/Unlabelled at 51.5074, -0.1278/)).toBeInTheDocument()
    expect(screen.getByTestId('needs-labelling-badge')).toBeInTheDocument()
    // Aggregates shown.
    expect(screen.getByText('12')).toBeInTheDocument() // visits
    expect(screen.getByText('£175.92')).toBeInTheDocument() // total cost
  })

  it('Save calls updateLocation with the edited fields and shows a success toast', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([
      makeLocation({ id: 1, name: 'Home' }),
    ])
    const updateSpy = vi
      .spyOn(api, 'updateLocation')
      .mockResolvedValue(makeLocation({ id: 1, name: 'Home Renamed' }))

    render(
      <MemoryRouter>
        <Locations />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('save-button-1')).toBeInTheDocument()
    })

    const nameInput = screen.getByTestId('name-input-1') as HTMLInputElement
    await act(async () => {
      fireEvent.change(nameInput, { target: { value: 'Home Renamed' } })
      fireEvent.click(screen.getByTestId('save-button-1'))
    })

    expect(updateSpy).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ name: 'Home Renamed' }),
    )

    await waitFor(() => {
      expect(screen.getByTestId('locations-toast')).toHaveTextContent(/Saved/i)
    })
  })

  it('Recalculate button calls api after confirm and reports the count', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([makeLocation({ id: 1 })])
    const recalcSpy = vi
      .spyOn(api, 'recalculateLocationPastCosts')
      .mockResolvedValue({ sessions_recomputed_count: 7 })
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )

    render(
      <MemoryRouter>
        <Locations />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('recalculate-button-1')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('recalculate-button-1'))
    })

    expect(recalcSpy).toHaveBeenCalledWith(1)
    await waitFor(() => {
      expect(screen.getByTestId('locations-toast')).toHaveTextContent(/Recomputed 7/)
    })
    vi.unstubAllGlobals()
  })

  it('Recalculate button does NOT call API if user cancels confirm', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([makeLocation({ id: 1 })])
    const recalcSpy = vi.spyOn(api, 'recalculateLocationPastCosts')
    vi.stubGlobal(
      'confirm',
      vi.fn(() => false),
    )

    render(
      <MemoryRouter>
        <Locations />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('recalculate-button-1')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('recalculate-button-1'))
    })

    expect(recalcSpy).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('Delete button calls deleteLocation after confirm', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([makeLocation({ id: 1 })])
    const deleteSpy = vi
      .spyOn(api, 'deleteLocation')
      .mockResolvedValue(undefined)
    vi.stubGlobal(
      'confirm',
      vi.fn(() => true),
    )

    render(
      <MemoryRouter>
        <Locations />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('delete-button-1')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('delete-button-1'))
    })

    expect(deleteSpy).toHaveBeenCalledWith(1)
    vi.unstubAllGlobals()
  })

  it('Add location reveals the form and Create posts typed coordinates', async () => {
    vi.spyOn(api, 'getLocations').mockResolvedValue([])
    const createSpy = vi.spyOn(api, 'createLocation').mockResolvedValue({
      id: 99,
      name: 'Tesla Camborne',
      centroid_lat: 50.2276,
      centroid_lng: -5.2801,
      radius_m: 100,
      is_home: false,
      is_free: false,
      default_cost_per_kwh_p: 45,
      default_charge_network: 'Tesla',
      address: null,
    })

    render(
      <MemoryRouter>
        <Locations />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('add-location-button')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('add-location-button'))

    expect(screen.getByTestId('location-create-form')).toBeInTheDocument()
    fireEvent.change(screen.getByTestId('create-name-input'), {
      target: { value: 'Tesla Camborne' },
    })
    fireEvent.change(screen.getByTestId('create-lat-input'), {
      target: { value: '50.2276' },
    })
    fireEvent.change(screen.getByTestId('create-lng-input'), {
      target: { value: '-5.2801' },
    })

    await act(async () => {
      fireEvent.click(screen.getByTestId('create-location-submit'))
    })

    expect(createSpy).toHaveBeenCalledTimes(1)
    const payload = createSpy.mock.calls[0]![0]
    expect(payload.name).toBe('Tesla Camborne')
    expect(payload.centroid_lat).toBeCloseTo(50.2276)
    expect(payload.centroid_lng).toBeCloseTo(-5.2801)
  })
})
