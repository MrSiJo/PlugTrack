import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LocationLabelForm from './LocationLabelForm'
import { api } from '@/api/client'

describe('LocationLabelForm', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('disables the per-kWh rate input when "Free charging" is checked', async () => {
    const user = userEvent.setup()
    render(<LocationLabelForm locationId={1} />)

    const rateInput = screen.getByLabelText(/Default cost per kWh/i)
    expect(rateInput).not.toBeDisabled()

    await user.click(screen.getByLabelText(/Free charging/))
    expect(rateInput).toBeDisabled()
  })

  it('submits to api.labelLocation and emits the recompute count', async () => {
    const labelSpy = vi
      .spyOn(api, 'labelLocation')
      .mockResolvedValue({
        location: {
          id: 1,
          name: 'Tesco',
          centroid_lat: 50.85,
          centroid_lng: -0.13,
          radius_m: 100,
          is_home: false,
          is_free: false,
          default_cost_per_kwh_p: 35,
          address: null,
        },
        sessions_recomputed_count: 7,
      })

    const onSaved = vi.fn()
    const user = userEvent.setup()
    render(<LocationLabelForm locationId={1} onSaved={onSaved} />)

    await user.type(screen.getByPlaceholderText(/Home, Work/i), 'Tesco')
    await user.type(screen.getByLabelText(/Default cost per kWh/i), '35')
    await user.click(screen.getByRole('button', { name: /Save/i }))

    await waitFor(() => expect(labelSpy).toHaveBeenCalledTimes(1))
    expect(labelSpy).toHaveBeenCalledWith(1, {
      name: 'Tesco',
      is_home: false,
      is_free: false,
      default_cost_per_kwh_p: 35,
    })
    expect(onSaved).toHaveBeenCalledWith(7, expect.objectContaining({ name: 'Tesco' }))
  })

  it('disables the Save button until a name is entered', async () => {
    render(<LocationLabelForm locationId={1} />)
    const button = screen.getByRole('button', { name: /Save/i })
    expect(button).toBeDisabled()

    const user = userEvent.setup()
    await user.type(screen.getByPlaceholderText(/Home, Work/i), 'Home')
    expect(button).not.toBeDisabled()
  })

  it('sends null default_cost_per_kwh_p when free is checked', async () => {
    const labelSpy = vi
      .spyOn(api, 'labelLocation')
      .mockResolvedValue({
        location: {
          id: 1,
          name: 'Workplace',
          centroid_lat: 50,
          centroid_lng: 0,
          radius_m: 100,
          is_home: false,
          is_free: true,
          default_cost_per_kwh_p: null,
          address: null,
        },
        sessions_recomputed_count: 0,
      })

    const user = userEvent.setup()
    render(<LocationLabelForm locationId={1} />)
    await user.type(screen.getByPlaceholderText(/Home, Work/i), 'Workplace')
    await user.click(screen.getByLabelText(/Free charging/))
    await user.click(screen.getByRole('button', { name: /Save/i }))

    await waitFor(() => expect(labelSpy).toHaveBeenCalledTimes(1))
    expect(labelSpy.mock.calls[0]![1]).toMatchObject({
      is_free: true,
      default_cost_per_kwh_p: null,
    })
  })
})
