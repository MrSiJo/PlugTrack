import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SpendChart } from './SpendChart'

describe('SpendChart', () => {
  it('renders an empty-state message when given no data', () => {
    render(<SpendChart data={[]} currency="GBP" />)
    expect(screen.getByText(/no spend yet/i)).toBeInTheDocument()
  })

  it('renders a chart container when given data', () => {
    render(
      <SpendChart
        data={[
          { date: '2026-05-01', cost_pence: 400 },
          { date: '2026-05-02', cost_pence: 600 },
        ]}
        currency="GBP"
        data-testid="chart"
      />,
    )
    expect(screen.getByTestId('chart')).toBeInTheDocument()
  })

  it('renders the total spend in the header', () => {
    render(
      <SpendChart
        data={[
          { date: '2026-05-01', cost_pence: 400 },
          { date: '2026-05-02', cost_pence: 600 },
        ]}
        currency="GBP"
      />,
    )
    expect(screen.getByText(/£10\.00/)).toBeInTheDocument()
  })
})
