/**
 * Dashboard — the post-login landing page.
 *
 * v1 ships four numeric panels (no charts):
 *   1. Per-car current state (battery level, cable, last sync, force-sync).
 *   2. Recent sessions table (last 10).
 *   3. Lifetime totals (kWh, cost, distance, session count).
 *   4. Top 5 locations by visit count.
 *
 * Distance values flow through `formatDistance(km)` from settingsStore so
 * the user's chosen unit (mi/km) wins on display. Cost values flow
 * through `formatCurrency(pence, currencyCode)` against the `currency`
 * setting (defaults to GBP).
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ApiError,
  api,
  type DashboardCarPanel,
  type DashboardLocationStat,
  type DashboardSessionRow,
  type DashboardSummary,
} from '@/api/client'
import {
  formatDistance,
  useDistanceUnit,
  useSetting,
} from '@/stores/settingsStore'
import { useSyncStore } from '@/stores/syncStore'
import { kmToMi } from '@/utils/distance'
import { formatCurrency } from '@/utils/currency'

const SOURCE_BADGE_CLASS: Record<string, string> = {
  manual: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  synthesis: 'bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-200',
  cariad:
    'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
}

const SOURCE_BADGE_LABEL: Record<string, string> = {
  manual: 'Manual',
  synthesis: 'Cupra Connect',
  cariad: 'Cariad',
}

function formatRelative(iso: string | null): string {
  if (!iso) return 'never'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return 'never'
  const delta = Date.now() - t
  if (delta < 0) {
    const ahead = Math.round(-delta / 1000)
    if (ahead < 60) return `in ${ahead}s`
    if (ahead < 3600) return `in ${Math.round(ahead / 60)}m`
    return `in ${Math.round(ahead / 3600)}h`
  }
  const seconds = Math.round(delta / 1000)
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86_400)}d ago`
}

interface CarPanelCardProps {
  car: DashboardCarPanel
}

const STATE_LABEL: Record<string, string> = {
  IDLE: 'Disconnected',
  PLUGGED_IN: 'Plugged in (not charging)',
  CHARGING: 'Charging',
  CHARGING_DONE: 'Charge complete',
}

const STATE_PILL_CLASS: Record<string, string> = {
  IDLE: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  PLUGGED_IN:
    'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  CHARGING:
    'bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200',
  CHARGING_DONE:
    'bg-sky-100 text-sky-800 dark:bg-sky-900 dark:text-sky-200',
}

function CarPanelCard({ car }: CarPanelCardProps) {
  const stateLabel = car.last_state ? STATE_LABEL[car.last_state] ?? car.last_state : null
  const statePillClass = car.last_state
    ? STATE_PILL_CLASS[car.last_state] ?? STATE_PILL_CLASS.IDLE
    : null
  const locationDisplay = car.location_address
    ? car.location_name
      ? `${car.location_name} · ${car.location_address}`
      : car.location_address
    : car.location_name
  const unit = useDistanceUnit()
  const isCharging = car.last_state === 'CHARGING'
  // Range: prefer the user's display unit. Round to int.
  const rangeDisplay =
    car.electric_range_km !== null && car.electric_range_km !== undefined
      ? unit === 'mi'
        ? `${Math.round(kmToMi(car.electric_range_km))} mi`
        : `${car.electric_range_km} km`
      : null
  // Charge rate (mi/h or km/h) = power_kW × nominal_efficiency_mi_per_kwh,
  // then convert if user prefers km. Only meaningful while CHARGING.
  let chargeRateDisplay: string | null = null
  if (
    isCharging &&
    car.charging_power_kw !== null &&
    car.charging_power_kw !== undefined &&
    car.charging_power_kw > 0 &&
    car.nominal_efficiency_mi_per_kwh
  ) {
    const miPerHour = car.charging_power_kw * car.nominal_efficiency_mi_per_kwh
    chargeRateDisplay =
      unit === 'mi'
        ? `${miPerHour.toFixed(1)} mi/h`
        : `${(miPerHour / 0.621371).toFixed(1)} km/h`
  }
  return (
    <li
      className="rounded border border-slate-200 bg-white p-4 text-sm shadow-sm dark:border-slate-700 dark:bg-slate-900"
      data-testid={`car-panel-${car.id}`}
    >
      <div className="min-w-0 flex-1">
        <h3 className="font-semibold">
          {car.make} {car.model}
        </h3>
        {stateLabel && (
          <div className="mt-2">
            <span
              className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${statePillClass}`}
              data-testid="state-pill"
            >
              {stateLabel}
            </span>
          </div>
        )}
        <div className="mt-2 text-xs text-slate-500" data-testid="car-soc">
          Battery:{' '}
          <span className="font-mono">
            {car.battery_level ?? '—'}
            {car.battery_level !== null ? '%' : ''}
          </span>
          {car.target_soc !== null && car.target_soc !== undefined && (
            <span className="ml-1 text-slate-400">
              (target {car.target_soc}%)
            </span>
          )}
        </div>
        {rangeDisplay && (
          <div className="mt-1 text-xs text-slate-500" data-testid="car-range">
            Range: <span className="font-mono">{rangeDisplay}</span>
          </div>
        )}
        {isCharging && car.charging_power_kw !== null && car.charging_power_kw !== undefined && car.charging_power_kw > 0 && (
          <div className="mt-1 text-xs text-emerald-600 dark:text-emerald-400" data-testid="car-charging">
            Charging at{' '}
            <span className="font-mono">{car.charging_power_kw.toFixed(1)} kW</span>
            {chargeRateDisplay && (
              <span className="ml-1 text-slate-500">({chargeRateDisplay})</span>
            )}
          </div>
        )}
        {locationDisplay && (
          <div className="mt-1 truncate text-xs text-slate-500" data-testid="car-location">
            Location: {locationDisplay}
          </div>
        )}
        <div className="mt-1 text-xs text-slate-500">
          Last seen: {formatRelative(car.last_connected)}
        </div>
        <div className="text-xs text-slate-500">
          Next sync: {formatRelative(car.next_poll_at)}
        </div>
      </div>
    </li>
  )
}

interface SessionRowDisplayProps {
  row: DashboardSessionRow
  unit: 'mi' | 'km'
  currency: string
}

function SessionRowDisplay({ row, currency }: SessionRowDisplayProps) {
  const locationLabel =
    row.location_name ?? (row.location_id ? `loc#${row.location_id}` : '—')
  return (
    <tr
      className="border-b border-slate-200 last:border-b-0 dark:border-slate-700"
      data-testid={`recent-session-${row.id}`}
    >
      <td className="px-3 py-2 text-xs font-mono">{row.date}</td>
      <td className="px-3 py-2 text-xs">{row.car_label}</td>
      <td className="px-3 py-2 text-xs text-right">{row.kwh_added.toFixed(2)} kWh</td>
      <td className="px-3 py-2 text-xs text-right">
        {formatCurrency(row.cost_pence, currency)}
      </td>
      <td className="px-3 py-2 text-xs">
        {row.location_id !== null ? (
          <Link
            to={`/locations/${row.location_id}`}
            className="text-indigo-600 underline"
          >
            {locationLabel}
          </Link>
        ) : (
          <span className="text-slate-500">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-xs">
        <span
          className={`inline-flex items-center rounded px-2 py-0.5 text-[10px] font-medium ${
            SOURCE_BADGE_CLASS[row.source] ?? SOURCE_BADGE_CLASS.manual
          }`}
        >
          {SOURCE_BADGE_LABEL[row.source] ?? row.source}
        </span>
      </td>
      <td className="px-3 py-2 text-xs text-right">
        <Link
          to={`/sessions/${row.id}`}
          className="text-indigo-600 underline"
        >
          Details
        </Link>
      </td>
    </tr>
  )
}

interface LocationStatRowProps {
  loc: DashboardLocationStat
  currency: string
}

function LocationStatRow({ loc, currency }: LocationStatRowProps) {
  return (
    <li
      className="flex items-baseline justify-between border-b border-slate-200 py-1 last:border-b-0 dark:border-slate-700"
      data-testid={`top-location-${loc.id}`}
    >
      <Link
        to={`/locations/${loc.id}`}
        className="text-sm font-medium text-indigo-600 hover:underline"
      >
        {loc.name ?? <span className="italic text-slate-500">Unlabelled</span>}
      </Link>
      <div className="flex items-baseline gap-3 text-xs text-slate-500">
        <span>
          {loc.visit_count} {loc.visit_count === 1 ? 'visit' : 'visits'}
        </span>
        <span>{loc.total_kwh.toFixed(1)} kWh</span>
        <span>{formatCurrency(loc.total_cost_pence, currency)}</span>
      </div>
    </li>
  )
}

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const unit = useDistanceUnit()
  const currencyCode = useSetting<string>('currency') ?? 'GBP'
  const activeJobIds = useSyncStore((s) =>
    Object.keys(s.currentJobsByCarId).sort().join(','),
  )
  const prevActiveJobIds = useRef(activeJobIds)

  const reload = async () => {
    try {
      const data = await api.getDashboard()
      setSummary(data)
      setError(null)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to load dashboard',
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  // When any in-flight sync job clears, re-pull the dashboard so freshly
  // observed state (battery / range / charging power / location) shows up
  // without a manual refresh. SSE streams are owned by SyncStreamSubscriber.
  useEffect(() => {
    const prev = prevActiveJobIds.current
    prevActiveJobIds.current = activeJobIds
    if (prev && !activeJobIds) {
      void reload()
    }
  }, [activeJobIds])

  if (loading) {
    return (
      <main className="mx-auto max-w-7xl px-6 py-8">
        <p className="text-sm text-slate-500">Loading dashboard…</p>
      </main>
    )
  }

  if (error) {
    return (
      <main className="mx-auto max-w-7xl px-6 py-8">
        <div role="alert" className="text-sm text-red-600">
          {error}
        </div>
      </main>
    )
  }

  if (!summary) return null

  const distance = formatDistance(summary.lifetime_totals.distance_km)

  return (
    <main className="mx-auto max-w-7xl px-6 py-8" data-testid="dashboard-root">
      <h1 className="mb-6 text-2xl font-semibold">Dashboard</h1>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Panel 1 — current state per car */}
        <section data-testid="panel-cars">
          <h2 className="mb-3 text-lg font-semibold">Cars</h2>
          {summary.cars.length === 0 ? (
            <p className="text-sm text-slate-500">No cars yet.</p>
          ) : (
            <ul className="space-y-3">
              {summary.cars.map((car) => (
                <CarPanelCard key={car.id} car={car} />
              ))}
            </ul>
          )}
        </section>

        {/* Panel 3 — lifetime totals */}
        <section data-testid="panel-lifetime">
          <h2 className="mb-3 text-lg font-semibold">Lifetime</h2>
          <dl
            className="grid grid-cols-2 gap-3 rounded border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900"
            data-testid="lifetime-grid"
          >
            <div>
              <dt className="text-xs text-slate-500">Total kWh</dt>
              <dd className="text-2xl font-semibold" data-testid="lifetime-kwh">
                {summary.lifetime_totals.kwh.toFixed(1)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Total cost</dt>
              <dd className="text-2xl font-semibold" data-testid="lifetime-cost">
                {formatCurrency(summary.lifetime_totals.cost_pence, currencyCode)}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Distance</dt>
              <dd
                className="text-2xl font-semibold"
                data-testid="lifetime-distance"
              >
                {Math.round(distance.value)} {distance.unit}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Sessions</dt>
              <dd
                className="text-2xl font-semibold"
                data-testid="lifetime-count"
              >
                {summary.lifetime_totals.sessions_count}
              </dd>
            </div>
          </dl>
        </section>

        {/* Panel 2 — recent sessions */}
        <section className="lg:col-span-2" data-testid="panel-recent">
          <h2 className="mb-3 text-lg font-semibold">Recent sessions</h2>
          {summary.recent_sessions.length === 0 ? (
            <p className="text-sm text-slate-500">No sessions yet.</p>
          ) : (
            <div className="overflow-x-auto rounded border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
              <table className="w-full table-auto">
                <thead className="bg-slate-50 text-xs text-slate-500 dark:bg-slate-800">
                  <tr>
                    <th className="px-3 py-2 text-left">Date</th>
                    <th className="px-3 py-2 text-left">Car</th>
                    <th className="px-3 py-2 text-right">Energy</th>
                    <th className="px-3 py-2 text-right">Cost</th>
                    <th className="px-3 py-2 text-left">Location</th>
                    <th className="px-3 py-2 text-left">Source</th>
                    <th className="px-3 py-2 text-right" />
                  </tr>
                </thead>
                <tbody className="px-3">
                  {summary.recent_sessions.map((row) => (
                    <SessionRowDisplay
                      key={row.id}
                      row={row}
                      unit={unit}
                      currency={currencyCode}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* Panel 4 — top locations */}
        <section className="lg:col-span-2" data-testid="panel-locations">
          <h2 className="mb-3 text-lg font-semibold">Top locations</h2>
          {summary.top_locations.length === 0 ? (
            <p className="text-sm text-slate-500">No locations yet.</p>
          ) : (
            <ul className="rounded border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
              {summary.top_locations.map((loc) => (
                <LocationStatRow
                  key={loc.id}
                  loc={loc}
                  currency={currencyCode}
                />
              ))}
            </ul>
          )}
        </section>
      </div>
    </main>
  )
}
