import type { BatteryHealth } from '@/api/client'

export interface BatteryHealthCardProps {
  data: BatteryHealth | null
  className?: string
  'data-testid'?: string
}

/**
 * Headline card for the "Estimated battery health" module — sits above the
 * CapacityTrendChart. Surfaces the single SoH figure the backend derives,
 * with caveats for measurement noise and low sample counts.
 */
export function BatteryHealthCard({
  data,
  className,
  'data-testid': testId,
}: BatteryHealthCardProps) {
  if (data === null) return null

  const {
    estimated_usable_kwh,
    nominal_kwh,
    soh_pct,
    soh_pct_raw,
    qualifying_count,
    low_confidence,
  } = data

  return (
    <div className={className} data-testid={testId}>
      <div className="flex items-baseline gap-2">
        <span className="tabular-nums text-3xl font-semibold text-violet-600 dark:text-violet-300">
          ~{soh_pct}%
        </span>
        <span className="text-xs uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
          Estimated battery health
        </span>
      </div>

      <p className="mt-1 tabular-nums text-sm text-slate-600 dark:text-slate-300">
        ≈{estimated_usable_kwh} kWh usable vs {nominal_kwh} kWh nominal
      </p>

      {soh_pct_raw >= 100 && (
        <p className="mt-1 text-[10px] text-slate-400 dark:text-slate-500">
          No measurable degradation (within measurement noise).
        </p>
      )}

      {low_confidence && (
        <p className="mt-1 text-[10px] text-amber-500">
          Low confidence — based on {qualifying_count} qualifying charge
          {qualifying_count === 1 ? '' : 's'}
        </p>
      )}
    </div>
  )
}
