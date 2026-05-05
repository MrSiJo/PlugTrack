import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { GradientNumber } from './GradientNumber'

describe('GradientNumber', () => {
  it('renders the value with gradient text class', () => {
    render(<GradientNumber data-testid="gn">62%</GradientNumber>)
    const el = screen.getByTestId('gn')
    expect(el.textContent).toBe('62%')
    expect(el.className).toMatch(/text-gradient-electric/)
  })

  it('applies size variants', () => {
    const { rerender } = render(
      <GradientNumber data-testid="gn" size="sm">
        1
      </GradientNumber>,
    )
    expect(screen.getByTestId('gn').className).toMatch(/text-lg/)
    rerender(
      <GradientNumber data-testid="gn" size="xl">
        1
      </GradientNumber>,
    )
    expect(screen.getByTestId('gn').className).toMatch(/text-5xl/)
  })

  it('forwards arbitrary class names through cn()', () => {
    render(
      <GradientNumber data-testid="gn" className="custom">
        1
      </GradientNumber>,
    )
    expect(screen.getByTestId('gn').className).toMatch(/custom/)
  })
})
