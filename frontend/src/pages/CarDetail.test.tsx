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
    max_ac_kw: null, max_dc_kw: null,
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
    estimated_usable_kwh: null,
    seasonal_range_span: null,
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

  // ---------------------------------------------------------------------------
  // Battery health & seasonal range tile
  // ---------------------------------------------------------------------------

  it('renders battery-health card for active car with estimated_usable_kwh', async () => {
    // car.battery_kwh = 58; estimated = 54.3 → degradation = (1 - 54.3/58)*100 = 6.4%
    vi.spyOn(api, 'getCar').mockResolvedValue(makeCar({ battery_kwh: 58 }))
    vi.spyOn(api, 'getCarLifetime').mockResolvedValue(
      makeLifetime({
        estimated_usable_kwh: 54.3,
        seasonal_range_span: { min_km: 200, max_km: 350, avg_km: 280 },
      }),
    )

    renderAt('42')

    await waitFor(() => expect(screen.getByText('Cupra Born')).toBeInTheDocument())

    // Section heading
    expect(screen.getByText('Battery health & seasonal range')).toBeInTheDocument()

    // Estimated usable capacity
    expect(screen.getByTestId('tile-estimated-usable')).toHaveTextContent('54.3 kWh')

    // Indicative caveat text
    expect(screen.getByTestId('tile-estimated-usable-caveat')).toBeInTheDocument()

    // Degradation hint (6.4%)
    expect(screen.getByTestId('tile-degradation')).toHaveTextContent('6.4%')

    // Seasonal range span — values are mi by default (km / 1.609344)
    // min_km=200 → ~124.3 mi; max_km=350 → ~217.5 mi
    const spanEl = screen.getByTestId('tile-seasonal-span')
    expect(spanEl).toHaveTextContent(/\d+/)
    // Both min and max present — should show a range with "–"
    expect(spanEl.textContent).toMatch(/–/)
  })

  it('renders battery-health card for archived car', async () => {
    vi.spyOn(api, 'getCar').mockResolvedValue(makeCar({ active: false, battery_kwh: 77 }))
    vi.spyOn(api, 'getCarLifetime').mockResolvedValue(
      makeLifetime({
        estimated_usable_kwh: 72.0,
        seasonal_range_span: null,
      }),
    )

    renderAt('42')

    await waitFor(() => expect(screen.getByText('Archived')).toBeInTheDocument())
    expect(screen.getByText('Battery health & seasonal range')).toBeInTheDocument()
    expect(screen.getByTestId('tile-estimated-usable')).toHaveTextContent('72.0 kWh')
    // seasonal span is null → shows —
    expect(screen.getByTestId('tile-seasonal-span')).toHaveTextContent('—')
  })

  it('hides battery-health card when estimated_usable_kwh is null', async () => {
    vi.spyOn(api, 'getCar').mockResolvedValue(makeCar())
    vi.spyOn(api, 'getCarLifetime').mockResolvedValue(
      makeLifetime({ estimated_usable_kwh: null, seasonal_range_span: null }),
    )

    renderAt('42')

    await waitFor(() => expect(screen.getByText('Cupra Born')).toBeInTheDocument())
    expect(screen.queryByText('Battery health & seasonal range')).not.toBeInTheDocument()
    expect(screen.queryByTestId('tile-estimated-usable')).not.toBeInTheDocument()
  })

  it('shows — for degradation when estimated_usable_kwh exceeds battery_kwh', async () => {
    // Estimated > nominal → degrade is negative; guard → show "—" or ~0%
    vi.spyOn(api, 'getCar').mockResolvedValue(makeCar({ battery_kwh: 58 }))
    vi.spyOn(api, 'getCarLifetime').mockResolvedValue(
      makeLifetime({ estimated_usable_kwh: 60, seasonal_range_span: null }),
    )

    renderAt('42')

    await waitFor(() => expect(screen.getByText('Battery health & seasonal range')).toBeInTheDocument())
    const deg = screen.getByTestId('tile-degradation')
    // Should show "—" (or ≈0%) rather than a negative percentage
    const text = deg.textContent ?? ''
    const isNonNegative = text === '—' || text === '~0%' || (parseFloat(text) >= 0)
    expect(isNonNegative).toBe(true)
  })

  it('shows — for seasonal range when min_km or max_km is null', async () => {
    vi.spyOn(api, 'getCar').mockResolvedValue(makeCar())
    vi.spyOn(api, 'getCarLifetime').mockResolvedValue(
      makeLifetime({
        estimated_usable_kwh: 54,
        seasonal_range_span: { min_km: null, max_km: 350, avg_km: null },
      }),
    )

    renderAt('42')

    await waitFor(() => expect(screen.getByText('Battery health & seasonal range')).toBeInTheDocument())
    // When either min or max is null, show — for the span
    expect(screen.getByTestId('tile-seasonal-span')).toHaveTextContent('—')
  })
})
