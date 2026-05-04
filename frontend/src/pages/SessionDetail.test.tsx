import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CostBreakdown } from './SessionDetail'
import type { ChargingSessionPayload } from '@/api/client'

function makeSession(over: Partial<ChargingSessionPayload> = {}): ChargingSessionPayload {
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
    kwh_added: 21.5,
    odometer_at_session_km: 0,
    charging_type: 'dc',
    charging_mode: 'manual',
    interrupted: false,
    cost_pence: 1840,
    cost_basis: 'override_total',
    tariff_p_per_kwh: 79,
    cost_per_kwh_override_p: 79,
    total_cost_pence_override: 1840,
    location_id: null,
    location_name: null,
    location_address: null,
    user_label: null,
    charge_network: null,
    notes: null,
    source: 'manual',
    telematics_session_id: null,
    ...over,
  }
}

describe('CostBreakdown widget', () => {
  it('renders kwh × tariff product when no override is set', () => {
    render(
      <CostBreakdown
        session={makeSession({
          kwh_added: 10,
          tariff_p_per_kwh: 7.5,
          cost_pence: 75,
          cost_basis: 'home_rate',
          cost_per_kwh_override_p: null,
          total_cost_pence_override: null,
        })}
      />,
    )
    expect(screen.getByTestId('cost-breakdown')).toHaveTextContent(/10\.00 kWh/)
    expect(screen.getByTestId('cost-breakdown')).toHaveTextContent(/7\.5p/)
    expect(screen.getByTestId('cost-breakdown')).toHaveTextContent('£0.75')
    expect(screen.queryByTestId('override-receipt')).toBeNull()
  })

  it('shows the receipt-vs-computed delta when override_total is set', () => {
    render(<CostBreakdown session={makeSession()} />)
    const receipt = screen.getByTestId('override-receipt')
    expect(receipt).toHaveTextContent('£18.40') // total override
    // computed = round(21.5 * 79) = 1699 → £16.99 ; fees = £1.41
    expect(receipt).toHaveTextContent('£1.41')
  })

  it('handles missing tariff gracefully', () => {
    render(
      <CostBreakdown
        session={makeSession({
          tariff_p_per_kwh: null,
          cost_basis: 'unknown',
          cost_pence: null,
        })}
      />,
    )
    // Should not crash; basis label is rendered.
    expect(screen.getByTestId('cost-breakdown')).toHaveTextContent(/Unknown/i)
  })
})
