/**
 * Distance unit conversion + display formatting.
 *
 * Single source of truth for the client-side. The backend stores all
 * distance fields in km (with the `_km` suffix); the UI converts to
 * the user's preferred unit at render-time.
 *
 * `formatDistance(km, unit)` returns a fully-formed display string
 * ("125 mi" or "201 km"). Use the variant in `settingsStore` for the
 * raw {value, unit} tuple if you need to lay out the number and label
 * separately.
 */

const KM_PER_MILE = 1.609344

export type DistanceUnit = 'mi' | 'km'

export function kmToMi(km: number): number {
  return km / KM_PER_MILE
}

export function miToKm(mi: number): number {
  return mi * KM_PER_MILE
}

export function formatDistance(km: number, unit: DistanceUnit): string {
  const value = unit === 'km' ? km : kmToMi(km)
  // Round to 0 decimals for tidy display; callers with higher
  // precision needs can compute themselves.
  const rounded = Math.round(value)
  return `${rounded} ${unit}`
}
