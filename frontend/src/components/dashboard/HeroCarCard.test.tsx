import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { DashboardCarPanel } from '@/api/client'
import { HeroCarCard, type LatestCharge } from './HeroCarCard'

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
  // Snapshot battery — the backend sources this from the latest
  // session's end_soc.
  battery_level: 62,
  last_connected: null,
  last_soc: 62,
  nominal_efficiency_mi_per_kwh: 4.2,
  mileage_year: null,
  eved: null,
}

const baseCharge: LatestCharge = {
  date: '2026-05-27',
  end_soc: 62,
  kwh_added: 18.4,
  cost_pence: 240,
  location_name: 'Home',
}

describe('HeroCarCard', () => {
  /**
   * B7: Dashboard VIN masking.
   *
   * The DashboardCarPanel payload does not include a VIN field — VIN is
   * only present on CarPayload (the list/get endpoint) which is masked
   * server-side. The HeroCarCard therefore cannot leak a full VIN.
   */
  it('does not render a 17-character VIN string', () => {
    render(<HeroCarCard car={baseCar} latestCharge={baseCharge} />)
    const container = screen.getByTestId(`car-panel-${baseCar.id}`)
    const text = container.textContent ?? ''
    expect(text).not.toMatch(/[A-HJ-NPR-Z0-9]{17}/)
  })

  it('renders the make/model identity', () => {
    render(<HeroCarCard car={baseCar} latestCharge={baseCharge} />)
    const container = screen.getByTestId('car-panel-1')
    expect(container).toHaveTextContent('Cupra')
    expect(container).toHaveTextContent('Born')
  })

  it('renders the battery percentage as a gradient number', () => {
    render(<HeroCarCard car={baseCar} latestCharge={baseCharge} />)
    expect(screen.getByTestId('car-soc')).toHaveTextContent('62')
  })

  it('labels the battery readout "after last charge" with the latest session date', () => {
    render(<HeroCarCard car={baseCar} latestCharge={baseCharge} />)
    const label = screen.getByTestId('car-battery-label')
    expect(label).toHaveTextContent(/after last charge/i)
    // 2026-05-27 → "27 May" (short day/month, locale-dependent order).
    expect(label).toHaveTextContent(/27/)
    expect(label).toHaveTextContent(/May/)
  })

  it('shows the most-recent-charge summary: kWh added, cost, and location', () => {
    render(<HeroCarCard car={baseCar} latestCharge={baseCharge} currency="GBP" />)
    const summary = screen.getByTestId('car-last-charge')
    expect(summary).toHaveTextContent('18.4 kWh')
    expect(summary).toHaveTextContent('£2.40')
    expect(summary).toHaveTextContent('Home')
  })

  it('omits the location from the summary when the latest charge has none', () => {
    render(
      <HeroCarCard
        car={baseCar}
        latestCharge={{ ...baseCharge, location_name: null }}
      />,
    )
    const summary = screen.getByTestId('car-last-charge')
    expect(summary).toHaveTextContent('18.4 kWh')
    expect(summary).not.toHaveTextContent('At ')
  })

  it('hides the battery readout and summary when there is no latest charge', () => {
    render(<HeroCarCard car={{ ...baseCar, battery_level: null }} latestCharge={null} />)
    expect(screen.queryByTestId('car-soc')).not.toBeInTheDocument()
    expect(screen.queryByTestId('car-last-charge')).not.toBeInTheDocument()
  })

  it('does not render the removed live-sync pills/rows', () => {
    render(<HeroCarCard car={baseCar} latestCharge={baseCharge} />)
    // Charging-power pill, live state pill, battery-care pill, estimated-end row.
    expect(screen.queryByTestId('car-charging')).not.toBeInTheDocument()
    expect(screen.queryByTestId('state-pill')).not.toBeInTheDocument()
    expect(screen.queryByTestId('battery-care-pill')).not.toBeInTheDocument()
    expect(screen.queryByTestId('car-est-end')).not.toBeInTheDocument()
    // The "Seen" (last_connected) and "Sync" (next_poll_at) rows are gone.
    const container = screen.getByTestId('car-panel-1')
    expect(container).not.toHaveTextContent(/Seen/)
    expect(container).not.toHaveTextContent(/Sync/)
  })

  it('still renders the mileage-year tile when present', () => {
    render(
      <HeroCarCard
        car={{
          ...baseCar,
          mileage_year: {
            period_start_date: '2026-01-01',
            period_end_date: '2026-12-31',
            opening_odometer_km: 10_000,
            current_odometer_km: 15_000,
            annual_mileage_target_km: 16_000,
          },
        }}
        latestCharge={baseCharge}
      />,
    )
    expect(screen.getByTestId('car-mileage-year')).toBeInTheDocument()
  })

  const evedCar: DashboardCarPanel = {
    ...baseCar,
    eved: {
      rate_p_per_mile: 3.0,
      running_miles: 1000,
      running_pence: 3000,
      projected_annual_miles: 3615,
      projected_pence: 10845,
      ved_pence: 20000,
      total_due_pence: 30845,
      renewal_date: '07-31',
      low_confidence: false,
    },
  }

  it('renders the eVED tile with running, projected and combined-due figures', () => {
    render(<HeroCarCard car={evedCar} latestCharge={baseCharge} currency="GBP" />)
    const tile = screen.getByTestId('car-eved')
    expect(tile).toHaveTextContent(/eVED/i)
    expect(tile).toHaveTextContent('£30.00') // running so far
    expect(tile).toHaveTextContent('£108.45') // projected/yr
    expect(tile).toHaveTextContent('£308.45') // combined total due
    expect(tile).toHaveTextContent(/31 Jul/)
  })

  it('shows the low-confidence hint when flagged', () => {
    render(
      <HeroCarCard
        car={{ ...evedCar, eved: { ...evedCar.eved!, low_confidence: true } }}
        latestCharge={baseCharge}
      />,
    )
    expect(screen.getByTestId('car-eved')).toHaveTextContent(/settles/i)
  })

  it('hides the eVED tile when eved is null', () => {
    render(<HeroCarCard car={baseCar} latestCharge={baseCharge} />)
    expect(screen.queryByTestId('car-eved')).not.toBeInTheDocument()
  })
})
