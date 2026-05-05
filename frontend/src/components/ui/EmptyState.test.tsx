import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EmptyState } from './EmptyState'

describe('EmptyState', () => {
  it('renders title and body', () => {
    render(<EmptyState title="Nothing yet" body="Plug in your car" />)
    expect(screen.getByText('Nothing yet')).toBeInTheDocument()
    expect(screen.getByText('Plug in your car')).toBeInTheDocument()
  })
})
