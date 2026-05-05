export type CostBand = 'green' | 'cyan' | 'amber' | 'red' | 'slate'

export interface LocationLike {
  is_free: boolean
  default_cost_per_kwh_p: number | null
}

export interface BandContext {
  /** Home reference rate, in pence-per-kWh. Use 0 to indicate "unset". */
  homeRatePence: number
}

export function classifyCostBand(
  loc: LocationLike,
  ctx: BandContext,
): CostBand {
  if (loc.is_free) return 'green'
  if (loc.default_cost_per_kwh_p === null) return 'slate'
  if (ctx.homeRatePence <= 0) return 'slate'
  const ratio = loc.default_cost_per_kwh_p / ctx.homeRatePence
  if (ratio <= 1.2) return 'cyan'
  if (ratio <= 2.5) return 'amber'
  return 'red'
}
