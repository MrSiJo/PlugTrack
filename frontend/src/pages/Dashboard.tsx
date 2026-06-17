/**
 * Dashboard — post-login landing page (redesigned).
 *
 * Layout (lg+):
 *   ┌─────────────────────────────┬────────────────────┐
 *   │ Hero car card(s)            │ SpendChart (30d)   │
 *   ├──────┬──────┬──────┬────────┴────────────────────┤
 *   │ kWh  │ Cost │ Sess │ Avg p/kWh                   │  StatTile strip
 *   ├──────┴──────┴──────┴─────────────────────────────┤
 *   │ Recent sessions table                            │
 *   ├──────────────────────────────────────────────────┤
 *   │ Top locations                                    │
 *   └──────────────────────────────────────────────────┘
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ApiError,
  api,
  type DashboardLocationStat,
  type DashboardSessionRow,
  type DashboardSummary,
  type SpendTrendDay,
} from '@/api/client'
import { HeroCarCard } from '@/components/dashboard/HeroCarCard'
import { SpendChart } from '@/components/dashboard/SpendChart'
import { Card } from '@/components/ui/Card'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pill } from '@/components/ui/Pill'
import { StatTile } from '@/components/ui/StatTile'
import {
  formatDistance,
  useSetting,
} from '@/stores/settingsStore'
import { useSyncStore } from '@/stores/syncStore'
import { formatCurrency } from '@/utils/currency'
import { kmToMi } from '@/utils/distance'

const SOURCE_TONE: Record<string, 'cyan' | 'amber' | 'purple' | 'green'> = {
  telegram: 'green',
  manual: 'amber',
  synthesis: 'cyan',
  import: 'purple',
}

const SOURCE_LABEL: Record<string, string> = {
  telegram: 'Telegram',
  manual: 'Manual',
  synthesis: 'Cupra',
  import: 'Import',
}

interface SessionRowDisplayProps {
  row: DashboardSessionRow
  currency: string
}

function SessionRowDisplay({ row, currency }: SessionRowDisplayProps) {
  const tone = SOURCE_TONE[row.source] ?? 'slate'
  const label = SOURCE_LABEL[row.source] ?? row.source
  const locationLabel =
    row.location_name ?? (row.location_id ? `loc#${row.location_id}` : '—')
  return (
    <tr
      className="border-b border-slate-200 last:border-b-0 dark:border-slate-700"
      data-testid={`recent-session-${row.id}`}
    >
      <td className="px-3 py-2 text-xs tabular-nums text-slate-500 dark:text-slate-400">
        {row.date}
      </td>
      <td className="px-3 py-2 text-xs">{row.car_label}</td>
      <td className="px-3 py-2 text-right text-xs tabular-nums">
        {row.kwh_added.toFixed(1)} kWh
      </td>
      <td className="px-3 py-2 text-right text-xs tabular-nums">
        <GradientNumber size="sm">
          {formatCurrency(row.cost_pence, currency)}
        </GradientNumber>
      </td>
      <td className="px-3 py-2 text-xs">
        {row.location_id !== null ? (
          <Link
            to={`/locations/${row.location_id}`}
            className="text-cyan-600 hover:underline dark:text-cyan-300"
          >
            {locationLabel}
          </Link>
        ) : (
          <span className="text-slate-500">—</span>
        )}
      </td>
      <td className="px-3 py-2 text-xs">
        <Pill tone={tone}>{label}</Pill>
      </td>
      <td className="px-3 py-2 text-right text-xs">
        <Link
          to={`/sessions/${row.id}`}
          className="text-cyan-600 hover:underline dark:text-cyan-300"
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
      className="flex items-baseline justify-between border-b border-slate-200 py-2 last:border-b-0 dark:border-slate-700"
      data-testid={`top-location-${loc.id}`}
    >
      <Link
        to={`/locations/${loc.id}`}
        className="text-sm font-medium text-cyan-600 hover:underline dark:text-cyan-300"
      >
        {loc.name ?? (
          <span className="italic text-slate-500">Unlabelled</span>
        )}
      </Link>
      <div className="flex items-baseline gap-3 text-xs text-slate-500 dark:text-slate-400">
        <span className="tabular-nums">
          {loc.charge_count} {loc.charge_count === 1 ? 'charge' : 'charges'}
        </span>
        <span className="tabular-nums">{loc.total_kwh.toFixed(1)} kWh</span>
        <GradientNumber size="sm">
          {formatCurrency(loc.total_cost_pence, currency)}
        </GradientNumber>
      </div>
    </li>
  )
}

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [trend, setTrend] = useState<SpendTrendDay[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const currencyCode = useSetting<string>('currency') ?? 'GBP'
  const activeJobIds = useSyncStore((s) =>
    Object.keys(s.currentJobsByCarId).sort().join(','),
  )
  const prevActiveJobIds = useRef(activeJobIds)

  const reload = async () => {
    try {
      const [summaryData, trendData] = await Promise.all([
        api.getDashboard(),
        api.getSpendTrend(30).catch(() => [] as SpendTrendDay[]),
      ])
      setSummary(summaryData)
      setTrend(trendData)
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
  const avgPerKwh =
    summary.lifetime_totals.kwh > 0
      ? summary.lifetime_totals.cost_pence /
        summary.lifetime_totals.kwh
      : null

  // Cost per mile arrives from the API in pence-per-mile. Convert to p/km
  // for km users (kmToMi divides by KM_PER_MILE, which is exactly p/mi → p/km).
  const formatCostPerDistance = (pencePerMile: number | null): string | null => {
    if (pencePerMile === null) return null
    const value =
      distance.unit === 'km' ? kmToMi(pencePerMile) : pencePerMile
    return `${value.toFixed(1)} p/${distance.unit}`
  }
  const costPerMileMain = formatCostPerDistance(
    summary.cost_per_mile.lifetime_pence,
  )
  const costPerMile30d = formatCostPerDistance(
    summary.cost_per_mile.rolling_30d_pence,
  )

  return (
    <main className="mx-auto max-w-7xl px-6 py-8" data-testid="dashboard-root">
      <PageHeader title="Dashboard" />

      {/* Hero strip — cars + spend chart */}
      <section
        className="grid gap-4 lg:grid-cols-2"
        data-testid="panel-hero"
      >
        <div className="flex flex-col gap-3" data-testid="panel-cars">
          {summary.cars.length === 0 ? (
            <Card className="text-sm text-slate-500">No cars yet.</Card>
          ) : (
            summary.cars.map((car) => <HeroCarCard key={car.id} car={car} />)
          )}
        </div>
        <SpendChart
          data={trend}
          currency={currencyCode}
          data-testid="panel-spend-chart"
        />
      </section>

      {/* KPI strip */}
      <section
        className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5"
        data-testid="panel-lifetime"
      >
        <StatTile
          label="Total kWh"
          value={summary.lifetime_totals.kwh.toFixed(1)}
          data-testid="lifetime-kwh"
        />
        <StatTile
          label="Total cost"
          value={
            <GradientNumber size="md" data-testid="lifetime-cost">
              {formatCurrency(
                summary.lifetime_totals.cost_pence,
                currencyCode,
              )}
            </GradientNumber>
          }
        />
        <StatTile
          label="Distance"
          value={`${Math.round(distance.value)} ${distance.unit}`}
          data-testid="lifetime-distance"
        />
        <StatTile
          label="Sessions"
          value={summary.lifetime_totals.sessions_count}
          sub={
            avgPerKwh !== null
              ? `avg ${avgPerKwh.toFixed(1)}p / kWh`
              : undefined
          }
          data-testid="lifetime-count"
        />
        <StatTile
          label={`Cost / ${distance.unit === 'km' ? 'km' : 'mile'}`}
          value={costPerMileMain ?? '—'}
          sub={costPerMile30d !== null ? `30d ${costPerMile30d}` : undefined}
          data-testid="lifetime-cost-per-mile"
        />
      </section>

      {/* Recent sessions */}
      <section className="mt-6" data-testid="panel-recent">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
          Recent sessions
        </h2>
        {summary.recent_sessions.length === 0 ? (
          <Card className="text-sm text-slate-500">No sessions yet.</Card>
        ) : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full table-auto">
              <thead className="bg-slate-50 text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
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
              <tbody>
                {summary.recent_sessions.map((row) => (
                  <SessionRowDisplay
                    key={row.id}
                    row={row}
                    currency={currencyCode}
                  />
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </section>

      {/* Top locations */}
      <section className="mt-6" data-testid="panel-locations">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
          Top locations
        </h2>
        {summary.top_locations.length === 0 ? (
          <Card className="text-sm text-slate-500">No locations yet.</Card>
        ) : (
          <Card>
            <ul>
              {summary.top_locations.map((loc) => (
                <LocationStatRow
                  key={loc.id}
                  loc={loc}
                  currency={currencyCode}
                />
              ))}
            </ul>
          </Card>
        )}
      </section>
    </main>
  )
}
