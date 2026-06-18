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
  type LocationCreateRequest,
  type LocationListPayload,
} from '@/api/client'
import { LocationEditForm } from '@/components/locations/LocationEditForm'
import { LocationsMap } from '@/components/locations/LocationsMap'
import { LocationPickerMap } from '@/components/locations/LocationPickerMap'
import { PageHeader } from '@/components/ui/PageHeader'
import { useSetting } from '@/stores/settingsStore'

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

  // Auto-clear toast after 4s.
  useEffect(() => {
    if (toast === null) return
    const handle = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(handle)
  }, [toast])

  const homeRateRaw = useSetting<string>('default_home_rate_p_per_kwh') ?? '0'
  const homeRatePence = Number(homeRateRaw) || 0
  const currency = useSetting<string>('currency') ?? 'GBP'

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <PageHeader
        title="Locations"
        subtitle="Map shows where you charge — colour = cost band, size = visits. Edits here are forward-going only; use Recalculate past costs to re-apply this location's tariff to historical sessions."
        actions={
          <button
            type="button"
            onClick={() => setCreating((c) => !c)}
            className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500"
            data-testid="add-location-button"
          >
            {creating ? 'Close' : 'Add location'}
          </button>
        }
      />

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

      {!loading && locations.length > 0 && (
        <div className="mb-6">
          <LocationsMap
            locations={locations}
            homeRatePence={homeRatePence}
            currency={currency}
          />
        </div>
      )}

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

interface LocationCreateFormProps {
  onCreated: () => Promise<void>
  onCancel: () => void
  onToast: (t: Toast) => void
}

function LocationCreateForm({
  onCreated,
  onCancel,
  onToast,
}: LocationCreateFormProps) {
  const [name, setName] = useState('')
  const [lat, setLat] = useState<number | null>(null)
  const [lng, setLng] = useState<number | null>(null)
  const [radiusM, setRadiusM] = useState('100')
  const [defaultRate, setDefaultRate] = useState('')
  const [defaultNetwork, setDefaultNetwork] = useState('')
  const [isHome, setIsHome] = useState(false)
  const [isFree, setIsFree] = useState(false)
  const [busy, setBusy] = useState(false)
  const [geoBusy, setGeoBusy] = useState(false)
  const [addressQuery, setAddressQuery] = useState('')
  const [searching, setSearching] = useState(false)

  const latText = lat === null ? '' : String(lat)
  const lngText = lng === null ? '' : String(lng)

  const handlePick = (pickedLat: number, pickedLng: number) => {
    // Round to 6dp — ~0.1 m precision, plenty for a charge site centroid.
    setLat(Number(pickedLat.toFixed(6)))
    setLng(Number(pickedLng.toFixed(6)))
  }

  const handleUseMyLocation = () => {
    if (!('geolocation' in navigator)) {
      onToast({ kind: 'error', message: 'Geolocation not available in this browser.' })
      return
    }
    setGeoBusy(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        handlePick(pos.coords.latitude, pos.coords.longitude)
        setGeoBusy(false)
      },
      (err) => {
        setGeoBusy(false)
        onToast({ kind: 'error', message: `Couldn't get your location: ${err.message}` })
      },
      { enableHighAccuracy: true, timeout: 10_000 },
    )
  }

  const handleFindByAddress = async () => {
    if (addressQuery.trim() === '') {
      onToast({ kind: 'error', message: 'Type an address or place to search.' })
      return
    }
    setSearching(true)
    try {
      const r = await api.geocode(addressQuery.trim())
      handlePick(r.lat, r.lng)
      if (name.trim() === '') setName(addressQuery.trim())
      onToast({ kind: 'success', message: `Found: ${r.address}` })
    } catch (err) {
      onToast({
        kind: 'error',
        message:
          err instanceof ApiError
            ? err.status === 404
              ? 'No match for that address — try adding the town or postcode.'
              : err.message
            : 'Address search failed',
      })
    } finally {
      setSearching(false)
    }
  }

  const handleCreate = async () => {
    if (lat === null || lng === null) {
      onToast({ kind: 'error', message: 'Pick a point on the map or type a lat/lng.' })
      return
    }
    setBusy(true)
    try {
      const payload: LocationCreateRequest = {
        name: name.trim() === '' ? null : name.trim(),
        centroid_lat: lat,
        centroid_lng: lng,
        radius_m: Number(radiusM) || 100,
        is_home: isHome,
        is_free: isFree,
        default_cost_per_kwh_p: defaultRate === '' ? null : Number(defaultRate),
        default_charge_network:
          defaultNetwork.trim() === '' ? null : defaultNetwork.trim(),
      }
      await api.createLocation(payload)
      onToast({ kind: 'success', message: 'Location created.' })
      await onCreated()
    } catch (err) {
      onToast({
        kind: 'error',
        message: err instanceof ApiError ? err.message : 'Create failed',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="mb-6 rounded border border-indigo-200 bg-indigo-50/40 p-4 dark:border-indigo-900 dark:bg-indigo-950/20"
      data-testid="location-create-form"
    >
      <h2 className="mb-3 text-sm font-semibold">New location</h2>
      <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
        Search by address, click the map to drop a pin, type coordinates
        directly, or use your current location. Set a default rate now so
        charges here are costed correctly instead of falling back to the home
        rate.
      </p>

      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-1 flex-col gap-1 text-xs">
          <span className="font-medium">Find by address</span>
          <input
            type="text"
            value={addressQuery}
            onChange={(e) => setAddressQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void handleFindByAddress()
              }
            }}
            placeholder="e.g. Instavolt McDonalds, Lysander Road, Yeovil"
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
            data-testid="geocode-query-input"
          />
        </label>
        <button
          type="button"
          onClick={handleFindByAddress}
          disabled={searching}
          className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          data-testid="geocode-search-button"
        >
          {searching ? 'Searching…' : 'Find'}
        </button>
      </div>

      <div className="mb-3">
        <LocationPickerMap lat={lat} lng={lng} onPick={handlePick} />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Tesla Camborne"
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
            data-testid="create-name-input"
          />
        </label>
        <div className="flex items-end gap-2">
          <label className="flex flex-1 flex-col gap-1 text-xs">
            <span className="font-medium">Latitude</span>
            <input
              type="number"
              step="0.000001"
              value={latText}
              onChange={(e) =>
                setLat(e.target.value === '' ? null : Number(e.target.value))
              }
              className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
              data-testid="create-lat-input"
            />
          </label>
          <label className="flex flex-1 flex-col gap-1 text-xs">
            <span className="font-medium">Longitude</span>
            <input
              type="number"
              step="0.000001"
              value={lngText}
              onChange={(e) =>
                setLng(e.target.value === '' ? null : Number(e.target.value))
              }
              className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
              data-testid="create-lng-input"
            />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Default cost (p/kWh)</span>
          <input
            type="number"
            min="0"
            step="0.1"
            value={defaultRate}
            onChange={(e) => setDefaultRate(e.target.value)}
            placeholder="e.g. 45"
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Default charge network</span>
          <input
            type="text"
            value={defaultNetwork}
            onChange={(e) => setDefaultNetwork(e.target.value)}
            placeholder="e.g. Tesla, MFG, Outfox Energy"
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
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
          onClick={handleCreate}
          disabled={busy}
          className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          data-testid="create-location-submit"
        >
          Create location
        </button>
        <button
          type="button"
          onClick={handleUseMyLocation}
          disabled={geoBusy}
          className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
        >
          {geoBusy ? 'Locating…' : 'Use my location'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="ml-auto rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
        >
          Cancel
        </button>
      </div>
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
  const [mergeTargetId, setMergeTargetId] = useState<string>('')
  const [busy, setBusy] = useState(false)

  const isUnlabelled = loc.name === null

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

      <LocationEditForm
        location={loc}
        showRadius
        onSaved={onChanged}
        onToast={onToast}
      />

      <div className="mt-4 flex flex-wrap items-center gap-2">
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
