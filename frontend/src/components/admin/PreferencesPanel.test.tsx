import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import type { SettingsMap } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'
import { PreferencesPanel } from './PreferencesPanel'

function floatSetting(key: string, label: string, value: string): SettingsMap[string] {
  return {
    key,
    value,
    value_type: 'float',
    group_name: 'cost',
    label,
    description: null,
    is_secret: false,
  }
}

const settings: SettingsMap = {
  default_home_rate_p_per_kwh: floatSetting(
    'default_home_rate_p_per_kwh',
    'Home charging rate (p/kWh)',
    '7.5',
  ),
  eved_rate_p_per_mile: floatSetting('eved_rate_p_per_mile', 'eVED rate (p/mile)', '3.0'),
  ved_annual_cost_gbp: floatSetting('ved_annual_cost_gbp', 'Annual VED (£)', '200'),
  ved_renewal_date: {
    key: 'ved_renewal_date',
    value: '07-31',
    value_type: 'string',
    group_name: 'cost',
    label: 'VED renewal date (MM-DD)',
    description: null,
    is_secret: false,
  },
}

beforeEach(() => {
  useSettingsStore.setState({
    settings,
    loaded: true,
    loading: false,
    error: null,
  })
})

describe('PreferencesPanel', () => {
  it('renders the eVED and VED settings in the Cost group', () => {
    render(<PreferencesPanel />)
    expect(screen.getByText('eVED rate (p/mile)')).toBeInTheDocument()
    expect(screen.getByText('Annual VED (£)')).toBeInTheDocument()
    expect(screen.getByText('VED renewal date (MM-DD)')).toBeInTheDocument()
  })
})
