/**
 * SyncControlsPanel — manual sync controls + quota indicator.
 * Moved from SettingsPage.tsx so IntegrationCard doesn't depend on the page.
 */

import { useEffect, useState } from 'react'
import { ApiError, api, type CarPayload, type SyncStatusResponse } from '@/api/client'
import { useSyncStore } from '@/stores/syncStore'

// ---------------------------------------------------------------------------
// QuotaIndicator
// ---------------------------------------------------------------------------

export function QuotaIndicator({ status }: { status: SyncStatusResponse }) {
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
          <span className="ml-2 font-normal">
            — paused until tomorrow to protect the shared Cupra quota
          </span>
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

// ---------------------------------------------------------------------------
// SyncControlsPanel
// ---------------------------------------------------------------------------

export function SyncControlsPanel() {
  const [cars, setCars] = useState<CarPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyCarId, setBusyCarId] = useState<number | null>(null)
  const [toasts, setToasts] = useState<
    Record<number, { kind: 'success' | 'error'; message: string }>
  >({})
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

  function setToast(
    carId: number,
    t: { kind: 'success' | 'error'; message: string },
  ) {
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
        <strong>Force sync</strong> re-runs the state poll immediately using cached cloud data —
        cheap, fast.
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
