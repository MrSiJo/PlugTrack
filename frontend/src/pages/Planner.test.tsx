import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Planner from './Planner'
import { ApiError, api, type CarPayload, type ChargePlan } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeCar(over: Partial<CarPayload> = {}): CarPayload {
  return {
    id: 1,
    make: 'Cupra',
    model: 'Born',
    name: null,
    display_name: 'Cupra Born',
    vin: null,
    battery_kwh: 77,
    nominal_efficiency_mi_per_kwh: 3.5,
    provider: 'cupra_connect',
    provider_vehicle_id: null,
    active: true,
    ...over,
  }
}

function makePlan(over: Partial<ChargePlan> = {}): ChargePlan {
  return {
    car_id: 1,
    start_soc: 20,
    target_soc: 100,
    battery_kwh: 77,
    kwh_needed: 61.6,
    power_kw: 7.4,
    power_basis: 'fallback',
    sample_size: 0,
    total_minutes: 499,
    window_start: '23:45',
    window_end: '07:15',
    window_minutes: 450,
    fits_one_window: false,
    nights: [
      { index: 1, minutes: 450, end_soc: 75, finish_at: '07:15' },
      { index: 2, minutes: 49, end_soc: 100, finish_at: '00:34' },
    ],
    nights_needed: 2,
    finish_at: '00:34',
    cost_pence: 1746,
    home_rate_p_per_kwh: 28.34,
    is_free: false,
    ...over,
  }
}

function makeSingleNightPlan(over: Partial<ChargePlan> = {}): ChargePlan {
  return {
    car_id: 1,
    start_soc: 70,
    target_soc: 100,
    battery_kwh: 77,
    kwh_needed: 23.1,
    power_kw: 7.4,
    power_basis: 'history',
    sample_size: 5,
    total_minutes: 188,
    window_start: '23:45',
    window_end: '07:15',
    window_minutes: 450,
    fits_one_window: true,
    nights: [{ index: 1, minutes: 188, end_soc: 100, finish_at: '02:53' }],
    nights_needed: 1,
    finish_at: '02:53',
    cost_pence: 654,
    home_rate_p_per_kwh: 28.34,
    is_free: false,
    ...over,
  }
}

// ---------------------------------------------------------------------------
// Render helper
// ---------------------------------------------------------------------------

function renderPlanner() {
  return render(
    <MemoryRouter initialEntries={['/planner']}>
      <Planner />
    </MemoryRouter>,
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Planner page', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
  })

  it('renders the page heading', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makeSingleNightPlan())

    renderPlanner()

    expect(screen.getByText('Charge Planner')).toBeInTheDocument()
  })

  it('shows the duration and cost for a single-night plan', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makeSingleNightPlan())

    renderPlanner()

    // Duration: 188 min = 3h 08m
    const duration = await screen.findByTestId('plan-duration')
    expect(duration).toHaveTextContent('3h 08m')

    // Cost: 654 pence = £6.54
    const cost = screen.getByTestId('plan-cost')
    expect(cost).toHaveTextContent('£6.54')
  })

  it('shows the single-window verdict when fits_one_window is true', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makeSingleNightPlan())

    renderPlanner()

    const verdict = await screen.findByTestId('plan-verdict')
    expect(verdict).toHaveTextContent('Finishes ~02:53')
    expect(verdict).toHaveTextContent('23:45–07:15 window')
  })

  it('shows multi-night verdict and breakdown when fits_one_window is false', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    const verdict = await screen.findByTestId('plan-verdict')
    expect(verdict).toHaveTextContent('Needs 2 nights')
    expect(verdict).toHaveTextContent('finishes ~00:34 on night 2')

    // Night breakdown should be visible
    const nights = screen.getByTestId('plan-nights')
    expect(nights).toBeInTheDocument()

    const night1 = screen.getByTestId('plan-night-1')
    expect(night1).toHaveTextContent('Night 1')
    expect(night1).toHaveTextContent('75%')

    const night2 = screen.getByTestId('plan-night-2')
    expect(night2).toHaveTextContent('Night 2')
    expect(night2).toHaveTextContent('100%')
  })

  it('does NOT show the nights breakdown for a single-night plan', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makeSingleNightPlan())

    renderPlanner()

    await screen.findByTestId('plan-result')
    expect(screen.queryByTestId('plan-nights')).not.toBeInTheDocument()
  })

  it('shows the fallback power caption when power_basis is fallback', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan({ power_basis: 'fallback', power_kw: 7.4 }))

    renderPlanner()

    const caption = await screen.findByTestId('plan-power-caption')
    expect(caption).toHaveTextContent('Estimated at 7.4 kW')
    expect(caption).toHaveTextContent('not enough home history yet')
  })

  it('shows the history power caption when power_basis is history', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(
      makeSingleNightPlan({ power_basis: 'history', sample_size: 5, power_kw: 7.4 }),
    )

    renderPlanner()

    const caption = await screen.findByTestId('plan-power-caption')
    expect(caption).toHaveTextContent('Based on your last 5 home charges')
    expect(caption).toHaveTextContent('~7.4 kW')
  })

  it('shows "Free" when is_free is true', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(
      makeSingleNightPlan({ is_free: true, cost_pence: 0 }),
    )

    renderPlanner()

    const cost = await screen.findByTestId('plan-cost')
    expect(cost).toHaveTextContent('Free')
  })

  it('shows an error when the API call fails', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockRejectedValue(
      new ApiError(404, 'Car not found', null),
    )

    renderPlanner()

    const err = await screen.findByTestId('plan-error')
    expect(err).toHaveTextContent('Car not found')
  })

  it('calls getChargePlan with the correct car_id, start_soc, target_soc', async () => {
    const getCars = vi.spyOn(api, 'getCars').mockResolvedValue([makeCar({ id: 42 })])
    const getChargePlan = vi
      .spyOn(api, 'getChargePlan')
      .mockResolvedValue(makeSingleNightPlan())

    renderPlanner()

    // Wait until cars have loaded and the plan call is triggered.
    await waitFor(() => {
      expect(getCars).toHaveBeenCalled()
    })
    await waitFor(() => {
      expect(getChargePlan).toHaveBeenCalledWith(42, 20, 100)
    })
  })
})
