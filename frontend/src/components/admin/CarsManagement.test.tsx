import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api, type CarPayload } from '@/api/client'
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
    vin: '········12345',
    battery_kwh: 58,
    nominal_efficiency_mi_per_kwh: 3.5,
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
})
