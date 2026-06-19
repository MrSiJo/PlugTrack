/**
 * AdminPage — consolidated administration shell.
 *
 * Sections:
 *  - Integrations  — IntegrationCard per INTEGRATIONS config entry
 *  - Preferences   — PreferencesPanel (cost / display / planner settings)
 *  - Maintenance   — placeholder (filled in Phase C)
 *  - Locations     — placeholder (filled in Phase B)
 *  - Cars          — placeholder (filled in Phase B)
 */

import { useEffect } from 'react'
import { INTEGRATIONS } from '@/config/integrations'
import { IntegrationCard } from '@/components/admin/IntegrationCard'
import { PreferencesPanel } from '@/components/admin/PreferencesPanel'
import { useSettingsStore } from '@/stores/settingsStore'

export default function AdminPage() {
  const ensureLoaded = useSettingsStore((s) => s.ensureLoaded)

  useEffect(() => {
    void ensureLoaded()
  }, [ensureLoaded])

  return (
    <main className="mx-auto max-w-7xl px-6 py-8">
      <h1 className="mb-8 text-2xl font-bold tracking-tight">Administration</h1>

      {/* Integrations */}
      <section className="mb-10" aria-labelledby="section-integrations-heading">
        <h2
          id="section-integrations-heading"
          className="mb-4 text-lg font-semibold"
        >
          Integrations
        </h2>
        <div className="grid gap-4 lg:grid-cols-2">
          {INTEGRATIONS.map((def) => (
            <IntegrationCard key={def.key} def={def} />
          ))}
        </div>
      </section>

      {/* Preferences */}
      <section className="mb-10" aria-labelledby="section-preferences-heading">
        <h2
          id="section-preferences-heading"
          className="mb-4 text-lg font-semibold"
        >
          Preferences
        </h2>
        <PreferencesPanel />
      </section>

      {/* Maintenance — placeholder for Phase C */}
      <section
        className="mb-10"
        aria-labelledby="section-maintenance-heading"
        data-testid="admin-section-maintenance"
      >
        <h2
          id="section-maintenance-heading"
          className="mb-4 text-lg font-semibold"
        >
          Maintenance
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Maintenance tools coming soon.
        </p>
      </section>

      {/* Locations management — placeholder for Phase B */}
      <section
        className="mb-10"
        aria-labelledby="section-locations-heading"
        data-testid="admin-section-locations"
      >
        <h2
          id="section-locations-heading"
          className="mb-4 text-lg font-semibold"
        >
          Locations
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Location management coming soon.
        </p>
      </section>

      {/* Cars management — placeholder for Phase B */}
      <section
        className="mb-10"
        aria-labelledby="section-cars-heading"
        data-testid="admin-section-cars"
      >
        <h2
          id="section-cars-heading"
          className="mb-4 text-lg font-semibold"
        >
          Cars
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Car management coming soon.
        </p>
      </section>
    </main>
  )
}
