import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { OverTimeChart } from './OverTimeChart'

describe('OverTimeChart', () => {
  it('shows empty state with no data', () => {
    render(<OverTimeChart data={[]} granularity="daily" currency="GBP" />)
    expect(screen.getByText(/no data for this range/i)).toBeInTheDocument()
  })

  it('renders KPI totals from data', () => {
    render(
      <OverTimeChart
        data={[
          { period: '2026-06-01', spend_pence: 200, kwh: 10, sessions: 1 },
          { period: '2026-06-02', spend_pence: 300, kwh: 5, sessions: 2 },
        ]}
        granularity="daily"
        currency="GBP"
        data-testid="ot"
      />,
    )
    expect(screen.getByTestId('ot')).toBeInTheDocument()
    expect(screen.getByText(/£5\.00/)).toBeInTheDocument()
    expect(screen.getByText(/15\.0 kWh/)).toBeInTheDocument()
  })
})
