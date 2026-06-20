import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CarFields } from './CarFields'
import type { CarCreateRequest } from '@/api/client'

function makeDraft(over: Partial<CarCreateRequest> = {}): CarCreateRequest {
  return {
    make: 'Cupra',
    model: 'Born',
    battery_kwh: 58,
    nominal_efficiency_mi_per_kwh: 3.5,
    ...over,
  }
}

describe('CarFields', () => {
  it('renders Max AC kW input', () => {
    render(<CarFields draft={makeDraft()} setDraft={vi.fn()} />)
    expect(screen.getByText(/Max AC kW/i)).toBeInTheDocument()
  })

  it('renders Max DC kW input', () => {
    render(<CarFields draft={makeDraft()} setDraft={vi.fn()} />)
    expect(screen.getByText(/Max DC kW/i)).toBeInTheDocument()
  })

  it('shows max_ac_kw value when set in draft', () => {
    render(<CarFields draft={makeDraft({ max_ac_kw: 11 })} setDraft={vi.fn()} />)
    const acInput = screen.getByPlaceholderText(/3-phase Type-2/i) as HTMLInputElement
    expect(acInput.value).toBe('11')
  })

  it('shows max_dc_kw value when set in draft', () => {
    render(<CarFields draft={makeDraft({ max_dc_kw: 160 })} setDraft={vi.fn()} />)
    const dcInput = screen.getByPlaceholderText(/CCS fast-charge/i) as HTMLInputElement
    expect(dcInput.value).toBe('160')
  })

  it('Max AC kW input is empty when draft.max_ac_kw is null', () => {
    render(<CarFields draft={makeDraft({ max_ac_kw: null })} setDraft={vi.fn()} />)
    const acInput = screen.getByPlaceholderText(/3-phase Type-2/i) as HTMLInputElement
    expect(acInput.value).toBe('')
  })

  it('Max DC kW input is empty when draft.max_dc_kw is null', () => {
    render(<CarFields draft={makeDraft({ max_dc_kw: null })} setDraft={vi.fn()} />)
    const dcInput = screen.getByPlaceholderText(/CCS fast-charge/i) as HTMLInputElement
    expect(dcInput.value).toBe('')
  })

  it('Max AC kW input has step="any" so whole numbers and decimals are both valid', () => {
    render(<CarFields draft={makeDraft()} setDraft={vi.fn()} />)
    const acInput = screen.getByPlaceholderText(/3-phase Type-2/i) as HTMLInputElement
    expect(acInput.step).toBe('any')
  })

  it('Max DC kW input has step="any" so whole numbers like 165 are accepted', () => {
    render(<CarFields draft={makeDraft()} setDraft={vi.fn()} />)
    const dcInput = screen.getByPlaceholderText(/CCS fast-charge/i) as HTMLInputElement
    expect(dcInput.step).toBe('any')
  })
})
