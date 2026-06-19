/**
 * AdminPage — master-detail administration shell.
 *
 * Left rail: integration entries (from INTEGRATIONS config) + top-level sections.
 * Right pane: renders only the active section.
 * Active section is synced to the URL hash (e.g. /admin#telegram).
 */

import { useEffect, useState, useCallback } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { INTEGRATIONS } from '@/config/integrations'
import { IntegrationCard } from '@/components/admin/IntegrationCard'
import { PreferencesPanel } from '@/components/admin/PreferencesPanel'
import { MaintenancePanel } from '@/components/admin/MaintenancePanel'
import { LocationsManagement } from '@/components/admin/LocationsManagement'
import { CarsManagement } from '@/components/admin/CarsManagement'
import { McpTokens } from '@/components/admin/McpTokens'
import { useSettingsStore } from '@/stores/settingsStore'

/** All valid section keys in order. */
const INTEGRATION_KEYS = INTEGRATIONS.map((d) => d.key)
const TOP_LEVEL_KEYS = ['preferences', 'maintenance', 'locations', 'cars', 'mcp'] as const
type TopLevelKey = (typeof TOP_LEVEL_KEYS)[number]
type SectionKey = string // integration key or top-level key

const DEFAULT_SECTION: SectionKey = INTEGRATION_KEYS[0] ?? 'preferences'

function isValidSection(key: string): boolean {
  return INTEGRATION_KEYS.includes(key) || (TOP_LEVEL_KEYS as readonly string[]).includes(key)
}

function hashToSection(hash: string): SectionKey {
  const key = hash.replace(/^#/, '')
  return isValidSection(key) ? key : DEFAULT_SECTION
}

export default function AdminPage() {
  const ensureLoaded = useSettingsStore((s) => s.ensureLoaded)
  const location = useLocation()
  const navigate = useNavigate()

  const [activeSection, setActiveSection] = useState<SectionKey>(() =>
    hashToSection(location.hash),
  )

  // Keep state in sync when the hash changes externally (browser back/forward).
  useEffect(() => {
    setActiveSection(hashToSection(location.hash))
  }, [location.hash])

  useEffect(() => {
    void ensureLoaded()
  }, [ensureLoaded])

  const navigateTo = useCallback(
    (key: SectionKey) => {
      navigate({ hash: key }, { replace: false })
    },
    [navigate],
  )

  const navItemClass = (key: SectionKey) =>
    `flex w-full items-center rounded-md px-3 py-1.5 text-sm transition text-left ${
      activeSection === key
        ? 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-300'
        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100'
    }`

  return (
    <main className="mx-auto max-w-7xl px-6 py-8">
      <h1 className="mb-8 text-2xl font-bold tracking-tight">Administration</h1>

      <div className="flex flex-col gap-6 md:flex-row md:gap-8">
        {/* Left rail */}
        <nav
          aria-label="Administration sections"
          className="shrink-0 md:sticky md:top-8 md:w-56 md:self-start"
        >
          {/* Integrations group */}
          <p className="mb-1 px-3 text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Integrations
          </p>
          <ul className="mb-4 space-y-0.5">
            {INTEGRATIONS.map((def) => (
              <li key={def.key}>
                <button
                  type="button"
                  className={navItemClass(def.key)}
                  onClick={() => navigateTo(def.key)}
                  data-testid={`admin-nav-${def.key}`}
                >
                  {def.label}
                </button>
              </li>
            ))}
          </ul>

          {/* Top-level sections */}
          <ul className="space-y-0.5">
            {(
              [
                { key: 'preferences', label: 'Preferences' },
                { key: 'maintenance', label: 'Maintenance' },
                { key: 'locations', label: 'Locations' },
                { key: 'cars', label: 'Cars' },
                { key: 'mcp', label: 'MCP / API tokens' },
              ] satisfies { key: TopLevelKey; label: string }[]
            ).map(({ key, label }) => (
              <li key={key}>
                <button
                  type="button"
                  className={navItemClass(key)}
                  onClick={() => navigateTo(key)}
                  data-testid={`admin-nav-${key}`}
                >
                  {label}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        {/* Right content pane */}
        <div className="min-w-0 flex-1">
          {INTEGRATION_KEYS.includes(activeSection) && (() => {
            const def = INTEGRATIONS.find((d) => d.key === activeSection)
            return def ? <IntegrationCard def={def} /> : null
          })()}

          {activeSection === 'preferences' && <PreferencesPanel />}

          {activeSection === 'maintenance' && <MaintenancePanel />}

          {activeSection === 'locations' && <LocationsManagement />}

          {activeSection === 'cars' && <CarsManagement />}

          {activeSection === 'mcp' && <McpTokens />}
        </div>
      </div>
    </main>
  )
}
