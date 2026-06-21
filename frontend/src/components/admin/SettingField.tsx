/**
 * Shared setting field renderer, extracted from SettingsPage.
 *
 * Exports:
 *  - ENUM_OPTIONS   — hardcoded option lists for enum-type settings
 *  - ModelSelect    — OpenAI model picker (fetches available models from API)
 *  - SettingField   — bare input renderer (renamed from SettingInput)
 *  - SettingRow     — label + description + field; two modes:
 *      showInlineSave=true  → manages its own local state + inline Save button
 *      showInlineSave=false → controlled (parent supplies value + onChange, no Save)
 */

import { useEffect, useState } from 'react'
import { api, type OpenAiModelsResponse, type SettingPayload } from '@/api/client'
import { useSettingsStore } from '@/stores/settingsStore'

// ---------------------------------------------------------------------------
// ENUM_OPTIONS
// ---------------------------------------------------------------------------

// Hardcoded option lists for enum settings — kept local per YAGNI.
// Backend catalogue stores these keys as `enum` value_type but doesn't
// itself enumerate options.
export const ENUM_OPTIONS: Record<string, { value: string; label: string }[]> = {
  theme: [
    { value: 'system', label: 'System' },
    { value: 'light', label: 'Light' },
    { value: 'dark', label: 'Dark' },
  ],
  vehicle_provider: [{ value: 'cupra_connect', label: 'Cupra Connect' }],
  distance_unit: [
    { value: 'mi', label: 'Miles' },
    { value: 'km', label: 'Kilometres' },
  ],
  efficiency_priority: [
    { value: 'distance_per_energy', label: 'mi/kWh (Wh/mi secondary)' },
    { value: 'energy_per_distance', label: 'Wh/mi (mi/kWh secondary)' },
  ],
  geocoding_provider: [
    { value: 'nominatim', label: 'Nominatim (free)' },
    { value: 'mapbox', label: 'Mapbox' },
    { value: 'opencage', label: 'OpenCage' },
  ],
  ai_provider: [
    { value: 'openai', label: 'OpenAI' },
  ],
}

// ---------------------------------------------------------------------------
// ModelSelect
// ---------------------------------------------------------------------------

export function ModelSelect({
  value,
  onChange,
  disabled,
}: {
  value: string
  onChange: (v: string) => void
  disabled?: boolean
}) {
  const [data, setData] = useState<OpenAiModelsResponse | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    api.getOpenAiModels().then(setData).catch(() => setFailed(true))
  }, [])
  if (failed || !data) {
    return (
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={failed ? 'Save your OpenAI key first, then reload' : 'Loading models…'}
        className="w-full rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 disabled:opacity-50"
      />
    )
  }
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="w-full rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 disabled:opacity-50"
    >
      {data.models.map((m) => (
        <option key={m.id} value={m.id}>
          {m.recommended ? `⭐ ${m.id}` : m.id}
        </option>
      ))}
    </select>
  )
}

// ---------------------------------------------------------------------------
// SettingField (was SettingInput)
// ---------------------------------------------------------------------------

export interface SettingFieldProps {
  id: string
  entry: SettingPayload
  value: string
  onChange: (next: string) => void
  disabled?: boolean
}

export function SettingField({ id, entry, value, onChange, disabled }: SettingFieldProps) {
  const baseClass =
    'w-full rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 disabled:opacity-50'

  if (entry.value_type === 'bool') {
    const checked = value === 'true' || value === '1'
    return (
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked ? 'true' : 'false')}
      />
    )
  }

  if (entry.value_type === 'enum') {
    const options = ENUM_OPTIONS[entry.key] ?? []
    return (
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={baseClass}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    )
  }

  if (entry.value_type === 'int' || entry.value_type === 'float') {
    return (
      <input
        id={id}
        type="number"
        step={entry.value_type === 'float' ? '0.01' : '1'}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={baseClass}
      />
    )
  }

  if (entry.key === 'openai_model') {
    return <ModelSelect value={value} onChange={onChange} disabled={disabled} />
  }

  // string (possibly secret).
  return (
    <input
      id={id}
      type={entry.is_secret ? 'password' : 'text'}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className={baseClass}
      autoComplete={entry.is_secret ? 'new-password' : 'off'}
    />
  )
}

// ---------------------------------------------------------------------------
// SettingRow
// ---------------------------------------------------------------------------
//
// Two modes:
//
//  showInlineSave=true  (default) — self-managed: reads entry.value from the
//    store, maintains local draft state, renders its own Save button.
//    Used by PreferencesPanel.
//
//  showInlineSave=false — controlled: parent supplies `value` + `onChange`
//    and is responsible for persisting. No Save button rendered.
//    Used by IntegrationCard (the card has a single Save for all its fields).
//
// The `disabled` prop is forwarded to SettingField in both modes and also
// disables the Save button in inline-save mode.

type SettingRowInlineSaveProps = {
  entry: SettingPayload
  disabled?: boolean
  showInlineSave: true
}

type SettingRowControlledProps = {
  entry: SettingPayload
  disabled?: boolean
  showInlineSave: false
  value: string
  onChange: (next: string) => void
}

export type SettingRowProps = SettingRowInlineSaveProps | SettingRowControlledProps

export function SettingRow(props: SettingRowProps) {
  const { entry, disabled } = props
  const fieldId = `setting-${entry.key}`

  if (props.showInlineSave) {
    // ---- inline-save mode ----
    return <SettingRowInline entry={entry} disabled={disabled} />
  }

  // ---- controlled mode ----
  return (
    <div className="grid grid-cols-1 gap-2 md:grid-cols-[200px_1fr] md:items-center">
      <div>
        <label htmlFor={fieldId} className="block text-sm font-medium">
          {entry.label}
        </label>
        {entry.description && (
          <p className="text-xs text-slate-500">{entry.description}</p>
        )}
      </div>
      <div>
        {entry.is_secret && props.value === (entry.value ?? '') ? (
          // Show the masked affordance when the field hasn't been touched
          // (value still matches stored, which is '***' for secrets).
          entry.value ? (
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm">***</span>
              <button
                type="button"
                onClick={() => props.onChange('')}
                className="text-sm text-indigo-600 underline"
              >
                Set new value
              </button>
            </div>
          ) : (
            <SettingField
              id={fieldId}
              entry={entry}
              value={props.value}
              onChange={props.onChange}
              disabled={disabled}
            />
          )
        ) : (
          <SettingField
            id={fieldId}
            entry={entry}
            value={props.value}
            onChange={props.onChange}
            disabled={disabled}
          />
        )}
      </div>
    </div>
  )
}

// Internal component for inline-save mode (avoids hook-in-conditional issues).
function SettingRowInline({ entry, disabled }: { entry: SettingPayload; disabled?: boolean }) {
  const setSetting = useSettingsStore((s) => s.set)
  const [editing, setEditing] = useState(!entry.is_secret)
  const [value, setValue] = useState<string>(entry.value ?? '')
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fieldId = `setting-${entry.key}`

  // Sync local state when the catalogue is reloaded.
  useEffect(() => {
    setValue(entry.value ?? '')
    if (entry.is_secret) {
      setEditing(false)
    }
  }, [entry.value, entry.is_secret])

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await setSetting(entry.key, value === '' ? null : value)
      setSavedAt(Date.now())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="grid grid-cols-1 gap-2 md:grid-cols-[200px_1fr_auto] md:items-center">
      <div>
        <label htmlFor={fieldId} className="block text-sm font-medium">
          {entry.label}
        </label>
        {entry.description && (
          <p className="text-xs text-slate-500">{entry.description}</p>
        )}
      </div>
      <div>
        {entry.is_secret && !editing ? (
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm">{entry.value ? '***' : '(not set)'}</span>
            <button
              type="button"
              onClick={() => {
                setValue('')
                setEditing(true)
              }}
              className="text-sm text-indigo-600 underline"
            >
              Set new value
            </button>
          </div>
        ) : (
          <SettingField
            id={fieldId}
            entry={entry}
            value={value}
            onChange={setValue}
            disabled={disabled}
          />
        )}
        {error && (
          <p role="alert" className="mt-1 text-xs text-red-600">
            {error}
          </p>
        )}
        {savedAt && !error && (
          <p className="mt-1 text-xs text-emerald-600">Saved.</p>
        )}
      </div>
      <div className="flex justify-end">
        {(editing || !entry.is_secret) && (
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || disabled}
            className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        )}
      </div>
    </div>
  )
}
