import { render, screen } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'
import { EfficiencyValue } from './EfficiencyValue'
import { useSettingsStore } from '@/stores/settingsStore'
import type { SettingsMap } from '@/api/client'

function setSettings(overrides: Record<string, string>) {
  const base: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(overrides)) {
    base[key] = {
      key,
      value,
      value_type: 'enum',
      group_name: 'display',
      label: key,
      description: null,
      is_secret: false,
    }
  }
  useSettingsStore.setState({ settings: base as unknown as SettingsMap, loaded: true })
}

describe('EfficiencyValue', () => {
  beforeEach(() => {
    setSettings({ distance_unit: 'mi', efficiency_priority: 'distance_per_energy' })
  })

  it('renders primary + secondary figures', () => {
    render(<EfficiencyValue miPerKwh={4} data-testid="eff" />)
    const el = screen.getByTestId('eff')
    expect(el).toHaveTextContent('4.00 mi/kWh')
    expect(el).toHaveTextContent('250 Wh/mi')
  })

  it('renders an em-dash for null efficiency', () => {
    render(<EfficiencyValue miPerKwh={null} data-testid="eff" />)
    expect(screen.getByTestId('eff')).toHaveTextContent('—')
  })

  it('hides the secondary when primaryOnly', () => {
    render(<EfficiencyValue miPerKwh={4} primaryOnly data-testid="eff" />)
    const el = screen.getByTestId('eff')
    expect(el).toHaveTextContent('4.00 mi/kWh')
    expect(el).not.toHaveTextContent('Wh/mi')
  })

  it('reflects the energy_per_distance priority', () => {
    setSettings({ distance_unit: 'mi', efficiency_priority: 'energy_per_distance' })
    render(<EfficiencyValue miPerKwh={4} data-testid="eff" />)
    const el = screen.getByTestId('eff')
    // Primary is now Wh/mi; the leading text should be the Wh figure.
    expect(el.textContent?.trimStart().startsWith('250 Wh/mi')).toBe(true)
  })
})
