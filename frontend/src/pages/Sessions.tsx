/**
 * Sessions list page (redesigned).
 *
 * A single flat, sortable table: Date · Location · Energy · Cost ·
 * Saved vs petrol · SoC · Rate · Type.
 * Filters: source (Tabs) + date range (DropdownMenu, incl. custom range).
 *
 * Phase 4 highlight behaviour preserved — rows in
 * `syncStore.recentlyImportedSessionIds` get `data-highlighted="true"`.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronUp } from 'lucide-react'
import {
  ApiError,
  api,
  type ChargingSessionPayload,
} from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pill, type PillTone } from '@/components/ui/Pill'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/cn'
import { useSyncStore } from '@/stores/syncStore'
import { formatCurrency } from '@/utils/currency'
import { useSetting } from '@/stores/settingsStore'

type SourceFilter = 'all' | 'manual' | 'synthesis' | 'cariad' | 'unconfirmed'

type DateRange =
  | 'this_month'
  | 'last_30'
  | 'last_90'
  | 'this_year'
  | 'all'
  | 'custom'

type SortField = 'date' | 'cost' | 'energy' | 'saved'
type SortDir = 'asc' | 'desc'

const DATE_LABEL: Record<DateRange, string> = {
  this_month: 'This month',
  last_30: 'Last 30 days',
  last_90: 'Last 90 days',
  this_year: 'This year',
  all: 'All time',
  custom: 'Custom range',
}

const SOURCE_TONE: Record<string, PillTone> = {
  manual: 'amber',
  synthesis: 'cyan',
  cariad: 'purple',
  unconfirmed: 'slate',
}

const SOURCE_LABEL: Record<string, string> = {
  manual: 'Manual',
  synthesis: 'Cupra',
  cariad: 'Cariad',
  unconfirmed: 'Unconfirmed',
}

const TYPE_LABEL: Record<string, string> = {
  ac: 'AC',
  dc: 'DC',
}

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

/** "27 May" from an ISO date (yyyy-mm-dd...). */
function formatDayMonth(iso: string): string {
  const day = Number(iso.slice(8, 10))
  const month = MONTHS[Number(iso.slice(5, 7)) - 1] ?? ''
  return `${day} ${month}`.trim()
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function thirtyDaysAgoIso(): string {
  return new Date(Date.now() - 30 * 86_400_000).toISOString().slice(0, 10)
}

function dateRangeBounds(range: DateRange): {
  date_from?: string
  date_to?: string
} {
  if (range === 'all' || range === 'custom') return {}
  const now = new Date()
  const today = now.toISOString().slice(0, 10)
  if (range === 'this_month') {
    const start = new Date(now.getFullYear(), now.getMonth(), 1)
      .toISOString()
      .slice(0, 10)
    return { date_from: start, date_to: today }
  }
  if (range === 'this_year') {
    const start = new Date(now.getFullYear(), 0, 1).toISOString().slice(0, 10)
    return { date_from: start, date_to: today }
  }
  const days = range === 'last_30' ? 30 : 90
  const start = new Date(now.getTime() - days * 86_400_000)
    .toISOString()
    .slice(0, 10)
  return { date_from: start, date_to: today }
}

interface SortHeaderProps {
  label: string
  field: SortField
  sort: SortField
  dir: SortDir
  onSort: (field: SortField) => void
  className?: string
}

function SortHeader({
  label,
  field,
  sort,
  dir,
  onSort,
  className,
}: SortHeaderProps) {
  const active = sort === field
  return (
    <th
      scope="col"
      className={cn(
        'px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400',
        className,
      )}
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

/** Render a savings value as arrow + colour, no +/- sign.
 *  saved > 0 → green ↓ (cheaper than petrol)
 *  saved < 0 → red ↑ (dearer than petrol)
 *  saved === null → —
 *  estimated → ~ prefix
 */
function SavingsCell({
  saved,
  estimated,
  currency,
  className,
}: {
  saved: number | null
  estimated: boolean
  currency: string
  className?: string
}) {
  if (saved === null) {
    return (
      <span className={cn('text-slate-400 dark:text-slate-500', className)}>
        —
      </span>
    )
  }
  const cheaper = saved > 0
  const magnitude = Math.abs(saved)
  const arrow = cheaper ? '↓' : '↑'
  const colourCls = cheaper
    ? 'text-emerald-600 dark:text-emerald-400'
    : 'text-rose-600 dark:text-rose-400'
  return (
    <span className={cn('tabular-nums', colourCls, className)}>
      {estimated ? '~' : ''}{arrow} {formatCurrency(magnitude, currency)}
    </span>
  )
}

interface SessionRowProps {
  session: ChargingSessionPayload
  highlighted: boolean
  currency: string
  /** First non-null breakeven across visible rows (for rate colouring). */
  breakeven: number | null
}

function SessionRow({ session, highlighted, currency, breakeven }: SessionRowProps) {
  const tone = SOURCE_TONE[session.source] ?? 'slate'
  const sourceLabel = SOURCE_LABEL[session.source] ?? session.source
  const locationName =
    session.location_name ??
    (session.location_id !== null
      ? `loc#${session.location_id}`
      : 'No location')
  const tariffValue = session.tariff_p_per_kwh
  const tariffText = tariffValue !== null ? `@${tariffValue.toFixed(0)}p` : null
  const typeLabel = TYPE_LABEL[session.charging_type] ?? null
  const estimated = session.comparison_basis === 'estimated'

  // Rate cell colour: green ≤ breakeven, red > breakeven, neutral when missing.
  const rateCls =
    tariffValue === null || breakeven === null
      ? 'text-slate-500 dark:text-slate-400'
      : tariffValue <= breakeven
        ? 'text-emerald-600 dark:text-emerald-400'
        : 'text-rose-600 dark:text-rose-400'

  return (
    <tr
      className={cn(
        'border-b border-slate-200 transition last:border-b-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50',
        highlighted &&
          'animate-pulse-soft bg-emerald-50/60 dark:bg-emerald-950/20',
      )}
      data-testid="session-row"
      data-highlighted={highlighted ? 'true' : 'false'}
    >
      <td className="px-3 py-2.5 text-sm tabular-nums text-slate-700 dark:text-slate-200">
        <Link to={`/sessions/${session.id}`} className="block">
          {formatDayMonth(session.date)}
        </Link>
      </td>
      <td className="px-3 py-2.5">
        <Link
          to={`/sessions/${session.id}`}
          className="flex items-center gap-2"
        >
          <span className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
            {locationName}
          </span>
          <Pill tone={tone} data-testid={`source-badge-${session.source}`}>
            {sourceLabel}
          </Pill>
        </Link>
      </td>
      <td className="px-3 py-2.5 text-sm tabular-nums text-slate-700 dark:text-slate-200">
        <Link to={`/sessions/${session.id}`} className="block">
          {session.kwh_added.toFixed(1)}
        </Link>
      </td>
      <td className="px-3 py-2.5">
        <Link to={`/sessions/${session.id}`} className="block">
          <GradientNumber size="sm" data-testid="session-cost">
            {formatCurrency(session.cost_pence, currency)}
          </GradientNumber>
        </Link>
      </td>
      <td
        data-testid="session-saved"
        className="px-3 py-2.5 text-sm"
      >
        <Link to={`/sessions/${session.id}`} className="block">
          <SavingsCell
            saved={session.saved_vs_petrol_p}
            estimated={estimated}
            currency={currency}
          />
        </Link>
      </td>
      <td className="hidden px-3 py-2.5 text-sm tabular-nums text-slate-500 dark:text-slate-400 md:table-cell">
        <Link to={`/sessions/${session.id}`} className="block">
          {session.start_soc}→{session.end_soc}%
        </Link>
      </td>
      <td className={cn('hidden px-3 py-2.5 text-sm tabular-nums md:table-cell', rateCls)}>
        <Link to={`/sessions/${session.id}`} className="block">
          {tariffText ?? ''}
        </Link>
      </td>
      <td className="hidden px-3 py-2.5 text-sm text-slate-500 dark:text-slate-400 md:table-cell">
        <Link to={`/sessions/${session.id}`} className="block">
          {typeLabel ?? ''}
        </Link>
      </td>
    </tr>
  )
}

export default function Sessions() {
  const [sessions, setSessions] = useState<ChargingSessionPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [dateRange, setDateRange] = useState<DateRange>('last_30')
  const [customFrom, setCustomFrom] = useState<string>(thirtyDaysAgoIso())
  const [customTo, setCustomTo] = useState<string>(todayIso())
  const [sort, setSort] = useState<SortField>('date')
  const [dir, setDir] = useState<SortDir>('desc')
  /** All-time count of un-triaged unconfirmed rows (source='unconfirmed'). */
  const [unconfirmedCount, setUnconfirmedCount] = useState<number | null>(null)
  const recentlyImported = useSyncStore((s) => s.recentlyImportedSessionIds)
  const currency = useSetting<string>('currency') ?? 'GBP'

  const isCustom = dateRange === 'custom'
  const invalidCustom = isCustom && customFrom > customTo

  /** Fetch the all-time unconfirmed count separately (no date bounds). */
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const count = await api.countUnconfirmedSessions()
        if (!cancelled) setUnconfirmedCount(count)
      } catch {
        // Non-fatal: badge simply doesn't appear.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (invalidCustom) return
    let cancelled = false
    void (async () => {
      try {
        setLoading(true)
        const params = new URLSearchParams()
        if (sourceFilter !== 'all') params.set('source', sourceFilter)
        if (isCustom) {
          if (customFrom) params.set('date_from', customFrom)
          if (customTo) params.set('date_to', customTo)
        } else {
          const bounds = dateRangeBounds(dateRange)
          if (bounds.date_from) params.set('date_from', bounds.date_from)
          if (bounds.date_to) params.set('date_to', bounds.date_to)
        }
        params.set('sort', sort)
        params.set('dir', dir)
        const qs = params.toString()
        const data = await api.getSessions(qs ? `?${qs}` : undefined)
        if (!cancelled) {
          setSessions(data)
          // If we are already viewing the unconfirmed filter, the badge count
          // is exactly the returned set length (no date bounds needed — the
          // unconfirmed list is always all-time for the badge).
          if (sourceFilter === 'unconfirmed') {
            setUnconfirmedCount(data.length)
          }
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError
              ? err.message
              : 'Failed to load sessions',
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [
    sourceFilter,
    dateRange,
    customFrom,
    customTo,
    sort,
    dir,
    isCustom,
    invalidCustom,
  ])

  function handleSort(field: SortField) {
    if (field === sort) {
      setDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSort(field)
      setDir('desc')
    }
  }

  const triggerLabel = isCustom
    ? `${formatDayMonth(customFrom)} – ${formatDayMonth(customTo)}`
    : DATE_LABEL[dateRange]

  const summary = useMemo(() => {
    const totalCost = sessions.reduce(
      (acc, s) => acc + (s.cost_pence ?? 0),
      0,
    )
    // Sum only rows that have a savings value (null rows don't contribute).
    const savingsRows = sessions.filter((s) => s.saved_vs_petrol_p !== null)
    const totalSaved = savingsRows.reduce(
      (acc, s) => acc + (s.saved_vs_petrol_p ?? 0),
      0,
    )
    const hasSavings = savingsRows.length > 0
    // First non-null breakeven across visible rows.
    const breakeven =
      sessions.find((s) => s.breakeven_p_per_kwh !== null)?.breakeven_p_per_kwh ??
      null
    return {
      count: sessions.length,
      totalCost,
      totalSaved,
      hasSavings,
      breakeven,
    }
  }, [sessions])

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <PageHeader
        title="Sessions"
        actions={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1.5">
                {triggerLabel}
                <ChevronDown className="h-3.5 w-3.5" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              {(Object.keys(DATE_LABEL) as DateRange[]).map((r) => (
                <DropdownMenuItem key={r} onSelect={() => setDateRange(r)}>
                  {DATE_LABEL[r]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2" data-testid="source-tabs">
        {(['all', 'manual', 'synthesis', 'cariad', 'unconfirmed'] as SourceFilter[]).map(
          (f) => (
            <button
              key={f}
              type="button"
              onClick={() => setSourceFilter(f)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition',
                sourceFilter === f
                  ? 'border-cyan-300 bg-cyan-500/15 text-cyan-700 dark:border-cyan-900 dark:text-cyan-300'
                  : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800',
              )}
            >
              {f === 'all'
                ? 'All'
                : f === 'synthesis'
                  ? 'Cupra'
                  : SOURCE_LABEL[f]}
              {f === 'unconfirmed' && unconfirmedCount !== null && unconfirmedCount > 0 && (
                <span
                  className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-500 px-1 text-[10px] font-bold text-white"
                  data-testid="unconfirmed-badge"
                  aria-label={`${unconfirmedCount} unconfirmed`}
                >
                  {unconfirmedCount}
                </span>
              )}
            </button>
          ),
        )}
      </div>

      {isCustom && (
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
            From
            <input
              type="date"
              data-testid="custom-from"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200"
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
            To
            <input
              type="date"
              data-testid="custom-to"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
              className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200"
            />
          </label>
          {invalidCustom && (
            <span role="alert" className="text-xs text-red-600">
              Start date must be on or before the end date.
            </span>
          )}
        </div>
      )}

      <p className="mb-3 text-sm tabular-nums text-slate-500 dark:text-slate-400">
        {summary.count} {summary.count === 1 ? 'session' : 'sessions'} ·{' '}
        {formatCurrency(summary.totalCost, currency)} ·{' '}
        {summary.hasSavings ? (
          <>
            <SavingsCell
              saved={summary.totalSaved}
              estimated={false}
              currency={currency}
              className="inline"
            />{' '}
            vs petrol
          </>
        ) : (
          '— saved'
        )}
      </p>

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && (
        <div role="alert" className="text-sm text-red-600">
          {error}
        </div>
      )}
      {!loading && sessions.length === 0 && (
        <EmptyState
          title="No sessions yet"
          body="Sessions matching the current filters will appear here."
        />
      )}

      {sessions.length > 0 && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-800">
                <SortHeader
                  label="Date"
                  field="date"
                  sort={sort}
                  dir={dir}
                  onSort={handleSort}
                />
                <th
                  scope="col"
                  className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400"
                >
                  Location
                </th>
                <SortHeader
                  label="kWh"
                  field="energy"
                  sort={sort}
                  dir={dir}
                  onSort={handleSort}
                />
                <SortHeader
                  label="Cost"
                  field="cost"
                  sort={sort}
                  dir={dir}
                  onSort={handleSort}
                />
                <SortHeader
                  label="Saved"
                  field="saved"
                  sort={sort}
                  dir={dir}
                  onSort={handleSort}
                />
                <th
                  scope="col"
                  className="hidden px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400 md:table-cell"
                >
                  SoC
                </th>
                <th
                  scope="col"
                  className="hidden px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400 md:table-cell"
                >
                  <span>Rate</span>
                  {summary.breakeven !== null && (
                    <span
                      className="ml-1 font-normal normal-case tracking-normal text-[10px] text-slate-400 dark:text-slate-500"
                      title={`Charge rate above which electricity costs more than petrol per mile`}
                    >
                      vs petrol break-even ~{Math.round(summary.breakeven)}p/kWh
                    </span>
                  )}
                </th>
                <th
                  scope="col"
                  className="hidden px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400 md:table-cell"
                >
                  Type
                </th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <SessionRow
                  key={session.id}
                  session={session}
                  highlighted={recentlyImported.includes(session.id)}
                  currency={currency}
                  breakeven={summary.breakeven}
                />
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}
