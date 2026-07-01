import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { BatteryHealth } from '@/api/client'
import { BatteryHealthCard } from './BatteryHealthCard'

const BASE: BatteryHealth = {
  estimated_usable_kwh: 61.49,
  nominal_kwh: 59.0,
  soh_pct: 100,
  soh_pct_raw: 104,
  qualifying_count: 5,
  low_confidence: false,
}

describe('BatteryHealthCard', () => {
  it('renders nothing when data is null', () => {
    const { container } = render(<BatteryHealthCard data={null} data-testid="bhc" />)
    expect(container).toBeEmptyDOMElement()
    expect(screen.queryByTestId('bhc')).not.toBeInTheDocument()
  })

  it('shows headline percentage and the no-degradation caption when soh_pct_raw >= 100', () => {
    render(<BatteryHealthCard data={BASE} data-testid="bhc" />)
    expect(screen.getByTestId('bhc')).toBeInTheDocument()
    expect(screen.getByText('~100%')).toBeInTheDocument()
    expect(screen.getByText(/estimated battery health/i)).toBeInTheDocument()
    expect(screen.getByText(/no measurable degradation/i)).toBeInTheDocument()
  })

  it('shows the usable vs nominal sub-line', () => {
    render(<BatteryHealthCard data={BASE} data-testid="bhc" />)
    expect(
      screen.getByText(/≈61\.49 kWh usable vs 59 kWh nominal/i),
    ).toBeInTheDocument()
  })

  it('does not show the no-degradation caption below 100% raw', () => {
    render(
      <BatteryHealthCard
        data={{ ...BASE, soh_pct: 93, soh_pct_raw: 93 }}
        data-testid="bhc"
      />,
    )
    expect(screen.getByText('~93%')).toBeInTheDocument()
    expect(screen.queryByText(/no measurable degradation/i)).not.toBeInTheDocument()
  })

  it('shows the low-confidence caption with plural qualifying charges', () => {
    render(
      <BatteryHealthCard
        data={{ ...BASE, low_confidence: true, qualifying_count: 2 }}
        data-testid="bhc"
      />,
    )
    expect(
      screen.getByText(/low confidence — based on 2 qualifying charges/i),
    ).toBeInTheDocument()
  })

  it('shows the low-confidence caption with singular qualifying charge', () => {
    render(
      <BatteryHealthCard
        data={{ ...BASE, low_confidence: true, qualifying_count: 1 }}
        data-testid="bhc"
      />,
    )
    expect(
      screen.getByText(/low confidence — based on 1 qualifying charge$/i),
    ).toBeInTheDocument()
  })
})
