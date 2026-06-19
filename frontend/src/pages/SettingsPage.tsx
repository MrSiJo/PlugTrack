import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ApiError,
  api,
  type CarPayload,
  type HealthReport,
  type SettingPayload,
  type SyncStatusResponse,
} from '@/api/client'
import { useAuthStore } from '@/stores/authStore'
import { useSettingsStore } from '@/stores/settingsStore'
import { useSyncStore } from '@/stores/syncStore'
import { useTheme } from '@/theme'
import { SettingField, ENUM_OPTIONS, ModelSelect } from '@/components/admin/SettingField'

// Re-export so existing imports of ModelSelect from SettingsPage continue to work.
export { ENUM_OPTIONS, ModelSelect }

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

  const groupOrder = [
    'cupra_connect',
    'sync',
    'telegram',
    'openai',
    'cost',
    'display',
    'locations',
  ]
  const orderedGroups = groupOrder.filter((g) => grouped[g])
  for (const g of Object.keys(grouped)) {
    if (!groupOrder.includes(g)) orderedGroups.push(g)
  }

  const TAB_LABEL: Record<string, string> = {
    cupra_connect: 'Cupra Connect',
    sync: 'Sync',
    telegram: 'Telegram',
    openai: 'OpenAI',
    cost: 'Cost',
    display: 'Display',
    locations: 'Locations',
  }

  // The pycupra sync stack is gated off by default in standalone mode; the
  // manual sync controls are only meaningful when it is enabled.
  const pycupraEnabled = useMemo(() => {
    const raw = settings['pycupra_enabled']?.value
    return raw === 'true' || raw === '1'
  }, [settings])

  const [activeTab, setActiveTab] = useState<string>(orderedGroups[0] ?? 'cupra_connect')

  // If groups load after the first render, default to the first one.
  useEffect(() => {
    if (orderedGroups.length > 0 && !orderedGroups.includes(activeTab)) {
      setActiveTab(orderedGroups[0]!)
    }
  }, [orderedGroups, activeTab])

  async function handleLogout() {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <header className="mb-6 flex items-center justify-between">
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

      {/* Tab strip */}
      <div
        role="tablist"
        aria-label="Settings sections"
        className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-700"
      >
        {orderedGroups.map((group) => {
          const isActive = group === activeTab
          return (
            <button
              key={group}
              type="button"
              role="tab"
              aria-selected={isActive}
              data-testid={`settings-tab-${group}`}
              onClick={() => setActiveTab(group)}
              className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm transition ${
                isActive
                  ? 'border-indigo-600 font-medium text-indigo-700 dark:text-indigo-300'
                  : 'border-transparent text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100'
              }`}
            >
              {TAB_LABEL[group] ?? group.replace(/_/g, ' ')}
            </button>
          )
        })}
      </div>

      {/* Tab body — only the active group renders */}
      {orderedGroups.includes(activeTab) && grouped[activeTab] && (
        <section role="tabpanel" data-testid={`settings-panel-${activeTab}`}>
          <div className="space-y-4 rounded border border-slate-200 p-4 dark:border-slate-700">
            {grouped[activeTab]!.map((entry) => (
              <SettingRow key={entry.key} entry={entry} />
            ))}
            {activeTab === 'cupra_connect' && <ClearTokensButton />}
            {activeTab === 'sync' && pycupraEnabled && <SyncControlsPanel />}
            {(activeTab === 'telegram' || activeTab === 'openai') && <TestConnectionPanel />}
          </div>
        </section>
      )}
    </div>
  )
}

export function TestConnectionPanel() {
  const [report, setReport] = useState<HealthReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function run() {
    setBusy(true)
    setErr(null)
    try {
      setReport(await api.testTelegram())
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Test failed')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="border-t border-slate-200 pt-4 dark:border-slate-700">
      <button
        type="button"
        onClick={run}
        disabled={busy}
        className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50"
      >
        {busy ? 'Testing…' : 'Test connection'}
      </button>
      {err && <p role="alert" className="mt-2 text-xs text-red-600">{err}</p>}
      {report && (
        <ul className="mt-2 space-y-1 text-sm">
          {report.checks.map((c) => (
            <li key={c.name} className={c.ok ? 'text-emerald-600' : 'text-red-600'}>
              {c.ok ? '✓' : '✗'} {c.name}: {c.detail}
            </li>
          ))}
          {report.usage_this_month && (
            <li className="text-slate-500">
              📊 This month:{' '}
              {report.usage_this_month.input_tokens + report.usage_this_month.output_tokens} tokens
              {report.usage_this_month.cost_pence != null &&
                ` · £${(report.usage_this_month.cost_pence / 100).toFixed(2)}`}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

interface ToastState {
  kind: 'success' | 'error'
  message: string
}

function ClearTokensButton() {
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)

  useEffect(() => {
    if (toast === null) return
    const handle = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(handle)
  }, [toast])

  const handleClick = async () => {
    if (
      !window.confirm(
        "This will sign out all Cupra connections. You'll need to re-enter your credentials.",
      )
    ) {
      return
    }
    setBusy(true)
    try {
      await api.clearPycupraTokens()
      setToast({
        kind: 'success',
        message: 'Tokens cleared. Re-enter your password to reconnect.',
      })
    } catch (err) {
      setToast({
        kind: 'error',
        message: err instanceof ApiError ? err.message : 'Failed to clear tokens',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="border-t border-slate-200 pt-4 dark:border-slate-700">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="rounded border border-amber-300 bg-amber-50 px-3 py-1.5 text-sm font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
        data-testid="clear-pycupra-tokens-button"
      >
        Clear cached Cupra tokens
      </button>
      <p className="mt-1 text-xs text-slate-500">
        Wipes the on-disk token cache. Use after a password change or if
        background sync starts failing with credentials_invalid.
      </p>
      {toast && (
        <p
          role="status"
          data-testid="clear-pycupra-tokens-toast"
          className={
            'mt-2 text-xs ' +
            (toast.kind === 'success'
              ? 'text-emerald-600'
              : 'text-red-600')
          }
        >
          {toast.message}
        </p>
      )}
    </div>
  )
}

function QuotaIndicator({ status }: { status: SyncStatusResponse }) {
  const { requests_today, request_budget, quota_state } = status
  const fraction = request_budget > 0 ? Math.min(requests_today / request_budget, 1) : 0
  const pct = Math.round(fraction * 100)

  const barColor =
    quota_state === 'paused'
      ? 'bg-red-500'
      : quota_state === 'stretching'
        ? 'bg-amber-400'
        : 'bg-slate-400'

  const labelColor =
    quota_state === 'paused'
      ? 'text-red-600 dark:text-red-400'
      : quota_state === 'stretching'
        ? 'text-amber-600 dark:text-amber-400'
        : 'text-slate-500'

  return (
    <div
      data-testid="quota-indicator"
      className="mb-3 rounded border border-slate-200 p-3 dark:border-slate-700"
    >
      <div className={`mb-1 text-xs font-medium ${labelColor}`}>
        API calls today: {requests_today} / {request_budget}
        {quota_state === 'paused' && (
          <span className="ml-2 font-normal">— paused until tomorrow to protect the shared Cupra quota</span>
        )}
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function SyncControlsPanel() {
  const [cars, setCars] = useState<CarPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyCarId, setBusyCarId] = useState<number | null>(null)
  const [toasts, setToasts] = useState<Record<number, { kind: 'success' | 'error'; message: string }>>({})
  const [syncStatus, setSyncStatus] = useState<SyncStatusResponse | null>(null)
  const startStream = useSyncStore((s) => s.startStream)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const [list, status] = await Promise.all([api.getCars(), api.getSyncStatus()])
        if (!cancelled) {
          setCars(list)
          setSyncStatus(status)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  function setToast(carId: number, t: { kind: 'success' | 'error'; message: string }) {
    setToasts((prev) => ({ ...prev, [carId]: t }))
    window.setTimeout(() => {
      setToasts((prev) => {
        const next = { ...prev }
        delete next[carId]
        return next
      })
    }, 5000)
  }

  async function handleForceSync(carId: number) {
    setBusyCarId(carId)
    try {
      const res = await api.syncCar(carId)
      // Open the SSE stream so the dashboard's syncStore subscription
      // sees the job appear and disappear → triggers an auto-refresh
      // of the dashboard panels when the sync completes.
      startStream(carId, res.job_id, `/api/sync/stream/${res.job_id}`, 'force')
      setToast(carId, {
        kind: 'success',
        message: `Sync queued (job ${res.job_id.slice(0, 8)}…). Dashboard will update when it finishes.`,
      })
    } catch (err) {
      setToast(carId, {
        kind: 'error',
        message: err instanceof ApiError ? err.message : 'Sync failed',
      })
    } finally {
      setBusyCarId(null)
    }
  }

  return (
    <div className="border-t border-slate-200 pt-4 dark:border-slate-700">
      <h3 className="mb-2 text-sm font-medium">Manual sync controls</h3>
      <p className="mb-3 text-xs text-slate-500">
        <strong>Force sync</strong> re-runs the state poll immediately using cached cloud data — cheap, fast.
      </p>
      {loading && <p className="text-sm text-slate-500">Loading cars…</p>}
      {error && (
        <div role="alert" className="mb-3 text-sm text-red-600">
          {error}
        </div>
      )}
      {syncStatus && <QuotaIndicator status={syncStatus} />}
      {!loading && cars.length === 0 && (
        <p className="text-sm text-slate-500">No cars yet.</p>
      )}
      <ul className="space-y-2">
        {cars.map((car) => {
          const toast = toasts[car.id]
          return (
            <li
              key={car.id}
              className="rounded border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm">
                  <span className="font-medium">
                    {car.make} {car.model}
                  </span>
                  {car.provider_vehicle_id && (
                    <span className="ml-2 font-mono text-xs text-slate-500">
                      {car.provider_vehicle_id}
                    </span>
                  )}
                </div>
                <div className="flex flex-shrink-0 gap-2">
                  <button
                    type="button"
                    onClick={() => void handleForceSync(car.id)}
                    disabled={busyCarId === car.id}
                    className="rounded border border-indigo-300 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 dark:border-indigo-600 dark:bg-indigo-950 dark:text-indigo-200"
                    data-testid={`settings-force-sync-${car.id}`}
                  >
                    Force sync
                  </button>
                </div>
              </div>
              {toast && (
                <p
                  className={`mt-2 text-xs ${
                    toast.kind === 'success' ? 'text-emerald-600' : 'text-red-600'
                  }`}
                  role="status"
                >
                  {toast.message}
                </p>
              )}
            </li>
          )
        })}
      </ul>
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
          <SettingField
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

