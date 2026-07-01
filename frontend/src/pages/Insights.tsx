/**
 * Insights page (analytics home) — v1: by-location spend breakdown.
 *
 * Date-range control (all-time default + Last 30/90 + custom) re-queries
 * GET /api/insights/by-location. A horizontal spend-by-location bar chart
 * (recharts, SpendChart styling) tops a sortable breakdown table. Labelled
 * rows link to /locations/:id; the "Unassigned" row is non-clickable.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronDown, ChevronUp } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  ApiError,
  api,
  type CarPayload,
  type InsightsByLocationResponse,
  type InsightsLocationRow,
  type InsightsOverviewResponse,
} from '@/api/client'
import CarPicker from '@/components/cars/CarPicker'
import { OverTimeChart } from '@/components/insights/OverTimeChart'
import { HomePublicSplit } from '@/components/insights/HomePublicSplit'
import { NetworkBreakdown } from '@/components/insights/NetworkBreakdown'
import { EfficiencyChart } from '@/components/insights/EfficiencyChart'
import { SeasonalEfficiencyChart } from '@/components/insights/SeasonalEfficiencyChart'
import { CapacityTrendChart } from '@/components/insights/CapacityTrendChart'
import { BatteryHealthCard } from '@/components/insights/BatteryHealthCard'
import { MileageAllowance } from '@/components/insights/MileageAllowance'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { PageHeader } from '@/components/ui/PageHeader'
import { cn } from '@/lib/cn'
import { useSetting } from '@/stores/settingsStore'
import { formatCurrency } from '@/utils/currency'

type RangeKey = 'all' | 'last_30' | 'last_90' | 'custom'

const RANGE_LABEL: Record<RangeKey, string> = {
  all: 'All time',
  last_30: 'Last 30 days',
  last_90: 'Last 90 days',
  custom: 'Custom range',
}

/** Shared card-label treatment for the analytics modules (matches the
 *  "Spend by location" eyebrow), kept as a heading for screen readers. */
const MODULE_EYEBROW =
  'mb-3 text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400'

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function daysAgoIso(days: number): string {
  return new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10)
}

function rangeBounds(
  range: RangeKey,
  customFrom: string,
  customTo: string,
): { from?: string; to?: string } {
  if (range === 'all') return {}
  if (range === 'custom') return { from: customFrom, to: customTo }
  const days = range === 'last_30' ? 30 : 90
  return { from: daysAgoIso(days), to: todayIso() }
}

type SortField = 'name' | 'spend_pence' | 'kwh' | 'sessions' | 'avg_p_per_kwh' | 'pct_of_spend' | 'last_at'
type SortDir = 'asc' | 'desc'

function rowLabel(row: InsightsLocationRow): string {
  return row.location_id === null ? 'Unassigned' : row.name ?? `Location #${row.location_id}`
}

export default function Insights() {
  const currency = useSetting<string>('currency') ?? 'GBP'
  const [searchParams] = useSearchParams()
  const [data, setData] = useState<InsightsByLocationResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [range, setRange] = useState<RangeKey>('all')
  const [customFrom, setCustomFrom] = useState<string>(daysAgoIso(30))
  const [customTo, setCustomTo] = useState<string>(todayIso())
  const [sort, setSort] = useState<SortField>('spend_pence')
  const [dir, setDir] = useState<SortDir>('desc')
  const [overview, setOverview] = useState<InsightsOverviewResponse | null>(null)
  const [cars, setCars] = useState<CarPayload[]>([])
  const [selectedCarId, setSelectedCarId] = useState<number | null>(() => {
    const carParam = searchParams.get('car')
    return carParam ? Number(carParam) : null
  })

  const isCustom = range === 'custom'
  const invalidCustom = isCustom && customFrom > customTo

  useEffect(() => {
    if (invalidCustom) return
    let cancelled = false
    void (async () => {
      try {
        setLoading(true)
        const { from, to } = rangeBounds(range, customFrom, customTo)
        const [byLocation, ov] = await Promise.all([
          api.getInsightsByLocation(from, to, selectedCarId ?? undefined),
          api.getInsightsOverview(from, to, selectedCarId ?? undefined),
        ])
        if (!cancelled) {
          setData(byLocation)
          setOverview(ov)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Failed to load insights')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [range, customFrom, customTo, invalidCustom, selectedCarId])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const list = await api.getCars()
        if (cancelled) return
        setCars(list)
      } catch {
        /* mileage module simply won't render without cars */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // For mileage module: if no car selected, default to first active car
  const mileageCarId = selectedCarId ?? cars.find((c) => c.active)?.id ?? null

  function handleSort(field: SortField) {
    if (field === sort) {
      setDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(field)
      setDir(field === 'name' ? 'asc' : 'desc')
    }
  }

  const rows = useMemo(() => {
    const list = [...(data?.rows ?? [])]
    list.sort((a, b) => {
      let av: number | string
      let bv: number | string
      if (sort === 'name') {
        av = rowLabel(a).toLowerCase()
        bv = rowLabel(b).toLowerCase()
      } else if (sort === 'last_at') {
        av = a.last_at ?? ''
        bv = b.last_at ?? ''
      } else if (sort === 'avg_p_per_kwh') {
        av = a.avg_p_per_kwh ?? -1
        bv = b.avg_p_per_kwh ?? -1
      } else {
        av = a[sort]
        bv = b[sort]
      }
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return dir === 'asc' ? cmp : -cmp
    })
    return list
  }, [data, sort, dir])

  const chartData = useMemo(
    () =>
      [...(data?.rows ?? [])]
        .filter((r) => r.spend_pence > 0)
        .sort((a, b) => b.spend_pence - a.spend_pence)
        .slice(0, 10)
        .map((r) => ({
          label: rowLabel(r),
          spend_pence: r.spend_pence,
          isUnassigned: r.location_id === null,
        })),
    [data],
  )

  const triggerLabel = isCustom
    ? `${customFrom} – ${customTo}`
    : RANGE_LABEL[range]

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <PageHeader
        title="Insights"
        subtitle="Where your charging spend goes. Click a location to drill in."
        actions={
          <div className="flex flex-wrap items-center gap-2" data-testid="insights-range">
            {cars.length > 0 && (
              <CarPicker
                value={selectedCarId}
                onChange={setSelectedCarId}
                cars={cars}
                includeArchived
                allowAll
                data-testid="insights-car-picker"
              />
            )}
            {(Object.keys(RANGE_LABEL) as RangeKey[]).map((r) => (
              <button
                key={r}
                type="button"
                data-testid={`insights-range-${r}`}
                onClick={() => setRange(r)}
                className={cn(
                  'rounded-md border px-2.5 py-1 text-xs font-medium transition',
                  range === r
                    ? 'border-cyan-300 bg-cyan-500/15 text-cyan-700 dark:border-cyan-900 dark:text-cyan-300'
                    : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800',
                )}
              >
                {RANGE_LABEL[r]}
              </button>
            ))}
          </div>
        }
      />

      {isCustom && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
            From
            <input
              type="date"
              data-testid="insights-custom-from"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs dark:border-slate-800 dark:bg-slate-900"
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
            To
            <input
              type="date"
              data-testid="insights-custom-to"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs dark:border-slate-800 dark:bg-slate-900"
            />
          </label>
          {invalidCustom && (
            <span role="alert" className="text-xs text-red-600">
              Start date must be on or before the end date.
            </span>
          )}
        </div>
      )}

      <p className="mb-3 text-sm text-slate-500 dark:text-slate-400" data-testid="insights-range-active">
        {triggerLabel}
        {data && (
          <>
            {' · '}
            <GradientNumber size="sm" className="mr-1">
              {formatCurrency(data.totals.spend_pence, currency)}
            </GradientNumber>
            across {data.totals.sessions}{' '}
            {data.totals.sessions === 1 ? 'session' : 'sessions'}
          </>
        )}
      </p>

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && (
        <div role="alert" className="text-sm text-red-600">
          {error}
        </div>
      )}

      {!loading && !error && rows.length === 0 && (
        <EmptyState
          title="No charging data yet"
          body="Once you log charges, your spend by location appears here."
        />
      )}

      {!loading && !error && chartData.length > 0 && (
        <Card className="mb-6">
          <p className="mb-3 text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
            Spend by location
          </p>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ top: 4, right: 12, left: 8, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="insights-gradient" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.95} />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0.85} />
                  </linearGradient>
                </defs>
                <CartesianGrid
                  strokeDasharray="3 3"
                  horizontal={false}
                  stroke="currentColor"
                  className="text-slate-200 dark:text-slate-800"
                />
                <XAxis
                  type="number"
                  tickFormatter={(v: number) => (v === 0 ? '0' : `${(v / 100).toFixed(0)}`)}
                  tick={{ fontSize: 10 }}
                  stroke="currentColor"
                  className="text-slate-500 dark:text-slate-400"
                />
                <YAxis
                  type="category"
                  dataKey="label"
                  tick={{ fontSize: 11 }}
                  width={110}
                  stroke="currentColor"
                  className="text-slate-500 dark:text-slate-400"
                />
                <Tooltip
                  cursor={{ fill: 'rgba(34,211,238,0.05)' }}
                  content={<ChartTooltip currency={currency} />}
                />
                <Bar dataKey="spend_pence" fill="url(#insights-gradient)" radius={[0, 3, 3, 0]}>
                  {chartData.map((entry) => (
                    <Cell key={entry.label} fillOpacity={entry.isUnassigned ? 0.45 : 1} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {!loading && !error && rows.length > 0 && (
        <Card className="mb-6 overflow-x-auto p-0">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800">
                <BreakdownHeader label="Location" field="name" sort={sort} dir={dir} onSort={handleSort} />
                <BreakdownHeader label="Spend" field="spend_pence" sort={sort} dir={dir} onSort={handleSort} />
                <BreakdownHeader label="kWh" field="kwh" sort={sort} dir={dir} onSort={handleSort} />
                <BreakdownHeader label="Sessions" field="sessions" sort={sort} dir={dir} onSort={handleSort} />
                <BreakdownHeader label="Avg p/kWh" field="avg_p_per_kwh" sort={sort} dir={dir} onSort={handleSort} />
                <BreakdownHeader label="% spend" field="pct_of_spend" sort={sort} dir={dir} onSort={handleSort} />
                <BreakdownHeader label="Last visited" field="last_at" sort={sort} dir={dir} onSort={handleSort} />
              </tr>
            </thead>
            <tbody data-testid="insights-table-body">
              {rows.map((row) => {
                const label = rowLabel(row)
                const cells = (
                  <>
                    <td className="px-3 py-2.5 text-sm tabular-nums text-slate-700 dark:text-slate-200">
                      {formatCurrency(row.spend_pence, currency)}
                    </td>
                    <td className="px-3 py-2.5 text-sm tabular-nums text-slate-700 dark:text-slate-200">
                      {row.kwh.toFixed(1)}
                    </td>
                    <td className="px-3 py-2.5 text-sm tabular-nums text-slate-700 dark:text-slate-200">
                      {row.sessions}
                    </td>
                    <td className="px-3 py-2.5 text-sm tabular-nums text-slate-500 dark:text-slate-400">
                      {row.avg_p_per_kwh === null ? '—' : `${row.avg_p_per_kwh.toFixed(1)}p`}
                    </td>
                    <td className="px-3 py-2.5 text-sm tabular-nums text-slate-500 dark:text-slate-400">
                      {row.pct_of_spend.toFixed(1)}%
                    </td>
                    <td className="px-3 py-2.5 text-sm text-slate-500 dark:text-slate-400">
                      {row.last_at ?? '—'}
                    </td>
                  </>
                )
                return (
                  <tr
                    key={row.location_id ?? 'unassigned'}
                    data-testid="insights-row"
                    className="border-b border-slate-200 last:border-b-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50"
                  >
                    <td className="px-3 py-2.5 text-sm font-medium text-slate-900 dark:text-slate-100">
                      {row.location_id === null ? (
                        <span className="text-slate-500 dark:text-slate-400">{label}</span>
                      ) : (
                        <Link to={`/locations/${row.location_id}`} className="hover:underline">
                          {label}
                        </Link>
                      )}
                    </td>
                    {cells}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </Card>
      )}

      {!loading && !error && overview && (
        <>
          <Card className="mb-6">
            <h2 className={MODULE_EYEBROW}>Spend &amp; energy over time</h2>
            <OverTimeChart
              data={overview.over_time}
              granularity={overview.granularity}
              currency={currency}
            />
          </Card>

          <div className="mb-6 grid gap-6 lg:grid-cols-2">
            <Card>
              <h2 className={MODULE_EYEBROW}>Home vs public</h2>
              <HomePublicSplit split={overview.split} currency={currency} />
            </Card>
            <Card>
              <h2 className={MODULE_EYEBROW}>Network breakdown</h2>
              <NetworkBreakdown rows={overview.by_network} currency={currency} />
            </Card>
          </div>

          <Card className="mb-6">
            <h2 className={MODULE_EYEBROW}>Efficiency &amp; cost per mile</h2>
            <EfficiencyChart data={overview.efficiency} />
          </Card>

          {overview.seasonal_efficiency && overview.seasonal_efficiency.length > 0 && (
            <Card className="mb-6">
              <h2 className={MODULE_EYEBROW}>Seasonal efficiency &amp; range</h2>
              <SeasonalEfficiencyChart data={overview.seasonal_efficiency} />
              {overview.seasonal_delta != null && (
                <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                  Seasonal swing:{' '}
                  <span className="font-medium text-slate-700 dark:text-slate-200">
                    {overview.seasonal_delta.pct.toFixed(1)}%
                    {' '}({overview.seasonal_delta.abs_mi_per_kwh.toFixed(2)} mi/kWh)
                  </span>{' '}
                  between best ({overview.seasonal_delta.best.period}) and worst ({overview.seasonal_delta.worst.period}) month.
                </p>
              )}
            </Card>
          )}

          {overview.capacity_trend && overview.capacity_trend.length > 0 && (
            <Card className="mb-6">
              <h2 className={MODULE_EYEBROW}>Estimated battery health</h2>
              <BatteryHealthCard data={overview.battery_health} className="mb-4" />
              <CapacityTrendChart data={overview.capacity_trend} />
            </Card>
          )}
        </>
      )}

      {!loading && !error && (
        <Card className="mb-6">
          <div className="mb-3 flex items-center justify-between">
            <h2 className={cn(MODULE_EYEBROW, 'mb-0')}>Mileage allowance</h2>
          </div>
          {mileageCarId != null && <MileageAllowance carId={mileageCarId} />}
        </Card>
      )}
    </div>
  )
}

interface ChartTooltipProps {
  active?: boolean
  payload?: { payload?: { label: string; spend_pence: number } }[]
  currency: string
}

/** Dark-mode-aware chart tooltip (recharts' default is an unreadable white
 *  box in dark theme). Mirrors the dashboard SpendChart tooltip. */
function ChartTooltip({ active, payload, currency }: ChartTooltipProps) {
  const first = payload?.[0]
  if (!active || !first?.payload) return null
  const entry = first.payload
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <p className="font-medium text-slate-900 dark:text-slate-100">{entry.label}</p>
      <p className="tabular-nums text-cyan-600 dark:text-cyan-300">
        {formatCurrency(entry.spend_pence, currency)}
      </p>
    </div>
  )
}

interface BreakdownHeaderProps {
  label: string
  field: SortField
  sort: SortField
  dir: SortDir
  onSort: (f: SortField) => void
}

function BreakdownHeader({ label, field, sort, dir, onSort }: BreakdownHeaderProps) {
  const active = sort === field
  return (
    <th
      scope="col"
      className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400"
    >
      <button
        type="button"
        onClick={() => onSort(field)}
        aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
        className="inline-flex items-center gap-1 transition hover:text-slate-700 dark:hover:text-slate-200"
      >
        {label}
        {active &&
          (dir === 'asc' ? (
            <ChevronUp className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" aria-hidden />
          ))}
      </button>
    </th>
  )
}
