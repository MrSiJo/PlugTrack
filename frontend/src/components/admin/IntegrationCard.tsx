/**
 * IntegrationCard — renders one integration (master toggle + member settings + actions + Save).
 *
 * The master toggle is local optimistic state initialised from the stored value.
 * Member settings are disabled (greyed) when the master is off.
 * Save persists the master + any dirtied member settings via sequential
 * useSettingsStore.set() calls.
 *
 * Secret fields use the SettingRow controlled-mode affordance (*** / Set new value)
 * rather than the inline-save mode, so the card's single Save handles persistence.
 */

import { useState, useEffect } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { SettingRow } from './SettingField'
import type { IntegrationDef } from '@/config/integrations'
import { TestConnectionPanel } from '@/pages/SettingsPage'
import { ClearTokensButton } from './ClearTokensButton'
import { SyncControlsPanel } from './SyncControlsPanel'

export function IntegrationCard({ def }: { def: IntegrationDef }) {
  const settings = useSettingsStore((s) => s.settings)
  const setSetting = useSettingsStore((s) => s.set)

  const masterEntry = settings[def.masterKey]
  const masterStoredValue = masterEntry?.value
  const [enabled, setEnabled] = useState(
    masterStoredValue === 'true' || masterStoredValue === '1',
  )

  // Re-sync the master toggle when the store hydrates (e.g. on fresh page load
  // the store is empty at mount time; this effect fires once the async load
  // populates settings and masterStoredValue changes from undefined → 'true'/'false').
  useEffect(() => {
    setEnabled(masterStoredValue === 'true' || masterStoredValue === '1')
  }, [masterStoredValue])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  function draftFor(key: string): string {
    if (key in drafts) return drafts[key]!
    return settings[key]?.value ?? ''
  }

  async function handleSave() {
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      await setSetting(def.masterKey, enabled ? 'true' : 'false')
      for (const key of def.settingKeys) {
        if (key in drafts) {
          const v = drafts[key]!
          await setSetting(key, v === '' ? null : v)
        }
      }
      setDrafts({})
      setSaved(true)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  // aria-label for the master toggle: prefer the catalogue label, fall back to def label
  const masterAriaLabel = masterEntry?.label ?? `${def.label} enabled`

  return (
    <section
      className="rounded border border-slate-200 p-4 dark:border-slate-700"
      data-testid={`integration-${def.key}`}
    >
      <header className="mb-3 flex items-center justify-between">
        <h3 className="text-base font-semibold">{def.label}</h3>
        <label className="flex items-center gap-2 text-sm select-none">
          <input
            type="checkbox"
            checked={enabled}
            aria-label={masterAriaLabel}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          <span>Enabled</span>
        </label>
      </header>

      {def.hint && (
        <p className="mb-3 text-xs text-amber-600 dark:text-amber-400">{def.hint}</p>
      )}

      <div className={`space-y-4 ${!enabled ? 'opacity-50' : ''}`}>
        {def.settingKeys.map((key) => {
          const entry = settings[key]
          if (!entry) return null
          return (
            <SettingRow
              key={key}
              entry={entry}
              showInlineSave={false}
              value={draftFor(key)}
              disabled={!enabled}
              onChange={(v) => setDrafts((d) => ({ ...d, [key]: v }))}
            />
          )
        })}

        {/* Action panels */}
        {enabled && def.actions?.includes('testTelegram') && <TestConnectionPanel />}
        {enabled && def.actions?.includes('testOpenai') && <TestConnectionPanel />}
        {enabled && def.actions?.includes('clearPycupraTokens') && <ClearTokensButton />}
        {enabled && def.actions?.includes('syncControls') && <SyncControlsPanel />}
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saved && <span className="text-xs text-emerald-600">Saved.</span>}
        {saveError && (
          <span role="alert" className="text-xs text-red-600">
            {saveError}
          </span>
        )}
      </div>
    </section>
  )
}
