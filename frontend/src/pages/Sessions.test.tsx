import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import Sessions from './Sessions'
import { api, type ChargingSessionPayload } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'

function makeSession(
  over: Partial<ChargingSessionPayload> = {},
): ChargingSessionPayload {
  return {
    id: 1,
    user_id: 1,
    car_id: 1,
    date: '2026-04-12',
    charge_start_at: null,
    charge_end_at: null,
    start_soc: 20,
    end_soc: 80,
    kwh_added: 46.2,
    kwh_calculated: null,
    odometer_at_session_km: 12345,
    charging_type: 'ac',
    charging_mode: 'manual',
    battery_care: null,
    max_charge_current: null,
    actual_charge_seconds: null,
    interrupted: false,
    cost_pence: 347,
    cost_basis: 'home_rate',
    tariff_p_per_kwh: 7.5,
    cost_per_kwh_override_p: null,
    total_cost_pence_override: null,
    location_id: null,
    location_name: null,
    location_address: null,
    location_lat: null,
    location_lng: null,
    user_label: null,
    charge_network: null,
    notes: null,
    source: 'manual',
    telematics_session_id: null,
    saved_vs_petrol_p: null,
    comparison_basis: null,
    breakeven_p_per_kwh: null,
    efficiency_mi_per_kwh: null,
    efficiency_basis: null,
    ...over,
  }
}

/** Pull the most recent getSessions query string back out of the spy. */
function lastQuery(spy: ReturnType<typeof vi.spyOn>): URLSearchParams {
  const calls = spy.mock.calls
  expect(calls.length).toBeGreaterThan(0)
  const arg = calls[calls.length - 1]![0]
  const qs = typeof arg === 'string' ? arg.replace(/^\?/, '') : ''
  return new URLSearchParams(qs)
}

describe('Sessions page', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'getSettings').mockResolvedValue({})
    useSettingsStore.setState({ settings: {}, loaded: true })
  })

  it('renders a table with the expected column headers and a row per session', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([
      makeSession({ id: 1 }),
      makeSession({ id: 2 }),
      makeSession({ id: 3 }),
    ])

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByTestId('session-row')).toHaveLength(3)
    })

    expect(screen.getByRole('table')).toBeInTheDocument()
    for (const header of ['Date', 'Location', 'kWh', 'Cost', 'Saved', 'SoC', 'Rate', 'Type']) {
      expect(
        screen.getByRole('columnheader', { name: new RegExp(header, 'i') }),
      ).toBeInTheDocument()
    }
  })

  it('renders source badges and gradient cost', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([
      makeSession({ source: 'manual', cost_pence: 1840 }),
      makeSession({
        id: 2,
        source: 'synthesis',
        cost_pence: 0,
        location_id: 99,
      }),
    ])

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByTestId('session-row').length).toBe(2)
    })

    expect(screen.getByTestId('source-badge-manual')).toBeInTheDocument()
    expect(screen.getByTestId('source-badge-synthesis')).toBeInTheDocument()

    const costs = screen.getAllByTestId('session-cost')
    expect(costs[0]).toHaveTextContent('£18.40')
    expect(costs[1]).toHaveTextContent('£0.00')
  })

  it('shows a summary line with the session count and total cost', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([
      makeSession({ id: 1, cost_pence: 400 }),
      makeSession({ id: 2, cost_pence: 600 }),
      makeSession({ id: 3, cost_pence: 800 }),
    ])

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByTestId('session-row')).toHaveLength(3)
    })

    // 3 sessions · £18.00 total
    expect(screen.getByText(/3 sessions/)).toBeInTheDocument()
    expect(screen.getByText(/£18\.00/)).toBeInTheDocument()
  })

  it('shows empty state when there are no sessions', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([])
    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )
    await waitFor(() => {
      expect(screen.getByText(/No sessions yet/i)).toBeInTheDocument()
    })
  })

  describe('sorting', () => {
    it('defaults to sort=date dir=desc on the initial fetch', async () => {
      const spy = vi
        .spyOn(api, 'getSessions')
        .mockResolvedValue([makeSession({ id: 1 })])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const q = lastQuery(spy)
      expect(q.get('sort')).toBe('date')
      expect(q.get('dir')).toBe('desc')
    })

    it('clicking a sortable header refetches with that sort, and clicking again flips dir', async () => {
      const spy = vi
        .spyOn(api, 'getSessions')
        .mockResolvedValue([makeSession({ id: 1 })])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const costButton = screen.getByRole('button', { name: /Cost/i })

      // First click → sort=cost dir=desc
      fireEvent.click(costButton)
      await waitFor(() => {
        const q = lastQuery(spy)
        expect(q.get('sort')).toBe('cost')
        expect(q.get('dir')).toBe('desc')
      })

      // Active header shows the descending indicator (aria-sort on the
      // clickable sort control).
      expect(costButton).toHaveAttribute('aria-sort', 'descending')

      // Second click → same field flips to asc.
      fireEvent.click(costButton)
      await waitFor(() => {
        const q = lastQuery(spy)
        expect(q.get('sort')).toBe('cost')
        expect(q.get('dir')).toBe('asc')
      })
      expect(costButton).toHaveAttribute('aria-sort', 'ascending')
    })

    it('does not sort when a non-sortable header is clicked', async () => {
      const spy = vi
        .spyOn(api, 'getSessions')
        .mockResolvedValue([makeSession({ id: 1 })])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const callsBefore = spy.mock.calls.length
      // The Location header is plain text inside a <th> — not a button.
      const locationHeaderText = screen.getByText('Location')
      const locationHeader = locationHeaderText.closest('th') as HTMLElement
      expect(locationHeader).not.toBeNull()
      // A non-sortable header has no clickable sort button.
      expect(within(locationHeader).queryByRole('button')).toBeNull()

      fireEvent.click(locationHeader)

      // No refetch was triggered.
      expect(spy.mock.calls.length).toBe(callsBefore)
      const q = lastQuery(spy)
      expect(q.get('sort')).toBe('date')
    })
  })

  describe('saved cell', () => {
    it('renders "—" when saved_vs_petrol_p is null', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([
        makeSession({ id: 1, saved_vs_petrol_p: null, comparison_basis: null }),
      ])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const cell = screen.getByTestId('session-saved')
      expect(cell).toHaveTextContent('—')
      // Null savings should not render arrows or signs.
      expect(cell).not.toHaveTextContent('↓')
      expect(cell).not.toHaveTextContent('↑')
      expect(cell).not.toHaveTextContent('+')
      expect(cell).not.toHaveTextContent('-')
    })

    it('renders down-arrow + green and no +/- for a saving (estimated)', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([
        makeSession({
          id: 1,
          saved_vs_petrol_p: 538,
          comparison_basis: 'estimated',
        }),
      ])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const cell = screen.getByTestId('session-saved')
      // Arrow present, ~ prefix for estimated, no +/- sign.
      expect(cell).toHaveTextContent('~↓')
      expect(cell).toHaveTextContent('£5.38')
      expect(cell).not.toHaveTextContent('+')
      expect(cell).not.toHaveTextContent('-')
      // Positive savings → green colour class.
      const inner = cell.querySelector('span')!
      expect(inner.className).toMatch(/emerald/)
    })

    it('renders up-arrow + red for a loss (cheaper than petrol: false)', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([
        makeSession({
          id: 1,
          saved_vs_petrol_p: -689,
          comparison_basis: 'estimated',
        }),
      ])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const cell = screen.getByTestId('session-saved')
      // Up-arrow for loss, magnitude without sign.
      expect(cell).toHaveTextContent('~↑')
      expect(cell).toHaveTextContent('£6.89')
      expect(cell).not.toHaveTextContent('-£')
      // Loss → red colour class.
      const inner = cell.querySelector('span')!
      expect(inner.className).toMatch(/rose/)
    })

    it('renders without ~ prefix when comparison_basis is not "estimated"', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([
        makeSession({
          id: 1,
          saved_vs_petrol_p: 468,
          comparison_basis: null,
        }),
      ])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const cell = screen.getByTestId('session-saved')
      expect(cell).not.toHaveTextContent('~')
      expect(cell).toHaveTextContent('↓')
      expect(cell).toHaveTextContent('£4.68')
    })
  })

  describe('rate cell breakeven colouring', () => {
    it('colours the rate cell green when tariff <= breakeven', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([
        makeSession({
          id: 1,
          tariff_p_per_kwh: 19,
          breakeven_p_per_kwh: 47,
        }),
      ])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      // Cells: date, location, kWh, cost, saved, SoC, efficiency, rate, type.
      // Rate column is the 8th cell (index 7).
      const row = screen.getByTestId('session-row')
      const cells = row.querySelectorAll('td')
      const rateCell = cells[7]!
      expect(rateCell.className).toMatch(/emerald/)
    })

    it('colours the rate cell red when tariff > breakeven', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([
        makeSession({
          id: 1,
          tariff_p_per_kwh: 92,
          breakeven_p_per_kwh: 47,
        }),
      ])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const row = screen.getByTestId('session-row')
      const cells = row.querySelectorAll('td')
      const rateCell = cells[7]!
      expect(rateCell.className).toMatch(/rose/)
    })

    it('leaves rate cell neutral when breakeven is null', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([
        makeSession({
          id: 1,
          tariff_p_per_kwh: 19,
          breakeven_p_per_kwh: null,
        }),
      ])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const row = screen.getByTestId('session-row')
      const cells = row.querySelectorAll('td')
      const rateCell = cells[7]!
      expect(rateCell.className).not.toMatch(/emerald/)
      expect(rateCell.className).not.toMatch(/rose/)
    })

    it('shows the breakeven threshold caption in the Rate column header', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([
        makeSession({
          id: 1,
          tariff_p_per_kwh: 19,
          breakeven_p_per_kwh: 47.3,
        }),
      ])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      // The Rate header should contain the breakeven annotation.
      const rateHeader = screen.getByRole('columnheader', { name: /Rate/i })
      expect(rateHeader).toHaveTextContent(/47/)
    })
  })

  describe('summary line savings', () => {
    it('shows arrow + colour in the summary total saved when savings are present', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([
        makeSession({ id: 1, cost_pence: 400, saved_vs_petrol_p: 300, comparison_basis: 'estimated' }),
        makeSession({ id: 2, cost_pence: 600, saved_vs_petrol_p: 200, comparison_basis: 'estimated' }),
      ])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getAllByTestId('session-row')).toHaveLength(2)
      })

      // The summary line should show an arrow for total saved.
      // Use the "2 sessions" text (numeric prefix) to uniquely find the paragraph.
      const summary = screen.getByText(/2 sessions/i).closest('p')!
      // Total saved = 500p = £5.00, positive so ↓ (green).
      expect(summary).toHaveTextContent('↓')
      expect(summary).toHaveTextContent('£5.00')
      // Should not render a raw +/- sign before the amount.
      expect(summary).not.toHaveTextContent('+£')
    })

    it('shows "— saved" in the summary when no rows have savings', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([
        makeSession({ id: 1, saved_vs_petrol_p: null }),
        makeSession({ id: 2, saved_vs_petrol_p: null }),
      ])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getAllByTestId('session-row')).toHaveLength(2)
      })

      expect(screen.getByText(/— saved/i)).toBeInTheDocument()
    })
  })

  describe('date range filter', () => {
    it('defaults to a rolling 30-day window on the initial fetch', async () => {
      const spy = vi
        .spyOn(api, 'getSessions')
        .mockResolvedValue([makeSession({ id: 1 })])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const q = lastQuery(spy)
      const from = q.get('date_from')
      const to = q.get('date_to')
      expect(from).toBeTruthy()
      expect(to).toBeTruthy()

      const fromMs = new Date(from as string).getTime()
      const toMs = new Date(to as string).getTime()
      const spanDays = Math.round((toMs - fromMs) / 86_400_000)
      // Rolling ~30 days. Allow a few days of slack for local-vs-UTC date
      // truncation / DST; the point is it is a one-month window, clearly
      // distinct from last_90 (~90) or all-time (no bounds).
      expect(spanDays).toBeGreaterThanOrEqual(28)
      expect(spanDays).toBeLessThanOrEqual(33)
    })

    it('selecting "Custom range" reveals two date inputs and editing them refetches with those bounds', async () => {
      const user = userEvent.setup()
      const spy = vi
        .spyOn(api, 'getSessions')
        .mockResolvedValue([makeSession({ id: 1 })])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      // Open the date-range dropdown and pick "Custom range".
      await user.click(screen.getByRole('button', { name: /Last 30 days/i }))
      const customItem = await screen.findByText('Custom range')
      await user.click(customItem)

      // Two date inputs appear.
      let fromInput: HTMLInputElement
      let toInput: HTMLInputElement
      await waitFor(() => {
        fromInput = screen.getByTestId('custom-from') as HTMLInputElement
        toInput = screen.getByTestId('custom-to') as HTMLInputElement
        expect(fromInput.type).toBe('date')
        expect(toInput.type).toBe('date')
      })

      fireEvent.change(fromInput!, { target: { value: '2026-05-01' } })
      fireEvent.change(toInput!, { target: { value: '2026-05-20' } })

      await waitFor(() => {
        const q = lastQuery(spy)
        expect(q.get('date_from')).toBe('2026-05-01')
        expect(q.get('date_to')).toBe('2026-05-20')
      })
    })

    it('shows a hint and suppresses the request when from > to', async () => {
      const user = userEvent.setup()
      const spy = vi
        .spyOn(api, 'getSessions')
        .mockResolvedValue([makeSession({ id: 1 })])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      await user.click(screen.getByRole('button', { name: /Last 30 days/i }))
      const customItem = await screen.findByText('Custom range')
      await user.click(customItem)

      let fromInput: HTMLInputElement
      let toInput: HTMLInputElement
      await waitFor(() => {
        fromInput = screen.getByTestId('custom-from') as HTMLInputElement
        toInput = screen.getByTestId('custom-to') as HTMLInputElement
        expect(fromInput.type).toBe('date')
        expect(toInput.type).toBe('date')
      })

      // Establish a valid range first and let it settle into a request.
      fireEvent.change(fromInput!, { target: { value: '2026-05-20' } })
      fireEvent.change(toInput!, { target: { value: '2026-05-25' } })
      await waitFor(() => {
        const q = lastQuery(spy)
        expect(q.get('date_from')).toBe('2026-05-20')
        expect(q.get('date_to')).toBe('2026-05-25')
      })

      const callsBefore = spy.mock.calls.length

      // Now make `from` later than `to` → invalid range.
      fireEvent.change(toInput!, { target: { value: '2026-05-01' } })

      // The inline hint appears…
      await waitFor(() => {
        expect(
          screen.getByText(/Start date must be on or before the end date/i),
        ).toBeInTheDocument()
      })

      // …and no further request fired for the invalid range: the call count
      // is unchanged and the last query still carries the prior valid bounds.
      expect(spy.mock.calls.length).toBe(callsBefore)
      const q = lastQuery(spy)
      expect(q.get('date_from')).toBe('2026-05-20')
      expect(q.get('date_to')).toBe('2026-05-25')
    })
  })

  describe('source filter', () => {
    it('offers exactly All / Telegram / Manual / Cupra / Import — no Unconfirmed', async () => {
      vi.spyOn(api, 'getSessions').mockResolvedValue([makeSession({ id: 1 })])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const tabs = screen.getByTestId('source-tabs')
      const buttons = within(tabs)
        .getAllByRole('button')
        .map((b) => b.textContent?.trim())
      expect(buttons).toEqual(['All', 'Telegram', 'Manual', 'Cupra', 'Import'])
      expect(tabs).not.toHaveTextContent('Unconfirmed')
      expect(screen.queryByTestId('unconfirmed-badge')).not.toBeInTheDocument()
    })

    it('sends the selected source to the API (e.g. telegram)', async () => {
      const user = userEvent.setup()
      const spy = vi
        .spyOn(api, 'getSessions')
        .mockResolvedValue([makeSession({ id: 1, source: 'telegram' })])

      render(
        <MemoryRouter>
          <Sessions />
        </MemoryRouter>,
      )

      await waitFor(() => {
        expect(screen.getByTestId('session-row')).toBeInTheDocument()
      })

      const tabs = screen.getByTestId('source-tabs')
      await user.click(within(tabs).getByRole('button', { name: /Telegram/i }))

      await waitFor(() => {
        const q = lastQuery(spy)
        expect(q.get('source')).toBe('telegram')
      })
    })
  })

  it('New session button opens the form and Create calls createSession', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([makeSession({ id: 1 })])
    vi.spyOn(api, 'getCars').mockResolvedValue([
      {
        id: 7,
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
      },
    ])
    vi.spyOn(api, 'getLocations').mockResolvedValue([])
    const createSpy = vi
      .spyOn(api, 'createSession')
      .mockResolvedValue(makeSession({ id: 2 }))

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('new-session-button')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('new-session-button'))

    // Form appears and the car select is populated from getCars.
    await waitFor(() => {
      expect(screen.getByTestId('session-create-form')).toBeInTheDocument()
      expect(screen.getByTestId('create-car-select')).toHaveValue('7')
    })

    fireEvent.change(screen.getByTestId('create-start-soc'), {
      target: { value: '50' },
    })
    fireEvent.change(screen.getByTestId('create-end-soc'), {
      target: { value: '80' },
    })
    fireEvent.change(screen.getByTestId('create-kwh-input'), {
      target: { value: '18.66' },
    })

    fireEvent.click(screen.getByTestId('create-session-submit'))

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledTimes(1)
    })
    const payload = createSpy.mock.calls[0]![0]
    expect(payload.car_id).toBe(7)
    expect(payload.start_soc).toBe(50)
    expect(payload.end_soc).toBe(80)
    expect(payload.kwh_added).toBeCloseTo(18.66)
  })

  it('rejects a zero-kWh manual session before calling the API', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([makeSession({ id: 1 })])
    vi.spyOn(api, 'getCars').mockResolvedValue([
      {
        id: 7,
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
      },
    ])
    vi.spyOn(api, 'getLocations').mockResolvedValue([])
    const createSpy = vi.spyOn(api, 'createSession')

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('new-session-button')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('new-session-button'))
    await waitFor(() => {
      expect(screen.getByTestId('create-car-select')).toHaveValue('7')
    })

    // kWh left at 0 / blank → client-side guard fires, no API call.
    fireEvent.click(screen.getByTestId('create-session-submit'))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/greater than 0/i)
    })
    expect(createSpy).not.toHaveBeenCalled()
  })
})

describe('Sessions page — car filter', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'getSettings').mockResolvedValue({})
    useSettingsStore.setState({ settings: {}, loaded: true })
  })

  it('renders a car filter picker with "All cars" option', async () => {
    vi.spyOn(api, 'getSessions').mockResolvedValue([makeSession({ id: 1 })])
    vi.spyOn(api, 'getCars').mockResolvedValue([
      {
        id: 7,
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
      },
    ])

    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('car-filter-picker')).toBeInTheDocument()
    })

    // The trigger starts with "All cars"
    expect(screen.getByTestId('car-filter-picker')).toHaveTextContent('All cars')
  })

  it('selecting a car from the picker refetches sessions with car_id param', async () => {
    const spy = vi.spyOn(api, 'getSessions').mockResolvedValue([makeSession({ id: 1 })])
    vi.spyOn(api, 'getCars').mockResolvedValue([
      {
        id: 7,
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
      },
    ])

    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    // Wait for picker to load
    await waitFor(() => {
      expect(screen.getByTestId('car-filter-picker')).toBeInTheDocument()
    })

    // Open the car picker and select the car
    await user.click(screen.getByTestId('car-filter-picker'))
    const option = await screen.findByRole('option', { name: 'Cupra Born' })
    await user.click(option)

    await waitFor(() => {
      const q = lastQuery(spy)
      expect(q.get('car_id')).toBe('7')
    })
  })

  it('selecting "All cars" clears the car_id from the query', async () => {
    const spy = vi.spyOn(api, 'getSessions').mockResolvedValue([makeSession({ id: 1 })])
    vi.spyOn(api, 'getCars').mockResolvedValue([
      {
        id: 7,
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
      },
    ])

    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <Sessions />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('car-filter-picker')).toBeInTheDocument()
    })

    // Select a car first
    await user.click(screen.getByTestId('car-filter-picker'))
    const carOption = await screen.findByRole('option', { name: 'Cupra Born' })
    await user.click(carOption)

    await waitFor(() => {
      const q = lastQuery(spy)
      expect(q.get('car_id')).toBe('7')
    })

    // Now select "All cars"
    await user.click(screen.getByTestId('car-filter-picker'))
    const allCarsOption = await screen.findByRole('option', { name: 'All cars' })
    await user.click(allCarsOption)

    await waitFor(() => {
      const q = lastQuery(spy)
      expect(q.get('car_id')).toBeNull()
    })
  })
})
