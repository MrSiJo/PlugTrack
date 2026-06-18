import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { api, type LocationPayload } from '@/api/client'
import { LocationEditForm } from './LocationEditForm'

function makeLocation(over: Partial<LocationPayload> = {}): LocationPayload {
  return {
    id: 7,
    name: 'Home',
    centroid_lat: 51.5,
    centroid_lng: -0.12,
    radius_m: 100,
    is_home: true,
    is_free: false,
    default_cost_per_kwh_p: 7.5,
    default_charge_network: null,
    address: null,
    ...over,
  }
}

describe('LocationEditForm', () => {
  beforeEach(() => vi.restoreAllMocks())
  afterEach(() => vi.restoreAllMocks())

  it('saves edited fields via updateLocation and calls onSaved', async () => {
    const updateSpy = vi
      .spyOn(api, 'updateLocation')
      .mockResolvedValue(makeLocation({ name: 'Renamed' }))
    const onSaved = vi.fn()

    render(<LocationEditForm location={makeLocation()} onSaved={onSaved} />)

    const nameInput = screen.getByTestId('name-input-7') as HTMLInputElement
    fireEvent.change(nameInput, { target: { value: 'Renamed' } })
    fireEvent.click(screen.getByTestId('save-button-7'))

    await waitFor(() => expect(updateSpy).toHaveBeenCalledTimes(1))
    expect(updateSpy.mock.calls[0]![0]).toBe(7)
    expect(updateSpy.mock.calls[0]![1]).toMatchObject({ name: 'Renamed' })
    await waitFor(() => expect(onSaved).toHaveBeenCalled())
  })

  it('recalculate calls the API after confirm', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const recalcSpy = vi
      .spyOn(api, 'recalculateLocationPastCosts')
      .mockResolvedValue({ sessions_recomputed_count: 3 })
    const onSaved = vi.fn()

    render(<LocationEditForm location={makeLocation()} onSaved={onSaved} />)
    fireEvent.click(screen.getByTestId('recalculate-button-7'))

    await waitFor(() => expect(recalcSpy).toHaveBeenCalledWith(7))
  })

  it('omits the radius field unless showRadius is set', () => {
    const { rerender } = render(
      <LocationEditForm location={makeLocation()} onSaved={vi.fn()} />,
    )
    expect(screen.queryByLabelText(/Cluster radius/i)).toBeNull()
    rerender(
      <LocationEditForm location={makeLocation()} onSaved={vi.fn()} showRadius />,
    )
    expect(screen.getByLabelText(/Cluster radius/i)).toBeInTheDocument()
  })
})
