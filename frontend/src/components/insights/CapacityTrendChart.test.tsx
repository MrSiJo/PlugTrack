import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useSettingsStore } from '@/stores/settingsStore'
import { CapacityTrendChart } from './CapacityTrendChart'

const SAMPLE_DATA = [
  { date: '2026-01-10', usable_kwh: 56.2, charging_type: 'ac' as const, low_confidence: false },
  { date: '2026-03-15', usable_kwh: 55.8, charging_type: 'dc' as const, low_confidence: false },
  { date: '2026-05-20', usable_kwh: 54.9, charging_type: 'ac' as const, low_confidence: true },
]

describe('CapacityTrendChart', () => {
  beforeEach(() => {
    useSettingsStore.setState({ settings: {}, loaded: true })
    vi.restoreAllMocks()
  })

  it('shows empty state when data is empty', () => {
    render(<CapacityTrendChart data={[]} data-testid="ctc" />)
    expect(screen.getByText(/no trend data yet/i)).toBeInTheDocument()
  })

  it('renders the chart container when data is present', () => {
    render(<CapacityTrendChart data={SAMPLE_DATA} data-testid="ctc" />)
    expect(screen.getByTestId('ctc')).toBeInTheDocument()
  })

  it('shows the indicative SoH caveat note', () => {
    render(<CapacityTrendChart data={SAMPLE_DATA} data-testid="ctc" />)
    expect(screen.getByText(/indicative/i)).toBeInTheDocument()
    expect(screen.getByText(/not a certified/i)).toBeInTheDocument()
  })

  it('shows AC and DC in a legend or label', () => {
    render(<CapacityTrendChart data={SAMPLE_DATA} data-testid="ctc" />)
    // The custom DOM legend renders "AC" and "DC" as plain text nodes (single instance each).
    expect(screen.getByText('AC')).toBeInTheDocument()
    expect(screen.getByText('DC')).toBeInTheDocument()
  })

  it('shows kWh in the chart or surrounding text', () => {
    const { container } = render(<CapacityTrendChart data={SAMPLE_DATA} data-testid="ctc" />)
    // "kWh" appears in the YAxis label SVG text or legend formatter or summary text.
    // Use the full container textContent to avoid broken-up text node issues.
    expect(container.textContent).toMatch(/kWh/i)
  })
})
