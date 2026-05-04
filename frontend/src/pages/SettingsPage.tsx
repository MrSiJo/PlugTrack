import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { SettingPayload } from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { useSettingsStore } from '@/stores/settingsStore'
import { useTheme } from '@/theme'

// Hardcoded option lists for enum settings — kept local per YAGNI.
// Backend catalogue stores these keys as `enum` value_type but doesn't
// itself enumerate options.
const ENUM_OPTIONS: Record<string, { value: string; label: string }[]> = {
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
  geocoding_provider: [
    { value: 'nominatim', label: 'Nominatim (free)' },
    { value: 'mapbox', label: 'Mapbox' },
    { value: 'opencage', label: 'OpenCage' },
  ],
}

export default function SettingsPage() {
  const settings = useSettingsStore((s) => s.settings)
  const loaded = useSettingsStore((s) => s.loaded)
  const error = useSettingsStore((s) => s.error)
  const ensureLoaded = useSettingsStore((s) => s.ensureLoaded)
  const logout = useAuthStore((s) => s.logout)
  const { theme, setTheme } = useTheme()
  const navigate = useNavigate()

  useEffect(() => {
    void ensureLoaded()
  }, [ensureLoaded])

  const grouped = useMemo(() => {
    const out: Record<string, SettingPayload[]> = {}
    for (const entry of Object.values(settings)) {
      const list = out[entry.group_name] ?? []
      list.push(entry)
      out[entry.group_name] = list
    }
    for (const list of Object.values(out)) {
      list.sort((a, b) => a.label.localeCompare(b.label))
    }
    return out
  }, [settings])

  const groupOrder = ['cupra_connect', 'sync', 'cost', 'display', 'locations']
  const orderedGroups = groupOrder.filter((g) => grouped[g])
  // Catch any catalogue group we don't know about.
  for (const g of Object.keys(grouped)) {
    if (!groupOrder.includes(g)) orderedGroups.push(g)
  }

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <header className="mb-8 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Settings</h1>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <span>Theme:</span>
            <select
              aria-label="Theme"
              value={theme}
              onChange={(e) => setTheme(e.target.value as 'system' | 'light' | 'dark')}
              className="rounded border border-slate-300 bg-white px-2 py-1 dark:border-slate-700 dark:bg-slate-800"
            >
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
          <button
            type="button"
            onClick={handleLogout}
            className="rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700"
          >
            Sign out
          </button>
        </div>
      </header>

      {!loaded && <p className="text-sm text-slate-500">Loading settings…</p>}
      {error && (
        <div role="alert" className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {orderedGroups.map((group) => (
        <section key={group} className="mb-8">
          <h2 className="mb-3 text-lg font-medium capitalize">
            {group.replace(/_/g, ' ')}
          </h2>
          <div className="space-y-4 rounded border border-slate-200 p-4 dark:border-slate-700">
            {grouped[group]!.map((entry) => (
              <SettingRow key={entry.key} entry={entry} />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

interface SettingRowProps {
  entry: SettingPayload
}

function SettingRow({ entry }: SettingRowProps) {
  const setSetting = useSettingsStore((s) => s.set)
  const [editing, setEditing] = useState(!entry.is_secret)
  const [value, setValue] = useState<string>(entry.value ?? '')
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

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
        <label htmlFor={`setting-${entry.key}`} className="block text-sm font-medium">
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
          <SettingInput
            id={`setting-${entry.key}`}
            entry={entry}
            value={value}
            onChange={setValue}
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
            disabled={saving}
            className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        )}
      </div>
    </div>
  )
}

interface SettingInputProps {
  id: string
  entry: SettingPayload
  value: string
  onChange: (next: string) => void
}

function SettingInput({ id, entry, value, onChange }: SettingInputProps) {
  const baseClass =
    'w-full rounded border border-slate-300 px-3 py-1 text-sm dark:border-slate-700 dark:bg-slate-800'

  if (entry.value_type === 'bool') {
    const checked = value === 'true' || value === '1'
    return (
      <input
        id={id}
        type="checkbox"
        checked={checked}
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
        onChange={(e) => onChange(e.target.value)}
        className={baseClass}
      />
    )
  }

  // string (possibly secret).
  return (
    <input
      id={id}
      type={entry.is_secret ? 'password' : 'text'}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={baseClass}
      autoComplete={entry.is_secret ? 'new-password' : 'off'}
    />
  )
}
