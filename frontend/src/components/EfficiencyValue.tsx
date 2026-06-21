/**
 * EfficiencyValue — renders an efficiency (stored as miles per kWh) as a
 * primary figure with a muted secondary figure, ordered by the
 * `efficiency_priority` setting and unit-aware via `distance_unit`.
 *
 * Renders an em-dash when the efficiency is unknown / non-positive.
 */
import { useEffect } from 'react'
import { formatEfficiency, useSettingsStore } from '@/stores/settingsStore'

export interface EfficiencyValueProps {
  miPerKwh: number | null | undefined
  className?: string
  /** When true, the secondary figure is hidden (primary only). */
  primaryOnly?: boolean
  'data-testid'?: string
}

export function EfficiencyValue({
  miPerKwh,
  className,
  primaryOnly = false,
  'data-testid': testId,
}: EfficiencyValueProps) {
  // Subscribe to the settings map so the figure re-renders when the user
  // changes `efficiency_priority` or `distance_unit`.
  useSettingsStore((s) => s.settings)
  const ensureLoaded = useSettingsStore((s) => s.ensureLoaded)
  useEffect(() => {
    void ensureLoaded()
  }, [ensureLoaded])

  const eff = formatEfficiency(miPerKwh)
  if (!eff) {
    return (
      <span className={className} data-testid={testId}>
        —
      </span>
    )
  }

  return (
    <span className={className} data-testid={testId}>
      <span className="block tabular-nums">{eff.primary.display}</span>
      {!primaryOnly && (
        <span className="block text-xs font-normal tabular-nums text-slate-400 dark:text-slate-500">
          {eff.secondary.display}
        </span>
      )}
    </span>
  )
}
