import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PageHeader } from './PageHeader'

describe('PageHeader', () => {
  it('renders title', () => {
    render(<PageHeader title="Sessions" />)
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe(
      'Sessions',
    )
  })

  it('renders subtitle and actions', () => {
    render(
      <PageHeader title="x" subtitle="sub" actions={<button>act</button>} />,
    )
    expect(screen.getByText('sub')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'act' })).toBeInTheDocument()
  })
})
