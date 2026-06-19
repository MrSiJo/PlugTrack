import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HomePublicSplit } from './HomePublicSplit'

describe('HomePublicSplit', () => {
  it('shows empty state when both buckets are empty', () => {
    const blank = { spend_pence: 0, kwh: 0, sessions: 0, avg_p_per_kwh: null }
    render(<HomePublicSplit split={{ home: blank, public: blank }} currency="GBP" />)
    expect(screen.getByText(/no data for this range/i)).toBeInTheDocument()
  })

  it('renders home and public spend', () => {
    render(
      <HomePublicSplit
        split={{
          home: { spend_pence: 200, kwh: 10, sessions: 1, avg_p_per_kwh: 20 },
          public: { spend_pence: 1500, kwh: 30, sessions: 1, avg_p_per_kwh: 50 },
        }}
        currency="GBP"
      />,
    )
    expect(screen.getByText(/£2\.00/)).toBeInTheDocument()
    expect(screen.getByText(/£15\.00/)).toBeInTheDocument()
  })
})
