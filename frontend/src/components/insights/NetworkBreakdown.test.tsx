import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { NetworkBreakdown } from './NetworkBreakdown'

describe('NetworkBreakdown', () => {
  it('shows empty state with no rows', () => {
    render(<NetworkBreakdown rows={[]} currency="GBP" />)
    expect(screen.getByText(/no data for this range/i)).toBeInTheDocument()
  })

  it('lists networks', () => {
    render(
      <NetworkBreakdown
        rows={[{ network: 'Tesla', spend_pence: 1500, kwh: 30, sessions: 1, avg_p_per_kwh: 50 }]}
        currency="GBP"
      />,
    )
    expect(screen.getByText('Tesla')).toBeInTheDocument()
  })
})
