import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useSettingsStore } from '@/stores/settingsStore'
import { SeasonalEfficiencyChart } from './SeasonalEfficiencyChart'

const SAMPLE_DATA = [
  { period: '2026-01', mi_per_kwh: 3.2, derived_range_km: 168, low_confidence: false },
  { period: '2026-06', mi_per_kwh: 4.1, derived_range_km: 215, low_confidence: false },
  { period: '2026-11', mi_per_kwh: 2.8, derived_range_km: 147, low_confidence: true },
]

describe('SeasonalEfficiencyChart', () => {
  beforeEach(() => {
    useSettingsStore.setState({ settings: {}, loaded: true })
    vi.restoreAllMocks()
  })

  it('shows empty state when data is empty', () => {
    render(<SeasonalEfficiencyChart data={[]} data-testid="sec" />)
    expect(screen.getByText(/no trend data yet/i)).toBeInTheDocument()
  })

  it('shows empty state when all mi_per_kwh values are null', () => {
    render(
      <SeasonalEfficiencyChart
        data={[{ period: '2026-01', mi_per_kwh: null, derived_range_km: null, low_confidence: false }]}
        data-testid="sec"
      />,
    )
    expect(screen.getByText(/no trend data yet/i)).toBeInTheDocument()
  })

  it('renders the chart container when data is present', () => {
    render(<SeasonalEfficiencyChart data={SAMPLE_DATA} data-testid="sec" />)
    expect(screen.getByTestId('sec')).toBeInTheDocument()
  })

  it('shows the caveat note about derived range', () => {
    render(<SeasonalEfficiencyChart data={SAMPLE_DATA} data-testid="sec" />)
    expect(screen.getByText(/range is derived/i)).toBeInTheDocument()
    expect(screen.getByText(/full year of data/i)).toBeInTheDocument()
  })

  it('shows mi/kWh unit label', () => {
    render(<SeasonalEfficiencyChart data={SAMPLE_DATA} data-testid="sec" />)
    // The custom legend span renders "mi/kWh" as a plain DOM text node.
    expect(screen.getByText('mi/kWh')).toBeInTheDocument()
  })

  it('renders a range axis label in the user unit (miles by default)', () => {
    render(<SeasonalEfficiencyChart data={SAMPLE_DATA} data-testid="sec" />)
    // The custom legend span renders "Range (mi)" as a plain DOM text node.
    expect(screen.getByText('Range (mi)')).toBeInTheDocument()
  })

  it('renders a range axis label in km when distance_unit is km', () => {
    useSettingsStore.setState({
      settings: { distance_unit: { key: 'distance_unit', value: 'km', value_type: 'enum', group_name: '', label: '', description: null, is_secret: false } },
      loaded: true,
    })
    render(<SeasonalEfficiencyChart data={SAMPLE_DATA} data-testid="sec" />)
    expect(screen.getByText('Range (km)')).toBeInTheDocument()
  })
})
