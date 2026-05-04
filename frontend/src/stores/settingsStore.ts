/**
 * Settings store.
 *
 * Lazy-loads the catalogue from /api/settings on first access via
 * `ensureLoaded()`. Exposes typed getters/setters and helper hooks.
 *
 * `formatDistance(km)` is the single source for converting an
 * internal-km value into the user's preferred display unit (mi/km).
 */
import { useEffect } from 'react'
import { create } from 'zustand'
import { api, type SettingPayload, type SettingsMap } from '@/api/client'

const KM_PER_MILE = 1.609344

export type DistanceUnit = 'mi' | 'km'

export interface SettingsState {
  settings: SettingsMap
  loaded: boolean
  loading: boolean
  error: string | null
  ensureLoaded: () => Promise<void>
  reload: () => Promise<void>
  get: (key: string) => SettingPayload | undefined
  set: (key: string, value: string | null) => Promise<void>
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  settings: {},
  loaded: false,
  loading: false,
  error: null,

  ensureLoaded: async () => {
    if (get().loaded || get().loading) return
    await get().reload()
  },

  reload: async () => {
    set({ loading: true, error: null })
    try {
      const settings = await api.getSettings()
      set({ settings, loaded: true, loading: false })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load settings'
      set({ loading: false, error: message })
      throw err
    }
  },

  get: (key) => get().settings[key],

  set: async (key, value) => {
    await api.putSetting(key, value)
    // Re-fetch so derived data (e.g. is_secret redaction) stays
    // authoritative server-side.
    await get().reload()
  },
}))

export function useSetting<T extends string | null>(key: string): T | undefined {
  const entry = useSettingsStore((s) => s.settings[key])
  const ensureLoaded = useSettingsStore((s) => s.ensureLoaded)
  useEffect(() => {
    void ensureLoaded()
  }, [ensureLoaded])
  return entry?.value as T | undefined
}

export function useDistanceUnit(): DistanceUnit {
  const value = useSetting<string>('distance_unit')
  return value === 'km' ? 'km' : 'mi'
}

/**
 * Convert an internal kilometres value to the user's chosen display
 * unit. Reads `distance_unit` from the store. Returns the numeric
 * value only — callers append the unit label themselves.
 */
export function formatDistance(km: number): { value: number; unit: DistanceUnit } {
  const entry = useSettingsStore.getState().settings['distance_unit']
  const unit: DistanceUnit = entry?.value === 'km' ? 'km' : 'mi'
  const value = unit === 'km' ? km : km / KM_PER_MILE
  return { value, unit }
}
