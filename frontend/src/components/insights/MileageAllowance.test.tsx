import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, type InsightsMileageResponse } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import { MileageAllowance } from './MileageAllowance'

function setUnit(unit: 'mi' | 'km') {
  useSettingsStore.setState({
    settings: {
      distance_unit: {
        key: 'distance_unit', value: unit, value_type: 'enum',
        group_name: 'display', label: 'Distance unit', description: null, is_secret: false,
      },
    },
    loaded: true, loading: false, error: null,
  } as never)
}

const ENABLED: InsightsMileageResponse = {
  enabled: true, car_id: 1, period_start: '2026-01-01', period_end: '2026-12-31',
  opening_km: 16093, current_km: 20000, target_km: 16093.4, used_km: 3907,
  remaining_km: 12186.4, days_elapsed: 170, days_total: 365,
  projected_year_end_km: 24482, pace: 'under',
}

describe('MileageAllowance', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders a setup CTA when not enabled', async () => {
    setUnit('mi')
    vi.spyOn(api, 'getInsightsMileage').mockResolvedValue({
      enabled: false, car_id: 1, period_start: null, period_end: null, opening_km: null,
      current_km: null, target_km: null, used_km: null, remaining_km: null,
      days_elapsed: null, days_total: null, projected_year_end_km: null, pace: null,
    })
    render(<MileageAllowance carId={1} />)
    await waitFor(() => expect(screen.getByText(/set up mileage tracking/i)).toBeInTheDocument())
  })

  it('renders KPI cards and pace when enabled', async () => {
    setUnit('mi')
    vi.spyOn(api, 'getInsightsMileage').mockResolvedValue(ENABLED)
    render(<MileageAllowance carId={1} />)
    await waitFor(() => expect(screen.getByTestId('mileage-allowance')).toBeInTheDocument())
    expect(screen.getByText(/under/i)).toBeInTheDocument()
    // 3907 km used ≈ 2428 mi
    expect(screen.getByText(/2,428 mi|2428 mi/)).toBeInTheDocument()
  })
})
