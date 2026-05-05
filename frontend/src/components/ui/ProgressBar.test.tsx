import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ProgressBar } from './ProgressBar'

describe('ProgressBar', () => {
  it('clamps value to [0, 100]', () => {
    const { rerender } = render(<ProgressBar data-testid="b" value={-10} />)
    let fill = screen
      .getByTestId('b')
      .querySelector('div') as HTMLDivElement
    expect(fill.style.width).toBe('0%')
    rerender(<ProgressBar data-testid="b" value={150} />)
    fill = screen.getByTestId('b').querySelector('div') as HTMLDivElement
    expect(fill.style.width).toBe('100%')
  })

  it('applies pulse animation when pulsing', () => {
    render(<ProgressBar data-testid="b" value={50} pulsing />)
    const fill = screen
      .getByTestId('b')
      .querySelector('div') as HTMLDivElement
    expect(fill.className).toMatch(/animate-pulse-soft/)
  })

  it('applies gradient fill when gradient prop is true', () => {
    render(<ProgressBar data-testid="b" value={50} gradient />)
    const fill = screen
      .getByTestId('b')
      .querySelector('div') as HTMLDivElement
    expect(fill.className).toMatch(/bg-gradient-electric/)
  })

  it('exposes ARIA progressbar with current/min/max', () => {
    render(<ProgressBar data-testid="b" value={42} />)
    const el = screen.getByRole('progressbar')
    expect(el.getAttribute('aria-valuenow')).toBe('42')
    expect(el.getAttribute('aria-valuemin')).toBe('0')
    expect(el.getAttribute('aria-valuemax')).toBe('100')
  })
})
