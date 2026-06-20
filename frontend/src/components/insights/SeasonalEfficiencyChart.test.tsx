import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useSettingsStore } from '@/stores/settingsStore'
import { SeasonalEfficiencyChart, ChartTooltip } from './SeasonalEfficiencyChart'

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

  it('tooltip shows derived_range_km converted to km (100 km → "100 km")', () => {
    useSettingsStore.setState({
      settings: { distance_unit: { key: 'distance_unit', value: 'km', value_type: 'enum', group_name: '', label: '', description: null, is_secret: false } },
      loaded: true,
    })
    const point = { period: '2026-06', mi_per_kwh: 4.1, derived_range_km: 100, low_confidence: false }
    const payload = [{ payload: point, name: 'derived_range_display', value: 100 }]
    render(<ChartTooltip active={true} payload={payload} />)
    // formatDistance(100, 'km') → { value: 100, unit: 'km' } → "100 km"
    expect(screen.getByText(/100 km/i)).toBeInTheDocument()
  })

  it('tooltip shows derived_range_km converted to mi (160.9344 km → "100 mi")', () => {
    // Default distance_unit is 'mi'
    useSettingsStore.setState({ settings: {}, loaded: true })
    const point = { period: '2026-06', mi_per_kwh: 4.1, derived_range_km: 160.9344, low_confidence: false }
    const payload = [{ payload: point, name: 'derived_range_display', value: 100 }]
    render(<ChartTooltip active={true} payload={payload} />)
    // formatDistance(160.9344, 'mi') → { value: 100, unit: 'mi' } → "100 mi"
    expect(screen.getByText(/100 mi/i)).toBeInTheDocument()
  })

  it('Fix 3: tooltip mi_per_kwh is rounded to 2 dp (not raw float)', () => {
    // 3.293709853662873 should display as "3.29 mi/kWh", not the raw float.
    useSettingsStore.setState({ settings: {}, loaded: true })
    const point = {
      period: '2026-06',
      mi_per_kwh: 3.293709853662873,
      derived_range_km: 168,
      low_confidence: false,
    }
    const payload = [{ payload: point, name: 'mi_per_kwh', value: 3.293709853662873 }]
    const { container } = render(<ChartTooltip active={true} payload={payload} />)
    // Must show exactly 2 dp
    expect(container.textContent).toMatch(/3\.29 mi\/kWh/)
    // Must NOT show 6+ dp raw float
    expect(container.textContent).not.toMatch(/3\.2937/)
  })

  it('Fix 3: tooltip range value is rounded to whole number (no decimal)', () => {
    useSettingsStore.setState({ settings: {}, loaded: true })
    const point = {
      period: '2026-09',
      mi_per_kwh: 3.1,
      derived_range_km: 148.7,  // converts to ~92.4 mi — should show "92" not "92.4..."
      low_confidence: false,
    }
    const payload = [{ payload: point, name: 'mi_per_kwh', value: 3.1 }]
    const { container } = render(<ChartTooltip active={true} payload={payload} />)
    // Range display should be a whole number followed by the unit
    expect(container.textContent).toMatch(/\d+ mi/)
    // Should NOT contain a decimal in the range portion
    // The range line is "Range: N mi" — no decimal N
    expect(container.textContent).not.toMatch(/Range: \d+\.\d/)
  })
})
