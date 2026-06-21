import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as clientModule from '@/api/client'
import { useSettingsStore, formatDistance, formatEfficiency } from './settingsStore'

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
  useSettingsStore.setState({
    settings: base as unknown as clientModule.SettingsMap,
    loaded: true,
  })
}

const sampleCatalogue = {
  distance_unit: {
    key: 'distance_unit',
    value: 'mi',
    value_type: 'enum',
    group_name: 'display',
    label: 'Distance unit',
    description: null,
    is_secret: false,
  },
  theme: {
    key: 'theme',
    value: 'system',
    value_type: 'enum',
    group_name: 'display',
    label: 'Theme',
    description: null,
    is_secret: false,
  },
} as const

describe('settingsStore', () => {
  beforeEach(() => {
    useSettingsStore.setState({
      settings: {},
      loaded: false,
      loading: false,
      error: null,
    })
  })

  it('ensureLoaded() fetches once and stores the catalogue', async () => {
    const spy = vi
      .spyOn(clientModule.api, 'getSettings')
      .mockResolvedValue(sampleCatalogue as unknown as clientModule.SettingsMap)

    await useSettingsStore.getState().ensureLoaded()
    await useSettingsStore.getState().ensureLoaded() // second call no-ops

    expect(spy).toHaveBeenCalledTimes(1)
    expect(useSettingsStore.getState().loaded).toBe(true)
    expect(useSettingsStore.getState().get('distance_unit')?.value).toBe('mi')
  })

  it('set() PUTs and reloads', async () => {
    vi.spyOn(clientModule.api, 'getSettings').mockResolvedValue(
      sampleCatalogue as unknown as clientModule.SettingsMap,
    )
    const putSpy = vi
      .spyOn(clientModule.api, 'putSetting')
      .mockResolvedValue({ key: 'theme', status: 'updated' })

    await useSettingsStore.getState().set('theme', 'dark')

    expect(putSpy).toHaveBeenCalledWith('theme', 'dark')
    expect(useSettingsStore.getState().loaded).toBe(true)
  })

  it('formatDistance honours distance_unit setting', () => {
    useSettingsStore.setState({
      settings: sampleCatalogue as unknown as clientModule.SettingsMap,
      loaded: true,
    })
    const mi = formatDistance(160.9344)
    expect(mi.unit).toBe('mi')
    expect(mi.value).toBeCloseTo(100, 3)

    useSettingsStore.setState({
      settings: {
        ...sampleCatalogue,
        distance_unit: { ...sampleCatalogue.distance_unit, value: 'km' },
      } as unknown as clientModule.SettingsMap,
      loaded: true,
    })
    const km = formatDistance(123.4)
    expect(km.unit).toBe('km')
    expect(km.value).toBeCloseTo(123.4, 6)
  })
})

describe('formatEfficiency', () => {
  beforeEach(() => {
    useSettingsStore.setState({ settings: {}, loaded: false, loading: false, error: null })
  })

  it('returns null for null / zero / negative input', () => {
    setSettings({ distance_unit: 'mi', efficiency_priority: 'distance_per_energy' })
    expect(formatEfficiency(null)).toBeNull()
    expect(formatEfficiency(undefined)).toBeNull()
    expect(formatEfficiency(0)).toBeNull()
    expect(formatEfficiency(-1)).toBeNull()
  })

  it('mi + distance_per_energy → mi/kWh primary, Wh/mi secondary', () => {
    setSettings({ distance_unit: 'mi', efficiency_priority: 'distance_per_energy' })
    const eff = formatEfficiency(4)!
    expect(eff.primary.unit).toBe('mi/kWh')
    expect(eff.primary.display).toBe('4.00 mi/kWh')
    expect(eff.secondary.unit).toBe('Wh/mi')
    // 1000 / 4 = 250
    expect(eff.secondary.value).toBe(250)
    expect(eff.secondary.display).toBe('250 Wh/mi')
  })

  it('energy_per_distance flips primary/secondary', () => {
    setSettings({ distance_unit: 'mi', efficiency_priority: 'energy_per_distance' })
    const eff = formatEfficiency(4)!
    expect(eff.primary.unit).toBe('Wh/mi')
    expect(eff.primary.display).toBe('250 Wh/mi')
    expect(eff.secondary.unit).toBe('mi/kWh')
  })

  it('km unit yields km/kWh + Wh/km', () => {
    setSettings({ distance_unit: 'km', efficiency_priority: 'distance_per_energy' })
    const eff = formatEfficiency(4)!
    // 4 mi/kWh × 1.609344 = 6.437 km/kWh
    expect(eff.primary.unit).toBe('km/kWh')
    expect(eff.primary.value).toBeCloseTo(6.44, 2)
    expect(eff.secondary.unit).toBe('Wh/km')
    // 1000 / 6.437 ≈ 155
    expect(eff.secondary.value).toBe(155)
  })

  it('Wh figure is rounded to a whole number', () => {
    setSettings({ distance_unit: 'mi', efficiency_priority: 'distance_per_energy' })
    const eff = formatEfficiency(3.6)! // 1000/3.6 = 277.77…
    expect(eff.secondary.display).toBe('278 Wh/mi')
  })
})
