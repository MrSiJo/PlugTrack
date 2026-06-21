import { render, screen } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'
import { EfficiencyChart } from './EfficiencyChart'
import { useSettingsStore } from '@/stores/settingsStore'

describe('EfficiencyChart', () => {
  beforeEach(() => {
    useSettingsStore.setState({ settings: {}, loaded: true })
  })

  it('shows empty state when every point is null', () => {
    render(
      <EfficiencyChart
        data={[{ period: '2026-06-01', observed_mi_per_kwh: null, rolling_mi_per_kwh: null, cost_per_mile_p: null }]}
      />,
    )
    expect(screen.getByText(/no odometer data/i)).toBeInTheDocument()
  })

  it('renders a chart container when a point has data', () => {
    render(
      <EfficiencyChart
        data={[{ period: '2026-06-01', observed_mi_per_kwh: 4.1, rolling_mi_per_kwh: 3.9, cost_per_mile_p: 6.2 }]}
        data-testid="eff"
      />,
    )
    expect(screen.getByTestId('eff')).toBeInTheDocument()
  })

  it('shows the rolling-lifetime headline from the latest non-null value', () => {
    render(
      <EfficiencyChart
        data={[
          { period: '2026-06-01', observed_mi_per_kwh: 4.1, rolling_mi_per_kwh: 3.5, cost_per_mile_p: 6.2 },
          { period: '2026-06-02', observed_mi_per_kwh: 4.4, rolling_mi_per_kwh: 3.7, cost_per_mile_p: 6.0 },
        ]}
      />,
    )
    const headline = screen.getByTestId('efficiency-rolling-headline')
    expect(headline).toHaveTextContent('Rolling lifetime')
    expect(headline).toHaveTextContent('3.70 mi/kWh') // latest non-null rolling
  })
})
