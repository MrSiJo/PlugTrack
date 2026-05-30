import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import SessionDetail from './SessionDetail'
import {
  api,
  type ChargingSessionPayload,
  type SessionMetricsPayload,
} from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'

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

describe('SessionDetail — charge context', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
  })

  it('renders a Charge context section with mode/type/battery-care/max-current', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        charging_mode: 'timer',
        charging_type: 'ac',
        battery_care: true,
        max_charge_current: 'maximum',
      }),
    )

    renderDetail()

    const section = await screen.findByTestId('charge-context')
    expect(section).toHaveTextContent('Charge context')
    expect(section).toHaveTextContent('Timer')
    expect(section).toHaveTextContent('AC')
    expect(section).toHaveTextContent('Battery care')
    expect(section).toHaveTextContent('Maximum')
  })

  it('omits the Charge context section when nothing useful is known', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        charging_mode: 'unknown',
        charging_type: 'unknown',
        battery_care: null,
        max_charge_current: null,
      }),
    )

    renderDetail()

    await waitFor(() => {
      expect(screen.getByTestId('toggle-edit')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('charge-context')).not.toBeInTheDocument()
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
    ...over,
  }
}

describe('SessionDetail — petrol comparison basis', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
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

  it('shows measured distance info when measured_miles_since_previous is present', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        metrics: makeMetrics({
          comparison_basis: 'estimated',
          miles_since_previous: 62,
          measured_miles_since_previous: 124,
        }),
      }),
    )

    renderDetail()

    const info = await screen.findByTestId('measured-distance-info')
    expect(info).toBeInTheDocument()
    // Shows the measured distance value.
    expect(info).toHaveTextContent('124')
  })

  it('does not show measured distance info when measured_miles_since_previous is null', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        metrics: makeMetrics({
          comparison_basis: 'estimated',
          miles_since_previous: 62,
          measured_miles_since_previous: null,
        }),
      }),
    )

    renderDetail()

    await screen.findByTestId('toggle-edit')
    expect(screen.queryByTestId('measured-distance-info')).not.toBeInTheDocument()
  })
})

describe('SessionDetail — unconfirmed session', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
  })

  it('shows the UnconfirmedActionPanel when source is "unconfirmed"', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({
        source: 'unconfirmed',
        kwh_calculated: 12.5,
        kwh_added: 0,
      }),
    )

    renderDetail()

    const panel = await screen.findByTestId('unconfirmed-panel')
    expect(panel).toBeInTheDocument()
    expect(panel).toHaveTextContent('Unconfirmed charge')
    expect(panel).toHaveTextContent('12.50 kWh')

    // Confirm and Discard buttons present.
    expect(screen.getByTestId('confirm-charge-btn')).toBeInTheDocument()
    expect(screen.getByTestId('discard-charge-btn')).toBeInTheDocument()
  })

  it('does not show the UnconfirmedActionPanel for a normal session', async () => {
    vi.spyOn(api, 'getSession').mockResolvedValue(
      makeSession({ source: 'manual' }),
    )

    renderDetail()

    await screen.findByTestId('toggle-edit')
    expect(screen.queryByTestId('unconfirmed-panel')).not.toBeInTheDocument()
  })

  it('calls confirmSession and refreshes the session after confirm', async () => {
    const unconfirmedSession = makeSession({
      source: 'unconfirmed',
      kwh_calculated: 10.0,
      kwh_added: 0,
    })
    const confirmedSession = makeSession({
      source: 'manual',
      kwh_added: 10.0,
      notes: '[auto-detected from SoC delta]',
    })

    vi.spyOn(api, 'getSession').mockResolvedValue(unconfirmedSession)
    const confirmSpy = vi
      .spyOn(api, 'confirmSession')
      .mockResolvedValue(confirmedSession)

    const user = (await import('@testing-library/user-event')).default.setup()
    renderDetail()

    await screen.findByTestId('confirm-charge-btn')
    await user.click(screen.getByTestId('confirm-charge-btn'))

    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalledWith(
        unconfirmedSession.id,
        expect.objectContaining({ location_id: null }),
      )
    })

    // After confirm the panel should disappear (session promoted to manual).
    await waitFor(() => {
      expect(screen.queryByTestId('unconfirmed-panel')).not.toBeInTheDocument()
    })
  })
})
