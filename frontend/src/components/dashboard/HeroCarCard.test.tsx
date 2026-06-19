import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { DashboardCarPanel } from '@/api/client'
import { HeroCarCard } from './HeroCarCard'

vi.mock('@/stores/settingsStore', async () => {
  const actual: object = await vi.importActual('@/stores/settingsStore')
  return {
    ...actual,
    useDistanceUnit: () => 'mi',
  }
})

const baseCar: DashboardCarPanel = {
  id: 1,
  make: 'Cupra',
  model: 'Born',
  battery_level: 62,
  charging_cable_connected: true,
  last_connected: new Date(Date.now() - 60_000).toISOString(),
  next_poll_at: new Date(Date.now() + 60_000).toISOString(),
  last_state: 'CHARGING',
  last_soc: 62,
  active_job_id: null,
  location_name: 'Home',
  location_address: null,
  electric_range_km: 320,
  charging_power_kw: 7.4,
  target_soc: 80,
  battery_care: null,
  max_charge_current: null,
  charging_estimated_end_at: null,
  nominal_efficiency_mi_per_kwh: 4.2,
  mileage_year: null,
}

describe('HeroCarCard', () => {
  /**
   * B7: Dashboard VIN masking.
   *
   * The DashboardCarPanel payload does not include a VIN field — VIN is
   * only present on CarPayload (the list/get endpoint) which is masked
   * server-side. The HeroCarCard therefore cannot leak a full VIN.
   * This test asserts that no 17-character alphanumeric VIN string appears
   * in the rendered card output.
   */
  it('does not render a 17-character VIN string', () => {
    render(<HeroCarCard car={baseCar} />)
    // A standard VIN is exactly 17 uppercase alphanumeric chars.
    // The card should not contain any such string.
    const container = screen.getByTestId(`car-panel-${baseCar.id}`)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/[A-HJ-NPR-Z0-9]{17}/)
  })

  it('renders battery percentage as gradient number', () => {
    render(<HeroCarCard car={baseCar} />)
    expect(screen.getByText('62')).toBeInTheDocument()
  })

  it('shows charging pill with kW when charging', () => {
    render(<HeroCarCard car={baseCar} />)
    expect(screen.getByTestId('car-charging').textContent).toMatch(/7\.4 kW/)
  })

  it('falls back gracefully when battery_level is null', () => {
    render(<HeroCarCard car={{ ...baseCar, battery_level: null }} />)
    expect(screen.getByTestId('car-soc').textContent).toContain('—')
  })

  it('omits charging pill when not charging', () => {
    render(<HeroCarCard car={{ ...baseCar, last_state: 'IDLE' }} />)
    expect(screen.queryByTestId('car-charging')).not.toBeInTheDocument()
  })

  it('shows the state label', () => {
    render(<HeroCarCard car={baseCar} />)
    expect(screen.getByTestId('state-pill').textContent).toContain('Charging')
  })

  it('renders a Battery care pill when battery_care is true', () => {
    render(<HeroCarCard car={{ ...baseCar, battery_care: true }} />)
    expect(screen.getByTestId('battery-care-pill').textContent).toContain(
      'Battery care',
    )
  })

  it('omits the Battery care pill when battery_care is falsy', () => {
    render(<HeroCarCard car={baseCar} />)
    expect(screen.queryByTestId('battery-care-pill')).not.toBeInTheDocument()
  })

  it('shows an estimated-end line while charging when set', () => {
    const end = new Date(Date.now() + 3_600_000).toISOString()
    render(
      <HeroCarCard car={{ ...baseCar, charging_estimated_end_at: end }} />,
    )
    expect(screen.getByTestId('car-est-end')).toBeInTheDocument()
  })

  it('omits the estimated-end line when not charging', () => {
    const end = new Date(Date.now() + 3_600_000).toISOString()
    render(
      <HeroCarCard
        car={{ ...baseCar, last_state: 'IDLE', charging_estimated_end_at: end }}
      />,
    )
    expect(screen.queryByTestId('car-est-end')).not.toBeInTheDocument()
  })
})
