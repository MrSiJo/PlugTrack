import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Pill } from './Pill'

describe('Pill', () => {
  it('renders children', () => {
    render(<Pill>Cariad</Pill>)
    expect(screen.getByText('Cariad')).toBeInTheDocument()
  })

  it('applies tone variant classes', () => {
    const { rerender } = render(
      <Pill data-testid="p" tone="cyan">
        x
      </Pill>,
    )
    expect(screen.getByTestId('p').className).toMatch(/cyan/)
    rerender(
      <Pill data-testid="p" tone="amber">
        x
      </Pill>,
    )
    expect(screen.getByTestId('p').className).toMatch(/amber/)
  })

  it('defaults to slate tone', () => {
    render(<Pill data-testid="p">x</Pill>)
    expect(screen.getByTestId('p').className).toMatch(/slate/)
  })
})
