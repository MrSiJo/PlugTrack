import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api, type DashboardSummary } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import Dashboard from './Dashboard'

function fixtureSummary(): DashboardSummary {
  return {
    cars: [
      {
        id: 1,
        make: 'Cupra',
        model: 'Born',
        battery_level: 73,
        last_connected: new Date(Date.now() - 60_000).toISOString(),
        last_soc: 73,
        nominal_efficiency_mi_per_kwh: null,
        mileage_year: null,
      },
      {
        id: 2,
        make: 'Cupra',
        model: 'Tavascan',
        battery_level: 50,
        last_connected: null,
        last_soc: 50,
        nominal_efficiency_mi_per_kwh: null,
        mileage_year: null,
      },
    ],
    recent_sessions: [
      {
        id: 100,
        car_id: 1,
        car_label: 'Cupra Born',
        date: '2026-05-01',
        kwh_added: 12.5,
        cost_pence: 240,
        cost_basis: 'home_rate',
        location_id: 7,
        location_name: 'Home',
        charge_network: null,
        source: 'synthesis',
      },
      {
        id: 101,
        car_id: 2,
        car_label: 'VW ID.4',
        date: '2026-04-30',
        kwh_added: 42.0,
        cost_pence: 3500,
        cost_basis: 'location_rate',
        location_id: 9,
        location_name: 'Gridserve',
        charge_network: 'Gridserve',
        source: 'manual',
      },
    ],
    lifetime_totals: {
      kwh: 1234.5,
      cost_pence: 89_900,
      // 1609.344 km == 1000 mi
      distance_km: 1609,
      sessions_count: 42,
    },
    top_locations: [
      {
        id: 7,
        name: 'Home',
        charge_count: 25,
        total_kwh: 412.3,
        total_cost_pence: 30_900,
      },
      {
        id: 9,
        name: 'Gridserve',
        charge_count: 4,
        total_kwh: 168.0,
        total_cost_pence: 14_000,
      },
    ],
    cost_per_mile: {
      lifetime_pence: 8.5,
      rolling_30d_pence: 9.2,
    },
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  // Default to imperial so the conversion test bites.
  useSettingsStore.setState({
    settings: {
      distance_unit: {
        key: 'distance_unit',
        value: 'mi',
        value_type: 'enum',
        group_name: 'display',
        label: 'Distance unit',
        description: null,
        is_secret: false,
      },
      currency: {
        key: 'currency',
        value: 'GBP',
        value_type: 'enum',
        group_name: 'display',
        label: 'Currency',
        description: null,
        is_secret: false,
      },
    },
    loaded: true,
    loading: false,
    error: null,
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Dashboard page', () => {
  it('renders all four panels with fixture data', async () => {
    vi.spyOn(api, 'getDashboard').mockResolvedValue(fixtureSummary())

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('dashboard-root')).toBeInTheDocument(),
    )

    expect(screen.getByTestId('panel-cars')).toBeInTheDocument()
    expect(screen.getByTestId('panel-recent')).toBeInTheDocument()
    expect(screen.getByTestId('panel-lifetime')).toBeInTheDocument()
    expect(screen.getByTestId('panel-locations')).toBeInTheDocument()

    // Per-car panels.
    expect(screen.getByTestId('car-panel-1')).toHaveTextContent('Born')
    expect(screen.getByTestId('car-panel-2')).toHaveTextContent('Tavascan')

    // HeroCarCard now shows a snapshot battery labelled "after last charge",
    // sourced from the latest session derived off recent_sessions.
    const car1 = screen.getByTestId('car-panel-1')
    expect(car1).toHaveTextContent('73')
    expect(car1).toHaveTextContent(/after last charge/i)
    // Most-recent-charge summary for car 1 (session id 100: 12.5 kWh @ Home).
    expect(within(car1).getByTestId('car-last-charge')).toHaveTextContent(
      '12.5 kWh',
    )
    expect(within(car1).getByTestId('car-last-charge')).toHaveTextContent('Home')

    // Recent session rows present.
    expect(screen.getByTestId('recent-session-100')).toBeInTheDocument()
    expect(screen.getByTestId('recent-session-101')).toBeInTheDocument()

    // Top locations.
    expect(screen.getByTestId('top-location-7')).toHaveTextContent('Home')
    expect(screen.getByTestId('top-location-9')).toHaveTextContent('Gridserve')
  })

  it('formats distance in miles when distance_unit is "mi"', async () => {
    vi.spyOn(api, 'getDashboard').mockResolvedValue(fixtureSummary())

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('lifetime-distance')).toBeInTheDocument(),
    )
    // 1609 km / 1.609344 = 999.79… mi → rounded 1000.
    expect(screen.getByTestId('lifetime-distance')).toHaveTextContent('1000 mi')
  })

  it('formats distance in km when distance_unit is "km"', async () => {
    useSettingsStore.setState({
      settings: {
        distance_unit: {
          key: 'distance_unit',
          value: 'km',
          value_type: 'enum',
          group_name: 'display',
          label: 'Distance unit',
          description: null,
          is_secret: false,
        },
        currency: {
          key: 'currency',
          value: 'GBP',
          value_type: 'enum',
          group_name: 'display',
          label: 'Currency',
          description: null,
          is_secret: false,
        },
      },
      loaded: true,
      loading: false,
      error: null,
    })
    vi.spyOn(api, 'getDashboard').mockResolvedValue(fixtureSummary())

    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('lifetime-distance')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('lifetime-distance')).toHaveTextContent('1609 km')
  })

  it('renders lifetime cost using the currency setting', async () => {
    vi.spyOn(api, 'getDashboard').mockResolvedValue(fixtureSummary())
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('lifetime-cost')).toBeInTheDocument(),
    )
    // 89_900p → £899.00
    expect(screen.getByTestId('lifetime-cost')).toHaveTextContent('£899.00')
  })

  it('shows cost per mile with lifetime headline and a 30-day sub-line', async () => {
    vi.spyOn(api, 'getDashboard').mockResolvedValue(fixtureSummary())
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('lifetime-cost-per-mile')).toBeInTheDocument(),
    )
    const tile = screen.getByTestId('lifetime-cost-per-mile')
    expect(tile).toHaveTextContent('8.5 p/mi')
    expect(tile).toHaveTextContent('30d 9.2 p/mi')
  })

  it('shows a dash for cost per mile when odometer coverage is missing', async () => {
    vi.spyOn(api, 'getDashboard').mockResolvedValue({
      ...fixtureSummary(),
      cost_per_mile: { lifetime_pence: null, rolling_30d_pence: null },
    })
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('lifetime-cost-per-mile')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('lifetime-cost-per-mile')).toHaveTextContent('—')
  })

  it('shows an empty state when the dashboard is empty', async () => {
    vi.spyOn(api, 'getDashboard').mockResolvedValue({
      cars: [],
      recent_sessions: [],
      lifetime_totals: { kwh: 0, cost_pence: 0, distance_km: 0, sessions_count: 0 },
      top_locations: [],
      cost_per_mile: { lifetime_pence: null, rolling_30d_pence: null },
    })
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('dashboard-root')).toBeInTheDocument(),
    )
    expect(screen.getByText(/No cars yet/)).toBeInTheDocument()
    expect(screen.getByText(/No sessions yet/)).toBeInTheDocument()
    expect(screen.getByText(/No locations yet/)).toBeInTheDocument()
  })

  it('has a "Plan a charge" link targeting /planner', async () => {
    vi.spyOn(api, 'getDashboard').mockResolvedValue(fixtureSummary())
    render(
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('dashboard-root')).toBeInTheDocument(),
    )
    const planLink = screen.getByRole('link', { name: /plan a charge/i })
    expect(planLink).toBeInTheDocument()
    expect(planLink).toHaveAttribute('href', '/planner')
  })
})
