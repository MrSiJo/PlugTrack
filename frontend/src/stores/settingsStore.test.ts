import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as clientModule from '@/api/client'
import { useSettingsStore, formatDistance } from './settingsStore'

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
