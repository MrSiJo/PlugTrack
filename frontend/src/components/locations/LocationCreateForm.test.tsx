import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { api } from '@/api/client'
import { LocationCreateForm } from './LocationCreateForm'

// LocationPickerMap uses react-leaflet which is incompatible with jsdom.
// The geocode test exercises handleFindByAddress → handlePick which sets lat/lng
// state; the map is a display-only side-effect that is irrelevant to the tested
// behaviour, so we stub it out.
vi.mock('@/components/locations/LocationPickerMap', () => ({
  LocationPickerMap: () => <div data-testid="location-picker-map-stub" />,
}))

describe('LocationCreateForm', () => {
  const onCreated = vi.fn().mockResolvedValue(undefined)
  const onCancel = vi.fn()
  const onToast = vi.fn()

  beforeEach(() => {
    vi.restoreAllMocks()
    onCreated.mockResolvedValue(undefined)
    onCancel.mockReset()
    onToast.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('Find by address geocodes and fills the lat/lng coordinate inputs', async () => {
    vi.spyOn(api, 'geocode').mockResolvedValue({
      lat: 51.5074,
      lng: -0.1278,
      address: '10 Downing St, Westminster, London',
      provider: 'nominatim',
    })

    render(
      <LocationCreateForm
        onCreated={onCreated}
        onCancel={onCancel}
        onToast={onToast}
      />,
    )

    // Type an address query
    fireEvent.change(screen.getByTestId('geocode-query-input'), {
      target: { value: 'Downing St, London' },
    })

    // Trigger the search
    await act(async () => {
      fireEvent.click(screen.getByTestId('geocode-search-button'))
    })

    expect(api.geocode).toHaveBeenCalledWith('Downing St, London')

    // Coordinate inputs must be filled with the geocoded values
    await waitFor(() => {
      const latInput = screen.getByTestId('create-lat-input') as HTMLInputElement
      const lngInput = screen.getByTestId('create-lng-input') as HTMLInputElement
      expect(Number(latInput.value)).toBe(51.5074)
      expect(Number(lngInput.value)).toBe(-0.1278)
    })

    // A success toast must be emitted
    expect(onToast).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'success' }),
    )
  })

  it('pressing Enter in the address input triggers the search', async () => {
    vi.spyOn(api, 'geocode').mockResolvedValue({
      lat: 50.1,
      lng: -5.2,
      address: 'Test Place',
      provider: 'nominatim',
    })

    render(
      <LocationCreateForm
        onCreated={onCreated}
        onCancel={onCancel}
        onToast={onToast}
      />,
    )

    fireEvent.change(screen.getByTestId('geocode-query-input'), {
      target: { value: 'Test Place' },
    })

    await act(async () => {
      fireEvent.keyDown(screen.getByTestId('geocode-query-input'), {
        key: 'Enter',
        code: 'Enter',
      })
    })

    expect(api.geocode).toHaveBeenCalledWith('Test Place')

    await waitFor(() => {
      const latInput = screen.getByTestId('create-lat-input') as HTMLInputElement
      expect(Number(latInput.value)).toBe(50.1)
    })
  })
})
