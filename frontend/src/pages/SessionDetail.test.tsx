import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import SessionDetail from './SessionDetail'
import {
  api,
  type ChargingSessionPayload,
  type SessionMetricsPayload,
} from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'

/** Default empty cars list — prevents getCars from being unmocked. */
function mockNoCars() {
  vi.spyOn(api, 'getCars').mockResolvedValue([])
}

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
    actual_charge_seconds: null,
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
    saved_vs_petrol_p: null,
    comparison_basis: null,
    breakeven_p_per_kwh: null,
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

describe('SessionDetail — hero charge time', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
    mockNoCars()
  })

  it('shows actual charge time (not the plug-in window) labelled "Charge time"', async () => {
    // 18h41m plug-in window, but only 3h58m of actual charging.
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        charge_start_at: '2026-06-18T13:17:00',
        charge_end_at: '2026-06-19T07:58:00',
        actual_charge_seconds: 3 * 3600 + 58 * 60,
      }),
    )

    renderDetail()

    const tile = await screen.findByTestId('session-duration')
    expect(tile).toHaveTextContent('Charge time')
    expect(tile).toHaveTextContent('3h 58')
    expect(tile).not.toHaveTextContent('18h 41')
  })

  it('falls back to the plug-in window labelled "Duration" when actual charge time is null', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        charge_start_at: '2026-06-18T13:17:00',
        charge_end_at: '2026-06-18T17:15:00',
        actual_charge_seconds: null,
      }),
    )

    renderDetail()

    const tile = await screen.findByTestId('session-duration')
    expect(tile).toHaveTextContent('Duration')
    expect(tile).toHaveTextContent('3h 58')
  })

  it('no longer renders the standalone kwh-calc-hint paragraph', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({ kwh_added: 46.2, kwh_calculated: 44.0 }),
    )

    renderDetail()

    await screen.findByTestId('toggle-edit')
    expect(screen.queryByTestId('kwh-calc-hint')).not.toBeInTheDocument()
  })
})

describe('SessionDetail — charge details', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
    mockNoCars()
  })

  it('renders a single Charge details section merging mechanics + context', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        charge_start_at: '2026-06-18T13:17:00',
        charge_end_at: '2026-06-18T17:15:00',
        charging_mode: 'timer',
        charging_type: 'ac',
        battery_care: true,
        max_charge_current: 'maximum',
        metrics: makeMetrics({
          range_added_miles: 120,
          average_power_kw: 7.2,
          peak_power_kw: 11,
          duration_minutes: 238,
        }),
      }),
    )

    renderDetail()

    const section = await screen.findByTestId('charge-details')
    expect(section).toHaveTextContent('Charge details')
    // Spine — always present.
    expect(section).toHaveTextContent('Range added')
    expect(section).toHaveTextContent('Avg power')
    // Known context tiles.
    expect(section).toHaveTextContent('Timer')
    expect(section).toHaveTextContent('AC')
    expect(section).toHaveTextContent('Battery care')
    // The dead tiles are gone.
    expect(screen.queryByTestId('metric-peak-power')).not.toBeInTheDocument()
    expect(screen.queryByTestId('ctx-max-current')).not.toBeInTheDocument()
    // There is no separate mechanics/context section any more.
    expect(screen.queryByTestId('charge-mechanics')).not.toBeInTheDocument()
    expect(screen.queryByTestId('charge-context')).not.toBeInTheDocument()
  })

  it('renders an Efficiency tile (mi/kWh + Wh/mi) when efficiency is known', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        metrics: makeMetrics({
          efficiency_mi_per_kwh: 3.6,
          efficiency_basis: 'observed',
        }),
      }),
    )

    renderDetail()

    const tile = await screen.findByTestId('metric-efficiency')
    expect(tile).toHaveTextContent('3.60 mi/kWh')
    expect(tile).toHaveTextContent('278 Wh/mi')
    expect(tile).toHaveTextContent('measured')
  })

  it('hides the Efficiency tile when efficiency is unknown', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({ metrics: makeMetrics({ efficiency_mi_per_kwh: null }) }),
    )
    renderDetail()
    await screen.findByTestId('charge-details')
    expect(screen.queryByTestId('metric-efficiency')).not.toBeInTheDocument()
  })

  it('renders the spine even when mode/type/care are unknown', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        charging_mode: 'unknown',
        charging_type: 'unknown',
        battery_care: null,
        max_charge_current: null,
        metrics: makeMetrics({
          range_added_miles: 80,
          average_power_kw: 6.5,
        }),
      }),
    )

    renderDetail()

    const section = await screen.findByTestId('charge-details')
    expect(section).toHaveTextContent('Range added')
    expect(section).toHaveTextContent('Avg power')
    // Unknown context tiles are suppressed.
    expect(screen.queryByTestId('ctx-mode')).not.toBeInTheDocument()
    expect(screen.queryByTestId('ctx-type')).not.toBeInTheDocument()
    expect(screen.queryByTestId('ctx-battery-care')).not.toBeInTheDocument()
  })

  it('renders the Duration tile only when both timestamps exist', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        charge_start_at: null,
        charge_end_at: null,
        metrics: makeMetrics({
          range_added_miles: 80,
          average_power_kw: 6.5,
          duration_minutes: 200,
        }),
      }),
    )

    renderDetail()

    await screen.findByTestId('charge-details')
    expect(screen.queryByTestId('details-duration')).not.toBeInTheDocument()
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

  it('edits charge start/end time + interrupted and submits them with derived date', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        date: '2026-06-01',
        charge_start_at: '2026-06-01T17:55:57',
        charge_end_at: '2026-06-01T18:01:01',
        interrupted: true,
      }),
    )
    const updateSpy = vi
      .spyOn(api, 'updateSession')
      .mockResolvedValue(makeSession())

    const user = (await import('@testing-library/user-event')).default.setup()
    renderDetail()

    await screen.findByTestId('toggle-edit')
    await user.click(screen.getByTestId('toggle-edit'))

    const startInput = screen.getByTestId('edit-charge-start') as HTMLInputElement
    const interruptedInput = screen.getByTestId(
      'edit-interrupted',
    ) as HTMLInputElement
    // Pre-filled (minute precision) from the stored offset-less timestamps.
    expect(startInput.value).toBe('2026-06-01T17:55')
    expect(interruptedInput.checked).toBe(true)

    // Push the start time back to 17:30 and clear the interrupted flag.
    await user.clear(startInput)
    await user.type(startInput, '2026-06-01T17:30')
    await user.click(interruptedInput)
    await user.click(screen.getByTestId('edit-save'))

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalled()
    })
    const body = updateSpy.mock.calls[0]![1]
    expect(body.charge_start_at).toBe('2026-06-01T17:30')
    expect(body.charge_end_at).toBe('2026-06-01T18:01')
    expect(body.interrupted).toBe(false)
    // `date` follows the corrected start so the list stays sorted.
    expect(body.date).toBe('2026-06-01')
  })
})

function makeMetrics(
  over: Partial<SessionMetricsPayload> = {},
): SessionMetricsPayload {
  return {
    miles_since_previous: 62,
    measured_miles_since_previous: null,
    cost_per_mile_p: 5.6,
    petrol_ppm: 12.8,
    petrol_equivalent_cost_p: 791,
    savings_vs_petrol_p: 423,
    petrol_price_p_per_litre: 151.9,
    petrol_mpg: 54.1,
    comparison_basis: 'measured',
    chain_session_ids: [],
    chain_total_cost_pence: null,
    chain_anchor_id: null,
    range_added_miles: null,
    duration_minutes: null,
    average_power_kw: null,
    peak_power_kw: null,
    efficiency_percent: null,
    breakeven_p_per_kwh: null,
    efficiency_mi_per_kwh: null,
    efficiency_basis: null,
    ...over,
  }
}

describe('SessionDetail — charge curve approximation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
    mockNoCars()
  })

  const curve = [
    [0, 55, 0],
    [264, 62, 62],
    [1188, 86, 50],
    [1320, 90, 0],
  ]

  it('renders an Approximate badge + dashed power line when approximate', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        power_curve: curve,
        power_curve_approximate: true,
      }),
    )

    renderDetail()

    const section = await screen.findByTestId('charge-curve')
    expect(section).toHaveTextContent(/Approximate/i)
    expect(section).not.toHaveTextContent('Measured')
    const power = section.querySelector('[data-testid="curve-power-path"]')
    expect(power).not.toBeNull()
    expect(power!.getAttribute('stroke-dasharray')).toBeTruthy()
  })

  it('renders a Measured badge + solid power line when not approximate', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        power_curve: curve,
        power_curve_approximate: false,
      }),
    )

    renderDetail()

    const section = await screen.findByTestId('charge-curve')
    expect(section).toHaveTextContent('Measured')
    expect(section).not.toHaveTextContent(/Approximate/i)
    const power = section.querySelector('[data-testid="curve-power-path"]')
    expect(power).not.toBeNull()
    expect(power!.getAttribute('stroke-dasharray')).toBeFalsy()
  })
})

describe('SessionDetail — petrol comparison basis', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
    mockNoCars()
  })

  it('shows the Estimated pill and a tilde on savings when basis is estimated', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        odometer_at_session_km: null,
        metrics: makeMetrics({ comparison_basis: 'estimated' }),
      }),
    )

    renderDetail()

    const badge = await screen.findByTestId('estimated-badge')
    expect(badge).toHaveTextContent('Estimated')

    const savings = screen.getByTestId('metric-savings')
    expect(savings).toHaveTextContent('~')
  })

  it('shows no pill and no tilde on savings when basis is not estimated', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        metrics: makeMetrics({ comparison_basis: null }),
      }),
    )

    renderDetail()

    const savings = await screen.findByTestId('metric-savings')
    expect(savings).not.toHaveTextContent('~')
    expect(screen.queryByTestId('estimated-badge')).not.toBeInTheDocument()
  })

  it('renders down-arrow + green in savings hero when cheaper than petrol', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        metrics: makeMetrics({
          comparison_basis: 'estimated',
          savings_vs_petrol_p: 423,
          miles_since_previous: 62,
        }),
      }),
    )

    renderDetail()

    const savings = await screen.findByTestId('metric-savings')
    // Down-arrow for a saving; ~ prefix for estimated.
    expect(savings).toHaveTextContent('~↓')
    expect(savings).toHaveTextContent('£4.23')
    // No raw +/- sign.
    expect(savings).not.toHaveTextContent('+')
    expect(savings.className).toMatch(/emerald/)
  })

  it('renders up-arrow + red in savings hero when dearer than petrol', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        metrics: makeMetrics({
          comparison_basis: 'estimated',
          savings_vs_petrol_p: -250,
          miles_since_previous: 30,
        }),
      }),
    )

    renderDetail()

    const savings = await screen.findByTestId('metric-savings')
    // Up-arrow for a loss; magnitude without sign.
    expect(savings).toHaveTextContent('~↑')
    expect(savings).toHaveTextContent('£2.50')
    expect(savings).not.toHaveTextContent('-£')
    expect(savings.className).toMatch(/rose/)
  })

  it('does not render any "chain" or "see session" messaging', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        metrics: makeMetrics({
          chain_session_ids: [5, 6],
          chain_anchor_id: 5,
          chain_total_cost_pence: 2000,
        }),
      }),
    )

    renderDetail()

    await screen.findByTestId('toggle-edit')

    // Chain / top-up messaging has been removed from the per-charge model.
    expect(screen.queryByText(/ongoing top-up chain/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/see session/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/chain/i)).not.toBeInTheDocument()
  })

})

describe('SessionDetail — petrol comparison compact card', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
    mockNoCars()
  })

  it('renders one compact line with savings, EV vs petrol /mi and equivalent', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        metrics: makeMetrics({
          comparison_basis: 'measured',
          savings_vs_petrol_p: 185,
          miles_since_previous: 62,
          cost_per_mile_p: 6.3,
          petrol_ppm: 12.8,
          petrol_equivalent_cost_p: 363,
        }),
      }),
    )

    renderDetail()

    const card = await screen.findByTestId('petrol-comparison')
    expect(card).toHaveTextContent('£1.85')
    expect(card).toHaveTextContent('6.3p')
    expect(card).toHaveTextContent('12.8p')
    expect(card).toHaveTextContent('£3.63')

    // The four standalone StatTiles are gone.
    expect(screen.queryByTestId('metric-cost-per-mile')).not.toBeInTheDocument()
    expect(screen.queryByTestId('metric-petrol-ppm')).not.toBeInTheDocument()
    expect(screen.queryByTestId('metric-petrol-cost')).not.toBeInTheDocument()
    expect(screen.queryByTestId('metric-miles')).not.toBeInTheDocument()
  })

  it('keeps the "set Settings" empty state', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        metrics: makeMetrics({
          petrol_price_p_per_litre: null,
          petrol_mpg: null,
        }),
      }),
    )

    renderDetail()

    const card = await screen.findByTestId('petrol-comparison')
    expect(card).toHaveTextContent(/Settings/i)
  })

  it('keeps the "needs data" empty state', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        metrics: makeMetrics({ miles_since_previous: null }),
      }),
    )

    renderDetail()

    const card = await screen.findByTestId('petrol-comparison')
    expect(card).toHaveTextContent(/Needs energy or odometer data/i)
  })
})

describe('SessionDetail — source rendering', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
    mockNoCars()
  })

  it('does not render any unconfirmed review panel for a normal session', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({ source: 'manual' }),
    )

    renderDetail()

    await screen.findByTestId('toggle-edit')
    // The unconfirmed review/confirm/discard surface has been removed entirely.
    expect(screen.queryByTestId('unconfirmed-panel')).not.toBeInTheDocument()
    expect(screen.queryByTestId('confirm-charge-btn')).not.toBeInTheDocument()
    expect(screen.queryByTestId('discard-charge-btn')).not.toBeInTheDocument()
    expect(screen.queryByText(/Unconfirmed charge/i)).not.toBeInTheDocument()
  })
})

describe('SessionDetail — assign location via edit form', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
    mockNoCars()
  })

  it('lets you assign a location to an unassigned session', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(makeSession({ location_id: null }))
    vi.spyOn(api, 'getLocations').mockResolvedValue([
      {
        id: 9,
        name: 'Instavolt McDonalds (Yeovil)',
        centroid_lat: 50.95,
        centroid_lng: -2.64,
        radius_m: 100,
        is_home: false,
        is_free: false,
        default_cost_per_kwh_p: 79,
        default_charge_network: 'InstaVolt',
        address: null,
        visit_count: 0,
        total_kwh: 0,
        total_cost_pence: 0,
        last_visited_at: null,
      },
    ])
    const updateSpy = vi
      .spyOn(api, 'updateSession')
      .mockResolvedValue(makeSession({ location_id: 9 }))

    renderDetail()

    await waitFor(() => expect(screen.getByTestId('toggle-edit')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('toggle-edit'))

    // The location selector is populated from getLocations.
    await waitFor(() =>
      expect(screen.getByTestId('edit-location-select')).toBeInTheDocument(),
    )
    fireEvent.change(screen.getByTestId('edit-location-select'), {
      target: { value: '9' },
    })

    await act(async () => {
      fireEvent.click(screen.getByTestId('edit-save'))
    })

    expect(updateSpy).toHaveBeenCalledTimes(1)
    expect(updateSpy.mock.calls[0]![1]).toMatchObject({ location_id: 9 })
  })
})

describe('SessionDetail — car reassignment picker', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
    mockNoCars()
  })

  it('renders a car-picker in the header/hero area showing the current car', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({ car_id: 7 }),
    )
    vi.spyOn(api, 'getCars').mockResolvedValue([
      {
        id: 7,
        make: 'Cupra',
        model: 'Born',
        name: null,
        display_name: 'Cupra Born',
        vin: null,
        battery_kwh: 59,
        nominal_efficiency_mi_per_kwh: 3.5,
        max_ac_kw: null,
        max_dc_kw: null,
        provider: 'cupra',
        provider_vehicle_id: null,
        active: true,
      },
      {
        id: 8,
        make: 'Tesla',
        model: 'Model 3',
        name: null,
        display_name: 'Tesla Model 3',
        vin: null,
        battery_kwh: 75,
        nominal_efficiency_mi_per_kwh: 4.0,
        max_ac_kw: null,
        max_dc_kw: null,
        provider: 'manual',
        provider_vehicle_id: null,
        active: true,
      },
    ])
    vi.spyOn(api, 'updateSession').mockResolvedValue(makeSession({ car_id: 8 }))

    renderDetail()

    // Car picker should be visible showing the current car
    await waitFor(() => {
      expect(screen.getByTestId('car-reassign-picker')).toBeInTheDocument()
    })
    expect(screen.getByTestId('car-reassign-picker')).toHaveTextContent('Cupra Born')
  })

  it('selecting a different car calls updateSession with the new car_id', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({ car_id: 7 }),
    )
    vi.spyOn(api, 'getCars').mockResolvedValue([
      {
        id: 7,
        make: 'Cupra',
        model: 'Born',
        name: null,
        display_name: 'Cupra Born',
        vin: null,
        battery_kwh: 59,
        nominal_efficiency_mi_per_kwh: 3.5,
        max_ac_kw: null,
        max_dc_kw: null,
        provider: 'cupra',
        provider_vehicle_id: null,
        active: true,
      },
      {
        id: 8,
        make: 'Tesla',
        model: 'Model 3',
        name: null,
        display_name: 'Tesla Model 3',
        vin: null,
        battery_kwh: 75,
        nominal_efficiency_mi_per_kwh: 4.0,
        max_ac_kw: null,
        max_dc_kw: null,
        provider: 'manual',
        provider_vehicle_id: null,
        active: true,
      },
    ])
    const updateSpy = vi
      .spyOn(api, 'updateSession')
      .mockResolvedValue(makeSession({ car_id: 8 }))
    vi.spyOn(api, 'getSession')
      .mockResolvedValueOnce(makeSession({ car_id: 7 }))
      .mockResolvedValueOnce(makeSession({ car_id: 8 }))

    const user = userEvent.setup()
    renderDetail()

    await waitFor(() => {
      expect(screen.getByTestId('car-reassign-picker')).toBeInTheDocument()
    })

    // Open the picker and select a different car
    await user.click(screen.getByTestId('car-reassign-picker'))
    const option = await screen.findByRole('option', { name: 'Tesla Model 3' })
    await user.click(option)

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(1, expect.objectContaining({ car_id: 8 }))
    })
  })

  it('shows an error alert when updateSession rejects during car reassign', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({ car_id: 7 }),
    )
    vi.spyOn(api, 'getCars').mockResolvedValue([
      {
        id: 7,
        make: 'Cupra',
        model: 'Born',
        name: null,
        display_name: 'Cupra Born',
        vin: null,
        battery_kwh: 59,
        nominal_efficiency_mi_per_kwh: 3.5,
        max_ac_kw: null,
        max_dc_kw: null,
        provider: 'cupra',
        provider_vehicle_id: null,
        active: true,
      },
      {
        id: 8,
        make: 'Tesla',
        model: 'Model 3',
        name: null,
        display_name: 'Tesla Model 3',
        vin: null,
        battery_kwh: 75,
        nominal_efficiency_mi_per_kwh: 4.0,
        max_ac_kw: null,
        max_dc_kw: null,
        provider: 'manual',
        provider_vehicle_id: null,
        active: true,
      },
    ])
    vi.spyOn(api, 'updateSession').mockRejectedValue(new Error('Server error'))

    const user = userEvent.setup()
    renderDetail()

    await waitFor(() => {
      expect(screen.getByTestId('car-reassign-picker')).toBeInTheDocument()
    })

    // Open the picker and select a different car
    await user.click(screen.getByTestId('car-reassign-picker'))
    const option = await screen.findByRole('option', { name: 'Tesla Model 3' })
    await user.click(option)

    // Failure message should appear
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(
        "Couldn't reassign car — please try again.",
      )
    })
  })
})
