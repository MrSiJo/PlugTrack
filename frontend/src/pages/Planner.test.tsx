import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import Planner from './Planner'
import { ApiError, api, type CarPayload, type ScenarioPlanResponse } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeCar(over: Partial<CarPayload> = {}): CarPayload {
  return {
    id: 1,
    make: 'Cupra',
    model: 'Born',
    name: null,
    display_name: 'Cupra Born',
    vin: null,
    battery_kwh: 77,
    nominal_efficiency_mi_per_kwh: 3.5,
    max_ac_kw: 11,
    max_dc_kw: 100,
    provider: 'cupra_connect',
    provider_vehicle_id: null,
    active: true,
    ...over,
  }
}

function makePlan(over: Partial<ScenarioPlanResponse> = {}): ScenarioPlanResponse {
  return {
    car_id: 1,
    start_soc: 60,
    target_soc: 80,
    battery_kwh: 77,
    loss_factor: 0.9,
    home_rate_p_per_kwh: 28.34,
    is_free: false,
    rows: [
      {
        label: 'Home AC (from your history)',
        power_kw: 7.2,
        minutes: 499,
        source_tag: 'history',
        finish_at: '07:15',
        nights: 2,
        note: null,
      },
      {
        label: 'Home AC (spec max)',
        power_kw: 11,
        minutes: 327,
        source_tag: 'spec',
        finish_at: '05:27',
        nights: 1,
        note: null,
      },
      {
        label: 'DC rapid (curve-derived)',
        power_kw: 85,
        minutes: 42,
        source_tag: 'curve',
        finish_at: null,
        nights: null,
        note: null,
      },
      {
        label: 'Custom power',
        power_kw: 7,
        minutes: 512,
        source_tag: 'modelled',
        finish_at: null,
        nights: null,
        note: 'car-limited to ~7 kW',
      },
    ],
    ...over,
  }
}

// ---------------------------------------------------------------------------
// Render helper
// ---------------------------------------------------------------------------

function renderPlanner() {
  return render(
    <MemoryRouter initialEntries={['/planner']}>
      <Planner />
    </MemoryRouter>,
  )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Planner page', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
  })

  it('renders the page heading', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    expect(screen.getByText('Charge Planner')).toBeInTheDocument()
  })

  it('renders a table row for each scenario row with label, power, and formatted time', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    // Wait for plan to load
    const table = await screen.findByTestId('plan-table')
    expect(table).toBeInTheDocument()

    // Row 1: history — 499 min = 8h 19m
    const row0 = screen.getByTestId('plan-row-0')
    expect(row0).toHaveTextContent('Home AC (from your history)')
    expect(row0).toHaveTextContent('7.2 kW')
    expect(row0).toHaveTextContent('8h 19m')

    // Row 2: spec — 327 min = 5h 27m
    const row1 = screen.getByTestId('plan-row-1')
    expect(row1).toHaveTextContent('11 kW')
    expect(row1).toHaveTextContent('5h 27m')

    // Row 3: curve — 42 min
    const row2 = screen.getByTestId('plan-row-2')
    expect(row2).toHaveTextContent('42m')
  })

  it('shows the source_tag pill with the correct label for each row', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    await screen.findByTestId('plan-table')

    // history → "from your history"
    const row0 = screen.getByTestId('plan-row-0')
    expect(row0).toHaveTextContent('from your history')

    // spec → "spec"
    const row1 = screen.getByTestId('plan-row-1')
    expect(row1).toHaveTextContent('spec')

    // curve → "curve-derived"
    const row2 = screen.getByTestId('plan-row-2')
    expect(row2).toHaveTextContent('curve-derived')

    // modelled → "modelled"
    const row3 = screen.getByTestId('plan-row-3')
    expect(row3).toHaveTextContent('modelled')
  })

  it('shows finish_at and nights for AC window rows', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    await screen.findByTestId('plan-table')

    // Row 0 has finish_at='07:15' and nights=2
    const row0 = screen.getByTestId('plan-row-0')
    expect(row0).toHaveTextContent('07:15')
    expect(row0).toHaveTextContent('2')

    // Row 2 (DC curve) has no finish_at / nights — should show "—"
    const row2 = screen.getByTestId('plan-row-2')
    expect(row2).toHaveTextContent('—')
  })

  it('shows the note when a row has a note', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    await screen.findByTestId('plan-table')

    // Row 3 has note: 'car-limited to ~7 kW'
    const row3 = screen.getByTestId('plan-row-3')
    expect(row3).toHaveTextContent('car-limited to ~7 kW')
  })

  it('shows an error when the API call fails', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockRejectedValue(
      new ApiError(404, 'Car not found', null),
    )

    renderPlanner()

    const err = await screen.findByTestId('plan-error')
    expect(err).toHaveTextContent('Car not found')
  })

  it('shows a loading state while the plan is being fetched', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    // Never resolves to keep loading state visible
    vi.spyOn(api, 'getChargePlan').mockReturnValue(new Promise(() => {}))

    renderPlanner()

    // Cars load, then plan starts loading
    await waitFor(() => {
      expect(screen.getByTestId('plan-loading')).toBeInTheDocument()
    })
  })

  it('calls getChargePlan with carId, startSoc, targetSoc on mount', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar({ id: 42 })])
    const getChargePlan = vi
      .spyOn(api, 'getChargePlan')
      .mockResolvedValue(makePlan())

    renderPlanner()

    await waitFor(() => {
      expect(getChargePlan).toHaveBeenCalledWith(42, 60, 80, undefined)
    })
  })

  it('re-calls getChargePlan with customKw when a custom kW is entered', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar({ id: 1 })])
    const getChargePlan = vi
      .spyOn(api, 'getChargePlan')
      .mockResolvedValue(makePlan())

    renderPlanner()

    // Wait for initial load
    await screen.findByTestId('plan-table')

    // Clear initial calls
    getChargePlan.mockClear()

    // Enter a custom kW value
    const customInput = screen.getByTestId('planner-custom-kw')
    await user.clear(customInput)
    await user.type(customInput, '22')

    await waitFor(() => {
      expect(getChargePlan).toHaveBeenCalledWith(1, 60, 80, 22)
    })
  })

  it('keeps car selector, start SoC, and target SoC inputs', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    // Wait for cars to load
    await waitFor(() => {
      expect(screen.getByTestId('planner-car-select')).toBeInTheDocument()
    })
    expect(screen.getByTestId('planner-start-soc')).toBeInTheDocument()
    expect(screen.getByTestId('planner-target-soc')).toBeInTheDocument()
  })

  // ---------------------------------------------------------------------------
  // New tests: default SoC values + clearable inputs + validation
  // ---------------------------------------------------------------------------

  it('shows default start SoC of 60 and target SoC of 80 on render', async () => {
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    await waitFor(() => {
      expect(screen.getByTestId('planner-start-soc')).toBeInTheDocument()
    })

    const startInput = screen.getByTestId('planner-start-soc') as HTMLInputElement
    const targetInput = screen.getByTestId('planner-target-soc') as HTMLInputElement

    expect(startInput.value).toBe('60')
    expect(targetInput.value).toBe('80')
  })

  it('allows clearing the start SoC field without snapping to 0', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    await waitFor(() => {
      expect(screen.getByTestId('planner-start-soc')).toBeInTheDocument()
    })

    const startInput = screen.getByTestId('planner-start-soc') as HTMLInputElement

    await user.clear(startInput)

    // After clearing, the field value should be empty, NOT "0"
    expect(startInput.value).toBe('')
  })

  it('shows a validation message and does not call getChargePlan when start SoC is empty', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    const getChargePlan = vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    // Wait for initial plan load with valid defaults
    await screen.findByTestId('plan-table')
    getChargePlan.mockClear()

    const startInput = screen.getByTestId('planner-start-soc')
    await user.clear(startInput)

    // Should show a validation message
    await waitFor(() => {
      const err = screen.getByTestId('plan-error')
      expect(err).toBeInTheDocument()
    })

    // getChargePlan must NOT have been called with an invalid/empty start
    expect(getChargePlan).not.toHaveBeenCalled()
  })

  it('shows a validation message and does not call getChargePlan when target SoC is empty', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar()])
    const getChargePlan = vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    await screen.findByTestId('plan-table')
    getChargePlan.mockClear()

    const targetInput = screen.getByTestId('planner-target-soc')
    await user.clear(targetInput)

    await waitFor(() => {
      const err = screen.getByTestId('plan-error')
      expect(err).toBeInTheDocument()
    })

    expect(getChargePlan).not.toHaveBeenCalled()
  })

  it('shows a "target must be higher" message and does not fetch when target SoC <= start SoC', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar({ id: 1 })])
    const getChargePlan = vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    await screen.findByTestId('plan-table')
    getChargePlan.mockClear()

    // Set start to 80, target to 60 (reversed)
    const startInput = screen.getByTestId('planner-start-soc')
    const targetInput = screen.getByTestId('planner-target-soc')

    await user.clear(startInput)
    await user.type(startInput, '80')
    await user.clear(targetInput)
    await user.type(targetInput, '60')

    // Should show a "target must be higher" error
    await waitFor(() => {
      const err = screen.getByTestId('plan-error')
      expect(err.textContent?.toLowerCase()).toMatch(/target.*higher|target.*greater|higher.*start/i)
    })

    // getChargePlan must NOT have been called with (1, 80, 60, ...)
    expect(getChargePlan).not.toHaveBeenCalledWith(1, 80, 60, expect.anything())
  })

  it('calls getChargePlan when both SoC values are valid numbers and target > start', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'getCars').mockResolvedValue([makeCar({ id: 1 })])
    const getChargePlan = vi.spyOn(api, 'getChargePlan').mockResolvedValue(makePlan())

    renderPlanner()

    await screen.findByTestId('plan-table')
    getChargePlan.mockClear()

    const startInput = screen.getByTestId('planner-start-soc')
    const targetInput = screen.getByTestId('planner-target-soc')

    await user.clear(startInput)
    await user.type(startInput, '50')
    await user.clear(targetInput)
    await user.type(targetInput, '90')

    await waitFor(() => {
      expect(getChargePlan).toHaveBeenCalledWith(1, 50, 90, undefined)
    })
  })
})
