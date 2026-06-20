import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api, type InsightsByLocationResponse } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import Insights from './Insights'

function makeResponse(): InsightsByLocationResponse {
  return {
    rows: [
      { location_id: 1, name: 'Home', is_home: true, is_free: false,
        spend_pence: 3000, kwh: 300, sessions: 20, avg_p_per_kwh: 10,
        first_at: '2026-01-01', last_at: '2026-06-01', pct_of_spend: 75 },
      { location_id: null, name: null, is_home: false, is_free: false,
        spend_pence: 1000, kwh: 50, sessions: 4, avg_p_per_kwh: 20,
        first_at: '2026-02-01', last_at: '2026-05-01', pct_of_spend: 25 },
    ],
    totals: { spend_pence: 4000, kwh: 350, sessions: 24 },
  }
}

const EMPTY_OVERVIEW = {
  granularity: 'daily' as const,
  over_time: [],
  split: {
    home: { spend_pence: 0, kwh: 0, sessions: 0, avg_p_per_kwh: null },
    public: { spend_pence: 0, kwh: 0, sessions: 0, avg_p_per_kwh: null },
  },
  by_network: [],
  efficiency: [],
  seasonal_efficiency: [],
  capacity_trend: [],
}

const DISABLED_MILEAGE = {
  enabled: false, car_id: 1, period_start: null, period_end: null, opening_km: null,
  current_km: null, target_km: null, used_km: null, remaining_km: null,
  days_elapsed: null, days_total: null, projected_year_end_km: null, pace: null,
}

describe('Insights page', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
  })
  afterEach(() => vi.restoreAllMocks())

  it('renders the breakdown table; labelled row links, Unassigned does not', async () => {
    vi.spyOn(api, 'getInsightsByLocation').mockResolvedValue(makeResponse())
    vi.spyOn(api, 'getInsightsOverview').mockResolvedValue(EMPTY_OVERVIEW)
    vi.spyOn(api, 'getCars').mockResolvedValue([])

    render(
      <MemoryRouter>
        <Insights />
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Home')).toBeInTheDocument())
    // Labelled row links to the detail page.
    const homeLink = screen.getByRole('link', { name: /Home/i })
    expect(homeLink).toHaveAttribute('href', '/locations/1')
    // Unassigned present but NOT a link.
    expect(screen.getByText('Unassigned')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Unassigned/i })).toBeNull()
  })

  it('re-queries when the date range changes', async () => {
    const spy = vi
      .spyOn(api, 'getInsightsByLocation')
      .mockResolvedValue(makeResponse())
    vi.spyOn(api, 'getInsightsOverview').mockResolvedValue(EMPTY_OVERVIEW)
    vi.spyOn(api, 'getCars').mockResolvedValue([])

    render(
      <MemoryRouter>
        <Insights />
      </MemoryRouter>,
    )
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    // First call is all-time (no bounds, no car filter).
    expect(spy.mock.calls[0]).toEqual([undefined, undefined, undefined])

    fireEvent.click(screen.getByTestId('insights-range-last_30'))
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    // Second call carries a date_from bound.
    expect(spy.mock.calls[1]![0]).toBeTruthy()
  })

  it('threads car_id into API calls when ?car= deep-link is present', async () => {
    const locationSpy = vi
      .spyOn(api, 'getInsightsByLocation')
      .mockResolvedValue({ rows: [], totals: { spend_pence: 0, kwh: 0, sessions: 0 } })
    const overviewSpy = vi
      .spyOn(api, 'getInsightsOverview')
      .mockResolvedValue(EMPTY_OVERVIEW)
    vi.spyOn(api, 'getCars').mockResolvedValue([
      { id: 5, make: 'Cupra', model: 'Born', name: null, display_name: 'Cupra Born', vin: null,
        battery_kwh: 58, nominal_efficiency_mi_per_kwh: 4.2, max_ac_kw: null, max_dc_kw: null,
        provider: 'manual', provider_vehicle_id: null, active: true },
    ])

    render(
      <MemoryRouter initialEntries={['/insights?car=5']}>
        <Insights />
      </MemoryRouter>,
    )

    await waitFor(() => expect(locationSpy).toHaveBeenCalledTimes(1))
    // Both endpoints must receive car_id=5 as the third argument.
    // Use mock.calls to inspect exact args (expect.anything() excludes undefined).
    expect(locationSpy.mock.calls[0]![2]).toBe(5)
    expect(overviewSpy.mock.calls[0]![2]).toBe(5)
  })

  it('renders the additional insight modules', async () => {
    vi.spyOn(api, 'getInsightsByLocation').mockResolvedValue({
      rows: [], totals: { spend_pence: 0, kwh: 0, sessions: 0 },
    })
    vi.spyOn(api, 'getInsightsOverview').mockResolvedValue({
      granularity: 'daily',
      over_time: [{ period: '2026-06-01', spend_pence: 200, kwh: 10, sessions: 1 }],
      split: {
        home: { spend_pence: 200, kwh: 10, sessions: 1, avg_p_per_kwh: 20 },
        public: { spend_pence: 0, kwh: 0, sessions: 0, avg_p_per_kwh: null },
      },
      by_network: [{ network: 'Tesla', spend_pence: 200, kwh: 10, sessions: 1, avg_p_per_kwh: 20 }],
      efficiency: [{ period: '2026-06-01', observed_mi_per_kwh: null, cost_per_mile_p: null }],
    })
    vi.spyOn(api, 'getCars').mockResolvedValue([
      { id: 1, make: 'Cupra', model: 'Born', name: null, display_name: 'Cupra Born', vin: null, battery_kwh: 58,
        nominal_efficiency_mi_per_kwh: 4.2, max_ac_kw: null, max_dc_kw: null, provider: 'manual', provider_vehicle_id: null, active: true },
    ])
    vi.spyOn(api, 'getInsightsMileage').mockResolvedValue(DISABLED_MILEAGE)

    render(<MemoryRouter><Insights /></MemoryRouter>)

    await waitFor(() => expect(screen.getByRole('heading', { name: /spend & energy over time/i })).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: /home vs public/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /network breakdown/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /efficiency & cost per mile/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /mileage allowance/i })).toBeInTheDocument()
  })

  it('renders seasonal efficiency module when array is present and non-empty', async () => {
    vi.spyOn(api, 'getInsightsByLocation').mockResolvedValue({
      rows: [], totals: { spend_pence: 0, kwh: 0, sessions: 0 },
    })
    vi.spyOn(api, 'getInsightsOverview').mockResolvedValue({
      granularity: 'monthly',
      over_time: [],
      split: {
        home: { spend_pence: 0, kwh: 0, sessions: 0, avg_p_per_kwh: null },
        public: { spend_pence: 0, kwh: 0, sessions: 0, avg_p_per_kwh: null },
      },
      by_network: [],
      efficiency: [],
      seasonal_efficiency: [
        { period: '2026-01', mi_per_kwh: 3.2, derived_range_km: 168, low_confidence: false },
        { period: '2026-06', mi_per_kwh: 4.1, derived_range_km: 215, low_confidence: false },
      ],
      capacity_trend: [],
    })
    vi.spyOn(api, 'getCars').mockResolvedValue([])
    vi.spyOn(api, 'getInsightsMileage').mockResolvedValue(DISABLED_MILEAGE)

    render(<MemoryRouter><Insights /></MemoryRouter>)

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /seasonal efficiency/i })).toBeInTheDocument(),
    )
  })

  it('renders battery health module when capacity_trend array is present and non-empty', async () => {
    vi.spyOn(api, 'getInsightsByLocation').mockResolvedValue({
      rows: [], totals: { spend_pence: 0, kwh: 0, sessions: 0 },
    })
    vi.spyOn(api, 'getInsightsOverview').mockResolvedValue({
      granularity: 'monthly',
      over_time: [],
      split: {
        home: { spend_pence: 0, kwh: 0, sessions: 0, avg_p_per_kwh: null },
        public: { spend_pence: 0, kwh: 0, sessions: 0, avg_p_per_kwh: null },
      },
      by_network: [],
      efficiency: [],
      seasonal_efficiency: [],
      capacity_trend: [
        { date: '2026-01-10', usable_kwh: 56.2, charging_type: 'ac', low_confidence: false },
        { date: '2026-03-15', usable_kwh: 55.8, charging_type: 'dc', low_confidence: false },
      ],
    })
    vi.spyOn(api, 'getCars').mockResolvedValue([])
    vi.spyOn(api, 'getInsightsMileage').mockResolvedValue(DISABLED_MILEAGE)

    render(<MemoryRouter><Insights /></MemoryRouter>)

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /estimated battery health/i })).toBeInTheDocument(),
    )
  })

  it('does NOT render trend modules when their arrays are empty', async () => {
    vi.spyOn(api, 'getInsightsByLocation').mockResolvedValue({
      rows: [], totals: { spend_pence: 0, kwh: 0, sessions: 0 },
    })
    vi.spyOn(api, 'getInsightsOverview').mockResolvedValue({
      ...EMPTY_OVERVIEW,
      seasonal_efficiency: [],
      capacity_trend: [],
    })
    vi.spyOn(api, 'getCars').mockResolvedValue([])

    render(<MemoryRouter><Insights /></MemoryRouter>)

    // Wait for the page to settle
    await waitFor(() =>
      expect(screen.queryByText(/loading/i)).not.toBeInTheDocument(),
    )

    expect(screen.queryByRole('heading', { name: /seasonal efficiency/i })).toBeNull()
    expect(screen.queryByRole('heading', { name: /estimated battery health/i })).toBeNull()
  })
})
