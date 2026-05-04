/**
 * Sessions list page.
 *
 * Shows a paginated list of charging sessions with:
 * - Source badge (manual / synthesis / cariad)
 * - Distance via `formatDistance(km, unit)`
 * - Location pill — labelled name when available, else
 *   "Unlabelled · 51.0, -2.6"
 * - Cost pill colour-coded by `cost_basis`:
 *   green=`location_free`, blue=`override_*`, neutral otherwise.
 *
 * Phase 4 additions:
 * - Rows in `syncStore.recentlyImportedSessionIds` get a
 *   `data-highlighted="true"` attribute and a fade-in tailwind class.
 * - Header has a Force-sync + Wake button per active car. (Defaults to
 *   car_id=1 since multi-car selection lives in Phase 5.)
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ApiError,
  api,
  type ChargingSessionPayload,
  type CostBasis,
} from '@/api/client'
import { useDistanceUnit } from '@/stores/settingsStore'
import { useSyncStore } from '@/stores/syncStore'
import { formatDistance } from '@/utils/distance'

const SOURCE_BADGE_CLASS: Record<string, string> = {
  manual: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  synthesis: 'bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-200',
  cariad: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
}

const COST_BADGE_CLASS: Record<CostBasis, string> = {
  location_free: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  override_total: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  override_per_kwh: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  location_rate: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200',
  home_rate: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200',
  unknown: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
}

function formatCostPence(pence: number | null): string {
  if (pence === null) return '—'
  if (pence === 0) return '£0.00'
  return `£${(pence / 100).toFixed(2)}`
}

function locationLabel(s: ChargingSessionPayload): string {
  if (s.user_label) return s.user_label
  if (s.location_id === null) return 'No location'
  // The list endpoint doesn't currently expand location details (a
  // future optimisation); show "Unlabelled · loc#NN" as a placeholder.
  return `Unlabelled · loc#${s.location_id}`
}

interface SessionRowProps {
  session: ChargingSessionPayload
  unit: 'mi' | 'km'
  highlighted: boolean
}

function SessionRow({ session, unit, highlighted }: SessionRowProps) {
  const distanceKm = session.odometer_at_session_km
  return (
    <li
      className={
        'grid grid-cols-1 gap-2 rounded border p-3 text-sm md:grid-cols-[120px_120px_1fr_120px_120px_80px] ' +
        (highlighted
          ? 'animate-pulse border-emerald-400 bg-emerald-50 transition dark:border-emerald-600 dark:bg-emerald-950'
          : 'border-slate-200 dark:border-slate-700')
      }
      data-testid="session-row"
      data-highlighted={highlighted ? 'true' : 'false'}
    >
      <span className="font-mono text-xs text-slate-500">{session.date}</span>
      <span
        className={`inline-flex w-fit items-center rounded px-2 py-0.5 text-xs font-medium ${
          SOURCE_BADGE_CLASS[session.source] ?? SOURCE_BADGE_CLASS.manual
        }`}
        data-testid={`source-badge-${session.source}`}
      >
        {session.source}
      </span>
      <span data-testid="location-pill">{locationLabel(session)}</span>
      <span className="text-xs text-slate-500" data-testid="distance">
        {distanceKm !== null ? formatDistance(distanceKm, unit) : '—'}
      </span>
      <span
        className={`inline-flex w-fit items-center rounded px-2 py-0.5 text-xs font-medium ${COST_BADGE_CLASS[session.cost_basis]}`}
        data-testid={`cost-pill-${session.cost_basis}`}
      >
        {formatCostPence(session.cost_pence)}
      </span>
      <Link
        to={`/sessions/${session.id}`}
        className="text-xs text-indigo-600 underline"
      >
        Details
      </Link>
    </li>
  )
}

interface SyncControlsProps {
  carId: number
}

function SyncControls({ carId }: SyncControlsProps) {
  const startStream = useSyncStore((s) => s.startStream)
  const [busy, setBusy] = useState(false)
  const [wakeCooldown, setWakeCooldown] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (wakeCooldown === null || wakeCooldown <= 0) return
    const id = window.setInterval(() => {
      setWakeCooldown((s) => (s === null ? null : s <= 1 ? null : s - 1))
    }, 1000)
    return () => window.clearInterval(id)
  }, [wakeCooldown])

  const onForce = async () => {
    setBusy(true)
    setError(null)
    try {
      const job = await api.syncCar(carId)
      startStream(carId, job.job_id, job.stream_url, job.kind)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Force-sync failed')
    } finally {
      setBusy(false)
    }
  }

  const onWake = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.wakeCar(carId)
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        const retry = (err.body as { retry_after?: number } | null)?.retry_after ?? 1800
        setWakeCooldown(retry)
        setError(`Wake rate-limited; retry in ${retry}s`)
      } else {
        setError(err instanceof ApiError ? err.message : 'Wake failed')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="sync-controls">
      <button
        type="button"
        onClick={onForce}
        disabled={busy}
        className="rounded border border-indigo-300 bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 dark:border-indigo-600 dark:bg-indigo-950 dark:text-indigo-200"
        data-testid="force-sync-button"
      >
        Force sync
      </button>
      <button
        type="button"
        onClick={onWake}
        disabled={busy || (wakeCooldown !== null && wakeCooldown > 0)}
        className="rounded border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-600 dark:bg-amber-950 dark:text-amber-200"
        data-testid="wake-car-button"
      >
        {wakeCooldown && wakeCooldown > 0 ? `Wake (${wakeCooldown}s)` : 'Wake car'}
      </button>
      {error && (
        <span className="text-xs text-red-600" data-testid="sync-error">
          {error}
        </span>
      )}
    </div>
  )
}

export default function Sessions() {
  const [sessions, setSessions] = useState<ChargingSessionPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const unit = useDistanceUnit()
  const recentlyImported = useSyncStore((s) => s.recentlyImportedSessionIds)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await api.getSessions()
        if (!cancelled) {
          setSessions(data)
          setLoading(false)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Failed to load sessions')
          setLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Derive a default car_id for the sync controls. In Phase 5 this comes
  // from carsStore.activeCarId; for now use the first session's car.
  const defaultCarId = sessions[0]?.car_id ?? 1

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Charging sessions</h1>
        <SyncControls carId={defaultCarId} />
      </div>
      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && (
        <div role="alert" className="text-sm text-red-600">
          {error}
        </div>
      )}
      {!loading && sessions.length === 0 && (
        <p className="text-sm text-slate-500">No sessions yet.</p>
      )}
      <ul className="space-y-2">
        {sessions.map((s) => (
          <SessionRow
            key={s.id}
            session={s}
            unit={unit}
            highlighted={recentlyImported.includes(s.id)}
          />
        ))}
      </ul>
    </div>
  )
}
