import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CarPicker from './CarPicker'
import type { CarPayload } from '@/api/client'

function makeCar(over: Partial<CarPayload> = {}): CarPayload {
  return {
    id: 1,
    make: 'Cupra',
    model: 'Born',
    name: null,
    display_name: 'Cupra Born',
    vin: null,
    battery_kwh: 59,
    nominal_efficiency_mi_per_kwh: 3.5,
    max_ac_kw: null,
    max_dc_kw: null,
    provider: 'cupra',
    provider_vehicle_id: null,
    active: true,
    ...over,
  }
}

const activeCars: CarPayload[] = [
  makeCar({ id: 1, display_name: 'Cupra Born', active: true }),
  makeCar({ id: 2, display_name: 'Tesla Model 3', active: true }),
]

const archivedCars: CarPayload[] = [
  makeCar({ id: 3, display_name: 'Old Nissan Leaf', active: false }),
  makeCar({ id: 4, display_name: 'Very Old Polo', active: false }),
]

const allCars = [...activeCars, ...archivedCars]

describe('CarPicker — active cars visible', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows active cars in the open picker', async () => {
    const user = userEvent.setup()
    render(
      <CarPicker
        value={null}
        onChange={vi.fn()}
        cars={activeCars}
        allowAll
      />,
    )

    // Open the picker
    await user.click(screen.getByRole('combobox'))

    expect(screen.getByRole('option', { name: 'Cupra Born' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Tesla Model 3' })).toBeInTheDocument()
  })

  it('shows "All cars" option when allowAll is set', async () => {
    const user = userEvent.setup()
    render(
      <CarPicker
        value={null}
        onChange={vi.fn()}
        cars={activeCars}
        allowAll
      />,
    )

    await user.click(screen.getByRole('combobox'))
    expect(screen.getByRole('option', { name: 'All cars' })).toBeInTheDocument()
  })

  it('does not show "All cars" option when allowAll is false', async () => {
    const user = userEvent.setup()
    render(
      <CarPicker
        value={null}
        onChange={vi.fn()}
        cars={activeCars}
      />,
    )

    await user.click(screen.getByRole('combobox'))
    expect(screen.queryByRole('option', { name: 'All cars' })).not.toBeInTheDocument()
  })
})

describe('CarPicker — archived cars hidden by default', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('does not show archived cars by default (without reveal)', async () => {
    const user = userEvent.setup()
    render(
      <CarPicker
        value={null}
        onChange={vi.fn()}
        cars={allCars}
        includeArchived
        allowAll
      />,
    )

    await user.click(screen.getByRole('combobox'))

    // Active cars visible
    expect(screen.getByRole('option', { name: 'Cupra Born' })).toBeInTheDocument()
    // Archived cars NOT visible until reveal
    expect(screen.queryByRole('option', { name: /Old Nissan Leaf \(archived\)/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Very Old Polo \(archived\)/i })).not.toBeInTheDocument()
  })

  it('shows the "Show archived (N)" reveal button when archived cars exist', async () => {
    const user = userEvent.setup()
    render(
      <CarPicker
        value={null}
        onChange={vi.fn()}
        cars={allCars}
        includeArchived
        allowAll
      />,
    )

    await user.click(screen.getByRole('combobox'))
    expect(screen.getByText(/Show archived \(2\)/i)).toBeInTheDocument()
  })

  it('clicking the reveal shows archived cars labelled "(archived)"', async () => {
    const user = userEvent.setup()
    render(
      <CarPicker
        value={null}
        onChange={vi.fn()}
        cars={allCars}
        includeArchived
        allowAll
      />,
    )

    await user.click(screen.getByRole('combobox'))
    await user.click(screen.getByText(/Show archived \(2\)/i))

    // Archived entries now visible with the suffix
    expect(screen.getByRole('option', { name: 'Old Nissan Leaf (archived)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Very Old Polo (archived)' })).toBeInTheDocument()
  })

  it('does not show archived cars at all when includeArchived is false', async () => {
    const user = userEvent.setup()
    render(
      <CarPicker
        value={null}
        onChange={vi.fn()}
        cars={allCars}
        allowAll
      />,
    )

    await user.click(screen.getByRole('combobox'))

    // No archived reveal button
    expect(screen.queryByText(/Show archived/i)).not.toBeInTheDocument()
    // No archived cars
    expect(screen.queryByRole('option', { name: /archived/i })).not.toBeInTheDocument()
  })
})

describe('CarPicker — typing filters', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('typing narrows the visible options to matching cars', async () => {
    const user = userEvent.setup()
    render(
      <CarPicker
        value={null}
        onChange={vi.fn()}
        cars={activeCars}
        allowAll
      />,
    )

    await user.click(screen.getByRole('combobox'))
    // cmdk renders the input with data-slot="command-input"; query by placeholder
    const searchInput = screen.getByPlaceholderText('Search cars…')
    await user.type(searchInput, 'Tesla')

    expect(screen.getByRole('option', { name: 'Tesla Model 3' })).toBeInTheDocument()
    // Cupra Born should be filtered out
    expect(screen.queryByRole('option', { name: 'Cupra Born' })).not.toBeInTheDocument()
  })
})

describe('CarPicker — selecting calls onChange', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('selecting an active car calls onChange with its id', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <CarPicker
        value={null}
        onChange={onChange}
        cars={activeCars}
        allowAll
      />,
    )

    await user.click(screen.getByRole('combobox'))
    await user.click(screen.getByRole('option', { name: 'Tesla Model 3' }))

    expect(onChange).toHaveBeenCalledWith(2)
  })

  it('selecting "All cars" calls onChange with null', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <CarPicker
        value={2}
        onChange={onChange}
        cars={activeCars}
        allowAll
      />,
    )

    await user.click(screen.getByRole('combobox'))
    await user.click(screen.getByRole('option', { name: 'All cars' }))

    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('selecting an archived car calls onChange with its id', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <CarPicker
        value={null}
        onChange={onChange}
        cars={allCars}
        includeArchived
      />,
    )

    await user.click(screen.getByRole('combobox'))
    await user.click(screen.getByText(/Show archived \(2\)/i))
    await user.click(screen.getByRole('option', { name: 'Old Nissan Leaf (archived)' }))

    expect(onChange).toHaveBeenCalledWith(3)
  })
})

describe('CarPicker — trigger label', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows "All cars" as the trigger label when value is null and allowAll', () => {
    render(
      <CarPicker
        value={null}
        onChange={vi.fn()}
        cars={activeCars}
        allowAll
      />,
    )

    expect(screen.getByRole('combobox')).toHaveTextContent('All cars')
  })

  it('shows the selected car display_name in the trigger', () => {
    render(
      <CarPicker
        value={1}
        onChange={vi.fn()}
        cars={activeCars}
        allowAll
      />,
    )

    expect(screen.getByRole('combobox')).toHaveTextContent('Cupra Born')
  })

  it('shows the archived car name (with suffix) in the trigger when selected', () => {
    render(
      <CarPicker
        value={3}
        onChange={vi.fn()}
        cars={allCars}
        includeArchived
      />,
    )

    expect(screen.getByRole('combobox')).toHaveTextContent('Old Nissan Leaf (archived)')
  })
})
