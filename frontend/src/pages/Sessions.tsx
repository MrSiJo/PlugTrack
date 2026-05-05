/**
 * Sessions list page.
 *
 * Shows a paginated list of charging sessions with:
 * - Source badge (Manual / Cupra Connect / Cariad)
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

const SOURCE_BADGE_LABEL: Record<string, string> = {
  manual: 'Manual',
  synthesis: 'Cupra Connect',
  cariad: 'Cariad',
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
  if (s.location_name) return s.location_name
  if (s.location_id === null) return 'No location'
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
        {SOURCE_BADGE_LABEL[session.source] ?? session.source}
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

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Charging sessions</h1>
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
