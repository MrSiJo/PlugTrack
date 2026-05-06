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
  nominal_efficiency_mi_per_kwh: 4.2,
  mileage_year: null,
}

describe('HeroCarCard', () => {
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
})
