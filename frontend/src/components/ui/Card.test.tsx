import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Card } from './Card'

describe('Card', () => {
  it('renders default variant with border + surface bg', () => {
    render(<Card data-testid="c">hi</Card>)
    const el = screen.getByTestId('c')
    expect(el.className).toMatch(/border/)
    expect(el.className).toMatch(/bg-/)
  })

  it('hero variant adds gradient glow border', () => {
    render(
      <Card data-testid="c" variant="hero">
        hi
      </Card>,
    )
    expect(screen.getByTestId('c').className).toMatch(/border-/)
  })

  it('forwards children', () => {
    render(<Card>hello</Card>)
    expect(screen.getByText('hello')).toBeInTheDocument()
  })
})
