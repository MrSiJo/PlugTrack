import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EfficiencyChart } from './EfficiencyChart'

describe('EfficiencyChart', () => {
  it('shows empty state when every point is null', () => {
    render(
      <EfficiencyChart
        data={[{ period: '2026-06-01', observed_mi_per_kwh: null, cost_per_mile_p: null }]}
      />,
    )
    expect(screen.getByText(/no odometer data/i)).toBeInTheDocument()
  })

  it('renders a chart container when a point has data', () => {
    render(
      <EfficiencyChart
        data={[{ period: '2026-06-01', observed_mi_per_kwh: 4.1, cost_per_mile_p: 6.2 }]}
        data-testid="eff"
      />,
    )
    expect(screen.getByTestId('eff')).toBeInTheDocument()
  })
})
