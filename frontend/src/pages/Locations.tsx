/**
 * Locations admin page (Phase 5.3).
 *
 * Inline-edit per row (no modal). Per-row actions:
 *   - Save (PUT — forward-going only, never recomputes past costs).
 *   - Recalculate past costs (explicit, with confirm).
 *   - Merge into another location (picker dropdown).
 *   - Delete (with confirm).
 *
 * Unlabelled locations (`name === null`) float to the top with a
 * "Needs labelling" badge — that's a hint to use the Sessions page's
 * label-on-first-visit flow rather than this admin page (PUT here is
 * forward-only and won't recompute history).
 *
 * NOTE: A map preview was scoped for this view (react-leaflet) but
 * skipped to avoid pulling in another dependency for v1. Each row
 * shows the centroid lat/lng instead. We can add the map in a later
 * iteration without changing the API surface.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  ApiError,
  api,
  type LocationListPayload,
  type LocationUpdateRequest,
} from '@/api/client'

interface Toast {
  kind: 'success' | 'error'
  message: string
}

function formatCostPence(pence: number): string {
  if (pence === 0) return '£0.00'
  return `£${(pence / 100).toFixed(2)}`
}

function formatCoord(lat: number, lng: number): string {
  return `${lat.toFixed(4)}, ${lng.toFixed(4)}`
}

function unlabelledTitle(loc: LocationListPayload): string {
  return `Unlabelled at ${formatCoord(loc.centroid_lat, loc.centroid_lng)}`
}

export default function Locations() {
  const [locations, setLocations] = useState<LocationListPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<Toast | null>(null)

  const refresh = async () => {
    try {
      const data = await api.getLocations()
      setLocations(data)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load locations')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  // Auto-clear toast after 4s.
  useEffect(() => {
    if (toast === null) return
    const handle = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(handle)
  }, [toast])

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Locations</h1>
        <p className="mt-1 text-sm text-slate-500">
          Edits here are forward-going only. Use{' '}
          <em>Recalculate past costs</em> to re-apply this location&apos;s
          tariff to historical sessions. Override-cost sessions are never
          touched.
        </p>
      </header>

      {toast && (
        <div
          role="status"
          data-testid="locations-toast"
          className={
            'mb-4 rounded p-3 text-sm ' +
            (toast.kind === 'success'
              ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
              : 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-200')
          }
        >
          {toast.message}
        </div>
      )}

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && (
        <div role="alert" className="text-sm text-red-600">
          {error}
        </div>
      )}
      {!loading && locations.length === 0 && (
        <p className="text-sm text-slate-500">No locations yet.</p>
      )}

      <ul className="space-y-3" data-testid="locations-list">
        {locations.map((loc) => (
          <LocationRow
            key={loc.id}
            loc={loc}
            allLocations={locations}
            onChanged={refresh}
            onToast={setToast}
          />
        ))}
      </ul>
    </div>
  )
}

interface LocationRowProps {
  loc: LocationListPayload
  allLocations: LocationListPayload[]
  onChanged: () => Promise<void>
  onToast: (t: Toast) => void
}

function LocationRow({ loc, allLocations, onChanged, onToast }: LocationRowProps) {
  const [name, setName] = useState<string>(loc.name ?? '')
  const [isHome, setIsHome] = useState<boolean>(loc.is_home)
  const [isFree, setIsFree] = useState<boolean>(loc.is_free)
  const [defaultRate, setDefaultRate] = useState<string>(
    loc.default_cost_per_kwh_p === null ? '' : String(loc.default_cost_per_kwh_p),
  )
  const [defaultNetwork, setDefaultNetwork] = useState<string>(
    loc.default_charge_network ?? '',
  )
  const [radiusM, setRadiusM] = useState<string>(String(loc.radius_m))
  const [mergeTargetId, setMergeTargetId] = useState<string>('')
  const [busy, setBusy] = useState(false)

  // Re-sync local state when the parent list refreshes.
  useEffect(() => {
    setName(loc.name ?? '')
    setIsHome(loc.is_home)
    setIsFree(loc.is_free)
    setDefaultRate(
      loc.default_cost_per_kwh_p === null ? '' : String(loc.default_cost_per_kwh_p),
    )
    setDefaultNetwork(loc.default_charge_network ?? '')
    setRadiusM(String(loc.radius_m))
  }, [loc])

  const isUnlabelled = loc.name === null

  const mergeCandidates = useMemo(
    () => allLocations.filter((l) => l.id !== loc.id),
    [allLocations, loc.id],
  )

  const handleSave = async () => {
    setBusy(true)
    try {
      const payload: LocationUpdateRequest = {
        name: name === '' ? null : name,
        is_home: isHome,
        is_free: isFree,
        default_cost_per_kwh_p:
          defaultRate === '' ? null : Number(defaultRate),
        default_charge_network:
          defaultNetwork.trim() === '' ? null : defaultNetwork.trim(),
        radius_m: Number(radiusM),
      }
      await api.updateLocation(loc.id, payload)
      onToast({ kind: 'success', message: 'Saved.' })
      await onChanged()
    } catch (err) {
      onToast({
        kind: 'error',
        message: err instanceof ApiError ? err.message : 'Save failed',
      })
    } finally {
      setBusy(false)
    }
  }

  const handleRecalculate = async () => {
    if (
      !window.confirm(
        'Re-apply this location\'s tariff to all past non-override sessions linked here?',
      )
    ) {
      return
    }
    setBusy(true)
    try {
      const result = await api.recalculateLocationPastCosts(loc.id)
      onToast({
        kind: 'success',
        message: `Recomputed ${result.sessions_recomputed_count} session(s).`,
      })
      await onChanged()
    } catch (err) {
      onToast({
        kind: 'error',
        message:
          err instanceof ApiError ? err.message : 'Recalculate failed',
      })
    } finally {
      setBusy(false)
    }
  }

  const handleMerge = async () => {
    const targetId = Number(mergeTargetId)
    if (!Number.isFinite(targetId) || targetId <= 0) {
      onToast({ kind: 'error', message: 'Pick a target location to merge into.' })
      return
    }
    if (
      !window.confirm(
        `Merge "${loc.name ?? unlabelledTitle(loc)}" into the selected location? This deletes the source row.`,
      )
    ) {
      return
    }
    setBusy(true)
    try {
      const result = await api.mergeLocations(loc.id, targetId)
      onToast({
        kind: 'success',
        message: `Merged: ${result.sessions_redirected} session(s) and ${result.plug_ins_redirected} plug-in(s) moved.`,
      })
      await onChanged()
    } catch (err) {
      onToast({
        kind: 'error',
        message: err instanceof ApiError ? err.message : 'Merge failed',
      })
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (
      !window.confirm(
        `Delete "${loc.name ?? unlabelledTitle(loc)}"? Sessions stay (they fall back to the global home rate).`,
      )
    ) {
      return
    }
    setBusy(true)
    try {
      await api.deleteLocation(loc.id)
      onToast({ kind: 'success', message: 'Location deleted.' })
      await onChanged()
    } catch (err) {
      onToast({
        kind: 'error',
        message: err instanceof ApiError ? err.message : 'Delete failed',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <li
      className="rounded border border-slate-200 p-4 dark:border-slate-700"
      data-testid="location-row"
      data-location-id={loc.id}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-medium">
          {loc.name ?? unlabelledTitle(loc)}
        </h2>
        {isUnlabelled && (
          <span
            className="rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900 dark:text-amber-200"
            data-testid="needs-labelling-badge"
          >
            Needs labelling
          </span>
        )}
        {loc.is_home && (
          <span className="rounded bg-sky-100 px-2 py-0.5 text-xs font-medium text-sky-800 dark:bg-sky-900 dark:text-sky-200">
            Home
          </span>
        )}
        {loc.is_free && (
          <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200">
            Free
          </span>
        )}
        {loc.default_charge_network && (
          <span
            className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-200"
            data-testid="location-network-badge"
          >
            {loc.default_charge_network}
          </span>
        )}
      </div>

      <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-500 sm:grid-cols-4">
        <div>
          <dt className="font-medium uppercase tracking-wide">Visits</dt>
          <dd>{loc.visit_count}</dd>
        </div>
        <div>
          <dt className="font-medium uppercase tracking-wide">Total kWh</dt>
          <dd>{loc.total_kwh.toFixed(2)}</dd>
        </div>
        <div>
          <dt className="font-medium uppercase tracking-wide">Total cost</dt>
          <dd>{formatCostPence(loc.total_cost_pence)}</dd>
        </div>
        <div>
          <dt className="font-medium uppercase tracking-wide">Centroid</dt>
          <dd>{formatCoord(loc.centroid_lat, loc.centroid_lng)}</dd>
        </div>
        {loc.address && (
          <div className="col-span-2 sm:col-span-4">
            <dt className="font-medium uppercase tracking-wide">Address</dt>
            <dd>{loc.address}</dd>
          </div>
        )}
      </dl>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
            data-testid={`name-input-${loc.id}`}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Default cost (p/kWh)</span>
          <input
            type="number"
            min="0"
            step="0.1"
            value={defaultRate}
            onChange={(e) => setDefaultRate(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Default charge network</span>
          <input
            type="text"
            value={defaultNetwork}
            onChange={(e) => setDefaultNetwork(e.target.value)}
            placeholder="e.g. Outfox Energy, Tesla, MFG"
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
            data-testid={`default-network-input-${loc.id}`}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Cluster radius (m)</span>
          <input
            type="number"
            min="1"
            step="1"
            value={radiusM}
            onChange={(e) => setRadiusM(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
        <div className="flex items-center gap-3 text-xs">
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={isHome}
              onChange={(e) => setIsHome(e.target.checked)}
            />
            <span>Is home</span>
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={isFree}
              onChange={(e) => setIsFree(e.target.checked)}
            />
            <span>Is free</span>
          </label>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={busy}
          className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          data-testid={`save-button-${loc.id}`}
        >
          Save
        </button>
        <button
          type="button"
          onClick={handleRecalculate}
          disabled={busy}
          className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
          data-testid={`recalculate-button-${loc.id}`}
        >
          Recalculate past costs
        </button>
        <select
          aria-label="Merge target"
          value={mergeTargetId}
          onChange={(e) => setMergeTargetId(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-800"
          data-testid={`merge-target-${loc.id}`}
        >
          <option value="">Merge into…</option>
          {mergeCandidates.map((c) => (
            <option key={c.id} value={String(c.id)}>
              {c.name ?? `loc#${c.id}`}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleMerge}
          disabled={busy || mergeTargetId === ''}
          className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
          data-testid={`merge-button-${loc.id}`}
        >
          Merge
        </button>
        <button
          type="button"
          onClick={handleDelete}
          disabled={busy}
          className="ml-auto rounded border border-red-300 px-3 py-1 text-xs font-medium text-red-700 disabled:opacity-50 dark:border-red-700 dark:text-red-300"
          data-testid={`delete-button-${loc.id}`}
        >
          Delete
        </button>
      </div>
    </li>
  )
}
