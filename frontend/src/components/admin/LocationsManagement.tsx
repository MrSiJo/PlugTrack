/**
 * LocationsManagement — relocated from Locations.tsx (Phase B5).
 *
 * Handles:
 *   - List all user locations
 *   - Add location (toggles LocationCreateForm)
 *   - Per-row Delete (confirm + api.deleteLocation)
 *   - Per-row Merge-into picker + Merge button (api.mergeLocations)
 *
 * Does NOT handle:
 *   - Browse map, aggregates, in-context edit — those stay in Locations.tsx.
 */
import { useEffect, useMemo, useState } from 'react'
import { ApiError, api, type LocationListPayload } from '@/api/client'
import { LocationCreateForm } from '@/components/locations/LocationCreateForm'

interface Toast {
  kind: 'success' | 'error'
  message: string
}

function formatCoord(lat: number, lng: number): string {
  return `${lat.toFixed(4)}, ${lng.toFixed(4)}`
}

function unlabelledTitle(loc: LocationListPayload): string {
  return `Unlabelled at ${formatCoord(loc.centroid_lat, loc.centroid_lng)}`
}

export function LocationsManagement() {
  const [locations, setLocations] = useState<LocationListPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<Toast | null>(null)
  const [creating, setCreating] = useState(false)

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

  // Auto-clear toast after 4 s.
  useEffect(() => {
    if (toast === null) return
    const handle = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(handle)
  }, [toast])

  return (
    <div data-testid="locations-management">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Create, delete, and merge locations. To rename or adjust rates, use the
          in-context edit on the{' '}
          <a
            href="/locations"
            className="text-indigo-600 underline dark:text-indigo-400"
          >
            Locations page
          </a>
          .
        </p>
        <button
          type="button"
          onClick={() => setCreating((c) => !c)}
          className="ml-4 rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500"
          data-testid="admin-add-location-button"
        >
          {creating ? 'Close' : 'Add location'}
        </button>
      </div>

      {toast && (
        <div
          role="status"
          data-testid="locations-mgmt-toast"
          className={
            'mb-3 rounded p-3 text-sm ' +
            (toast.kind === 'success'
              ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
              : 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-200')
          }
        >
          {toast.message}
        </div>
      )}

      {creating && (
        <LocationCreateForm
          onCreated={async () => {
            setCreating(false)
            await refresh()
          }}
          onCancel={() => setCreating(false)}
          onToast={setToast}
        />
      )}

      {error && (
        <div role="alert" className="mb-3 text-sm text-red-600">
          {error}
        </div>
      )}

      {loading && <p className="text-sm text-slate-500">Loading…</p>}

      {!loading && locations.length === 0 && (
        <p className="text-sm text-slate-500">No locations yet.</p>
      )}

      <ul className="space-y-2" data-testid="admin-locations-list">
        {locations.map((loc) => (
          <LocationManagementRow
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

interface LocationManagementRowProps {
  loc: LocationListPayload
  allLocations: LocationListPayload[]
  onChanged: () => Promise<void>
  onToast: (t: Toast) => void
}

function LocationManagementRow({
  loc,
  allLocations,
  onChanged,
  onToast,
}: LocationManagementRowProps) {
  const [mergeTargetId, setMergeTargetId] = useState<string>('')
  const [busy, setBusy] = useState(false)

  const mergeCandidates = useMemo(
    () => allLocations.filter((l) => l.id !== loc.id),
    [allLocations, loc.id],
  )

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
        message: `Merged: ${result.sessions_redirected} session(s) moved.`,
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
      className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-200 px-4 py-2 dark:border-slate-700"
      data-testid="admin-location-row"
      data-location-id={loc.id}
    >
      <span className="text-sm font-medium text-slate-800 dark:text-slate-100">
        {loc.name ?? unlabelledTitle(loc)}
      </span>

      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Merge target"
          value={mergeTargetId}
          onChange={(e) => setMergeTargetId(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-800"
          data-testid={`admin-merge-target-${loc.id}`}
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
          onClick={() => void handleMerge()}
          disabled={busy || mergeTargetId === ''}
          className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
          data-testid={`admin-merge-button-${loc.id}`}
        >
          Merge
        </button>
        <button
          type="button"
          onClick={() => void handleDelete()}
          disabled={busy}
          className="rounded border border-red-300 px-3 py-1 text-xs font-medium text-red-700 disabled:opacity-50 dark:border-red-700 dark:text-red-300"
          data-testid={`admin-delete-button-${loc.id}`}
        >
          Delete
        </button>
      </div>
    </li>
  )
}
