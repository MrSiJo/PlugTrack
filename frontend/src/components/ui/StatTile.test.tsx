import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatTile } from './StatTile'

describe('StatTile', () => {
  it('renders label and value', () => {
    render(<StatTile label="Total kWh" value="1,243" />)
    expect(screen.getByText('Total kWh')).toBeInTheDocument()
    expect(screen.getByText('1,243')).toBeInTheDocument()
  })

  it('renders subline when provided', () => {
    render(<StatTile label="x" value="1" sub="last week" />)
    expect(screen.getByText('last week')).toBeInTheDocument()
  })

  it('renders without subline when omitted', () => {
    const { container } = render(<StatTile label="x" value="1" />)
    expect(container.querySelectorAll('p').length).toBeLessThanOrEqual(2)
  })
})
