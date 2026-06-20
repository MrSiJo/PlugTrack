import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ApiError, api, type CarPayload } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import { CarsManagement } from './CarsManagement'

// Mock api so no real fetches happen
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      getCars: vi.fn(),
      createCar: vi.fn(),
      updateCar: vi.fn(),
      deleteCar: vi.fn(),
      revealCarVin: vi.fn(),
      getCarMileage: vi.fn(),
      getSettings: vi.fn().mockResolvedValue({}),
    },
  }
})

function makeCar(over: Partial<CarPayload> = {}): CarPayload {
  return {
    id: 1,
    make: 'Cupra',
    model: 'Born',
    name: null,
    display_name: 'Cupra Born',
    vin: '········12345',
    battery_kwh: 58,
    nominal_efficiency_mi_per_kwh: 3.5,
    max_ac_kw: null,
    max_dc_kw: null,
    provider: 'cupra_connect',
    provider_vehicle_id: 'VSSZZZK1ZNP123456',
    active: true,
    ...over,
  }
}

describe('CarsManagement', () => {
  beforeEach(() => {
    vi.mocked(api.getCarMileage).mockResolvedValue({
      enabled: false,
      current_period: null,
      history: [],
    })
    // Seed settings store so CarMileageSection's useDistanceUnit doesn't trigger real fetch
    useSettingsStore.setState({ settings: {}, loaded: true, loading: false, error: null })
  })

  afterEach(() => {
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  it('renders car rows', async () => {
    vi.mocked(api.getCars).mockResolvedValue([makeCar({ id: 1 })])

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getAllByTestId('admin-car-row').length).toBe(1),
    )
    expect(screen.getByText('Cupra Born')).toBeInTheDocument()
  })

  it('clicking "Add car" renders CarFields', async () => {
    vi.mocked(api.getCars).mockResolvedValue([])

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.queryByText('Loading…')).not.toBeInTheDocument(),
    )

    fireEvent.click(screen.getByRole('button', { name: /add car/i }))

    // CarFields renders a "Make" label
    expect(screen.getByText('Make')).toBeInTheDocument()
    // VIN field (full label text)
    expect(screen.getByText(/VIN \(optional, encrypted at rest\)/i)).toBeInTheDocument()
  })

  it('clicking Edit calls revealCarVin and the VIN input shows the full value', async () => {
    vi.mocked(api.getCars).mockResolvedValue([makeCar({ id: 7, vin: '········12345' })])
    vi.mocked(api.revealCarVin).mockResolvedValue({ vin: 'VSSZZZK1ZNP123456' })

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-edit-car-7')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-edit-car-7'))
    })

    expect(api.revealCarVin).toHaveBeenCalledWith(7)

    // After reveal, the VIN input should show the full plaintext VIN
    await waitFor(() => {
      const vinInput = screen.getByLabelText(/VIN \(optional, encrypted at rest\)/i) as HTMLInputElement
      expect(vinInput.value).toBe('VSSZZZK1ZNP123456')
    })
  })

  it('Delete calls api.deleteCar after confirm', async () => {
    vi.mocked(api.getCars).mockResolvedValue([makeCar({ id: 3 })])
    vi.mocked(api.deleteCar).mockResolvedValue(undefined)
    vi.stubGlobal('confirm', vi.fn(() => true))

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-delete-car-3')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-delete-car-3'))
    })

    expect(api.deleteCar).toHaveBeenCalledWith(3)
  })

  it('Delete does NOT call api.deleteCar when confirm is cancelled', async () => {
    vi.mocked(api.getCars).mockResolvedValue([makeCar({ id: 3 })])
    vi.stubGlobal('confirm', vi.fn(() => false))

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-delete-car-3')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-delete-car-3'))
    })

    expect(api.deleteCar).not.toHaveBeenCalled()
  })

  it('clears VIN field when revealCarVin fails (masked sentinel must not be saved)', async () => {
    vi.mocked(api.getCars).mockResolvedValue([makeCar({ id: 5, vin: '········12345' })])
    vi.mocked(api.revealCarVin).mockRejectedValue(new Error('network error'))

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-edit-car-5')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-edit-car-5'))
    })

    // After a failed reveal the VIN input must be empty — NOT the masked value.
    await waitFor(() => {
      const vinInput = screen.getByLabelText(/VIN \(optional, encrypted at rest\)/i) as HTMLInputElement
      expect(vinInput.value).toBe('')
    })
  })

  it('does NOT leak car A VIN into car B edit when A reveal resolves after switching to B', async () => {
    vi.mocked(api.getCars).mockResolvedValue([
      makeCar({ id: 10, vin: '········AAAAA', make: 'Car', model: 'A', display_name: 'Car A' }),
      makeCar({ id: 20, vin: '········BBBBB', make: 'Car', model: 'B', display_name: 'Car B' }),
    ])

    // Deferred promise for car A — we control when it resolves.
    let resolveCarA!: (v: { vin: string }) => void
    const carAReveal = new Promise<{ vin: string }>((res) => {
      resolveCarA = res
    })
    // Car B resolves immediately with its own VIN.
    vi.mocked(api.revealCarVin).mockImplementation((id) => {
      if (id === 10) return carAReveal
      return Promise.resolve({ vin: 'FULL-VIN-BBBBB' })
    })

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    // Wait for both edit buttons to appear.
    await waitFor(() =>
      expect(screen.getByTestId('admin-edit-car-10')).toBeInTheDocument(),
    )
    await waitFor(() =>
      expect(screen.getByTestId('admin-edit-car-20')).toBeInTheDocument(),
    )

    // Click Edit on car A — its reveal is still pending.
    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-edit-car-10'))
    })

    // Switch to car B before car A resolves; car B's reveal is immediate.
    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-edit-car-20'))
    })

    // Wait for car B's form + VIN to be visible.
    await waitFor(() => {
      const vinInput = screen.getByLabelText(
        /VIN \(optional, encrypted at rest\)/i,
      ) as HTMLInputElement
      expect(vinInput.value).toBe('FULL-VIN-BBBBB')
    })

    // Now resolve car A's deferred reveal — this is the late write that must be dropped.
    await act(async () => {
      resolveCarA({ vin: 'FULL-VIN-AAAAA' })
    })

    // The VIN input must still show car B's VIN, NOT car A's.
    const vinInput = screen.getByLabelText(
      /VIN \(optional, encrypted at rest\)/i,
    ) as HTMLInputElement
    expect(vinInput.value).toBe('FULL-VIN-BBBBB')
    expect(vinInput.value).not.toBe('FULL-VIN-AAAAA')
  })

  // ── New tests for Task 8 ────────────────────────────────────────────────────

  it('shows Archived pill for inactive car and Restore button', async () => {
    vi.mocked(api.getCars).mockResolvedValue([
      makeCar({ id: 2, active: false, display_name: 'Archived Car' }),
    ])

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getAllByTestId('admin-car-row').length).toBe(1),
    )

    expect(screen.getByText('Archived')).toBeInTheDocument()
    expect(screen.getByTestId('admin-restore-car-2')).toBeInTheDocument()
    expect(screen.queryByTestId('admin-archive-car-2')).not.toBeInTheDocument()
  })

  it('shows Archive button for active car, no Restore', async () => {
    vi.mocked(api.getCars).mockResolvedValue([
      makeCar({ id: 1, active: true, display_name: 'Active Car' }),
    ])

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getAllByTestId('admin-car-row').length).toBe(1),
    )

    expect(screen.getByTestId('admin-archive-car-1')).toBeInTheDocument()
    expect(screen.queryByTestId('admin-restore-car-1')).not.toBeInTheDocument()
    expect(screen.queryByText('Archived')).not.toBeInTheDocument()
  })

  it('clicking Archive calls updateCar with active: false', async () => {
    vi.mocked(api.getCars).mockResolvedValue([makeCar({ id: 4, active: true })])
    vi.mocked(api.updateCar).mockResolvedValue(makeCar({ id: 4, active: false }))

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-archive-car-4')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-archive-car-4'))
    })

    expect(api.updateCar).toHaveBeenCalledWith(4, { active: false })
  })

  it('clicking Restore calls updateCar with active: true', async () => {
    vi.mocked(api.getCars).mockResolvedValue([makeCar({ id: 5, active: false })])
    vi.mocked(api.updateCar).mockResolvedValue(makeCar({ id: 5, active: true }))

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-restore-car-5')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-restore-car-5'))
    })

    expect(api.updateCar).toHaveBeenCalledWith(5, { active: true })
  })

  it('409 delete shows server detail message', async () => {
    vi.mocked(api.getCars).mockResolvedValue([makeCar({ id: 6 })])
    vi.mocked(api.deleteCar).mockRejectedValue(
      new ApiError(409, 'This car has 3 charges. Archive it instead of deleting.', {
        detail: 'This car has 3 charges. Archive it instead of deleting.',
      }),
    )
    vi.stubGlobal('confirm', vi.fn(() => true))

    render(
      <MemoryRouter>
        <CarsManagement />
      </MemoryRouter>,
    )

    await waitFor(() =>
      expect(screen.getByTestId('admin-delete-car-6')).toBeInTheDocument(),
    )

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-delete-car-6'))
    })

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('This car has 3 charges'),
    )
  })
})
