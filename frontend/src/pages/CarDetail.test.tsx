import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { api, type CarPayload, type CarLifetimePayload } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import CarDetail from './CarDetail'

function makeCar(over: Partial<CarPayload> = {}): CarPayload {
  return {
    id: 42, make: 'Cupra', model: 'Born', name: null,
    display_name: 'Cupra Born', vin: '········XYZ12',
    battery_kwh: 58, nominal_efficiency_mi_per_kwh: 4.2,
    provider: 'manual', provider_vehicle_id: null, active: true, ...over,
  }
}

function makeLifetime(over: Partial<CarLifetimePayload> = {}): CarLifetimePayload {
  return {
    ownership_span: { first: '2025-01-01', last: '2026-06-01' },
    total_sessions: 20,
    total_kwh: 500,
    total_cost_pence: 3500,
    lifetime_avg_p_per_kwh: 7,
    lifetime_mi_per_kwh: 4.1,
    home_public: {
      home: { spend_pence: 2000, kwh: 300, sessions: 14, avg_p_per_kwh: 6.7 },
      public: { spend_pence: 1500, kwh: 200, sessions: 6, avg_p_per_kwh: 7.5 },
    },
    ...over,
  }
}

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/cars/${id}`]}>
      <Routes>
        <Route path="/cars/:id" element={<CarDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CarDetail page', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
  })
  afterEach(() => vi.restoreAllMocks())

  it('renders lifetime tiles for an active car', async () => {
    vi.spyOn(api, 'getCar').mockResolvedValue(makeCar())
    vi.spyOn(api, 'getCarLifetime').mockResolvedValue(makeLifetime())

    renderAt('42')

    await waitFor(() => expect(screen.getByText('Cupra Born')).toBeInTheDocument())
    // Active badge
    expect(screen.getByText('Active')).toBeInTheDocument()
    // VIN (masked)
    expect(screen.getByText('········XYZ12')).toBeInTheDocument()
    // Ownership span dates
    expect(screen.getByText(/2025-01-01/)).toBeInTheDocument()
    // Sessions tile
    expect(screen.getByText('20')).toBeInTheDocument()
    // kWh tile
    expect(screen.getByText('500.0')).toBeInTheDocument()
    // Cost tile: £35.00
    expect(screen.getByText('£35.00')).toBeInTheDocument()
    // Avg p/kWh
    expect(screen.getByText('7.0p')).toBeInTheDocument()
    // "View in Insights" link
    const insightsLink = screen.getByRole('link', { name: /view in insights/i })
    expect(insightsLink).toHaveAttribute('href', '/insights?car=42')
  })

  it('shows Archived badge for inactive car', async () => {
    vi.spyOn(api, 'getCar').mockResolvedValue(makeCar({ active: false }))
    vi.spyOn(api, 'getCarLifetime').mockResolvedValue(makeLifetime())

    renderAt('42')

    await waitFor(() => expect(screen.getByText('Cupra Born')).toBeInTheDocument())
    expect(screen.getByText('Archived')).toBeInTheDocument()
  })

  it('shows — for null ownership span', async () => {
    vi.spyOn(api, 'getCar').mockResolvedValue(makeCar())
    vi.spyOn(api, 'getCarLifetime').mockResolvedValue(
      makeLifetime({ ownership_span: { first: null, last: null } })
    )

    renderAt('42')

    await waitFor(() => expect(screen.getByText('Cupra Born')).toBeInTheDocument())
    // Both first and last are null => "— to —" or just "—"
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(1)
  })

  it('shows — for null lifetime_avg_p_per_kwh', async () => {
    vi.spyOn(api, 'getCar').mockResolvedValue(makeCar())
    vi.spyOn(api, 'getCarLifetime').mockResolvedValue(
      makeLifetime({ lifetime_avg_p_per_kwh: null })
    )

    renderAt('42')

    await waitFor(() => expect(screen.getByText('Cupra Born')).toBeInTheDocument())
    // The specific Avg p/kWh tile must render "—" when the value is null.
    expect(screen.getByTestId('tile-avg-p-per-kwh')).toHaveTextContent('—')
  })

  it('shows — for null lifetime_mi_per_kwh', async () => {
    vi.spyOn(api, 'getCar').mockResolvedValue(makeCar())
    vi.spyOn(api, 'getCarLifetime').mockResolvedValue(
      makeLifetime({ lifetime_mi_per_kwh: null })
    )

    renderAt('42')

    await waitFor(() => expect(screen.getByText('Cupra Born')).toBeInTheDocument())
    // The specific mi/kWh tile must render "—" when the value is null.
    expect(screen.getByTestId('tile-mi-per-kwh')).toHaveTextContent('—')
  })
})
