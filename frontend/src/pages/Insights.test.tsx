import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api, type InsightsByLocationResponse } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import Insights from './Insights'

function makeResponse(): InsightsByLocationResponse {
  return {
    rows: [
      { location_id: 1, name: 'Home', is_home: true, is_free: false,
        spend_pence: 3000, kwh: 300, sessions: 20, avg_p_per_kwh: 10,
        first_at: '2026-01-01', last_at: '2026-06-01', pct_of_spend: 75 },
      { location_id: null, name: null, is_home: false, is_free: false,
        spend_pence: 1000, kwh: 50, sessions: 4, avg_p_per_kwh: 20,
        first_at: '2026-02-01', last_at: '2026-05-01', pct_of_spend: 25 },
    ],
    totals: { spend_pence: 4000, kwh: 350, sessions: 24 },
  }
}

describe('Insights page', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useSettingsStore.setState({ settings: {}, loaded: true })
  })
  afterEach(() => vi.restoreAllMocks())

  it('renders the breakdown table; labelled row links, Unassigned does not', async () => {
    vi.spyOn(api, 'getInsightsByLocation').mockResolvedValue(makeResponse())

    render(
      <MemoryRouter>
        <Insights />
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('Home')).toBeInTheDocument())
    // Labelled row links to the detail page.
    const homeLink = screen.getByRole('link', { name: /Home/i })
    expect(homeLink).toHaveAttribute('href', '/locations/1')
    // Unassigned present but NOT a link.
    expect(screen.getByText('Unassigned')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Unassigned/i })).toBeNull()
  })

  it('re-queries when the date range changes', async () => {
    const spy = vi
      .spyOn(api, 'getInsightsByLocation')
      .mockResolvedValue(makeResponse())

    render(
      <MemoryRouter>
        <Insights />
      </MemoryRouter>,
    )
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    // First call is all-time (no bounds).
    expect(spy.mock.calls[0]).toEqual([undefined, undefined])

    fireEvent.click(screen.getByTestId('insights-range-last_30'))
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    // Second call carries a date_from bound.
    expect(spy.mock.calls[1]![0]).toBeTruthy()
  })
})
