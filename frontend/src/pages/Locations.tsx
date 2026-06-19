/**
 * Locations browse page (Phase 5.3 / B5 stripped).
 *
 * Shows the map, browse list with aggregates, and in-context edit
 * (LocationEditForm) per row.
 *
 * Create/delete/merge have moved to Admin → LocationsManagement.
 */
import { useEffect, useState } from 'react'
import {
  ApiError,
  api,
  type LocationListPayload,
} from '@/api/client'
import { LocationEditForm } from '@/components/locations/LocationEditForm'
import { LocationsMap } from '@/components/locations/LocationsMap'
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
        subtitle="Map shows where you charge — colour = cost band, size = visits. Edits here are forward-going only; use Recalculate past costs to re-apply this location's tariff to historical sessions. To add, delete, or merge locations use the Admin page."
      />

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
  onChanged: () => Promise<void>
  onToast: (t: Toast) => void
}

function LocationRow({ loc, onChanged, onToast }: LocationRowProps) {
  const isUnlabelled = loc.name === null

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
    </li>
  )
}
