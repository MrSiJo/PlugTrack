/**
 * PreferencesPanel — plain, always-editable user preferences grouped by section.
 *
 * Each setting has its own inline Save button (showInlineSave=true mode of SettingRow).
 * Groups: Cost · Display · Charging planner.
 *
 * Used in AdminPage. Calls ensureLoaded on mount so it works standalone.
 */

import { useEffect } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { SettingRow } from './SettingField'

// Keys for each preference group, in display order.
const PREFERENCE_GROUPS: { label: string; keys: string[] }[] = [
  {
    label: 'Cost',
    keys: [
      'default_home_rate_p_per_kwh',
      'petrol_price_p_per_litre',
      'petrol_mpg',
      'eved_rate_p_per_mile',
      'ved_annual_cost_gbp',
      'ved_renewal_date',
    ],
  },
  {
    label: 'Display',
    keys: [
      'theme',
      'currency',
      'distance_unit',
      'efficiency_priority',
      'public_base_url',
    ],
  },
  {
    label: 'Charging planner',
    keys: [
      'home_charge_window_start',
      'home_charge_window_end',
      'home_charge_fallback_kw',
    ],
  },
]

export function PreferencesPanel() {
  const settings = useSettingsStore((s) => s.settings)
  const ensureLoaded = useSettingsStore((s) => s.ensureLoaded)

  useEffect(() => {
    void ensureLoaded()
  }, [ensureLoaded])

  return (
    <div className="space-y-6" data-testid="preferences-panel">
      {PREFERENCE_GROUPS.map((group) => {
        // Only render the group if at least one key exists in the catalogue.
        const entries = group.keys.map((k) => settings[k]).filter(Boolean)
        if (entries.length === 0) return null

        return (
          <section key={group.label}>
            <h4 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-300">
              {group.label}
            </h4>
            <div className="space-y-4 rounded border border-slate-200 p-4 dark:border-slate-700">
              {entries.map((entry) => {
                if (!entry) return null
                return (
                  <SettingRow key={entry.key} entry={entry} showInlineSave={true} />
                )
              })}
            </div>
          </section>
        )
      })}
    </div>
  )
}
