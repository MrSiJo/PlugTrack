/**
 * Sessions list page (redesigned).
 *
 * Two-line rows grouped by month with a per-month total header.
 * Filters: source (Tabs) + date range (DropdownMenu).
 *
 * Phase 4 highlight behaviour preserved — rows in
 * `syncStore.recentlyImportedSessionIds` get `data-highlighted="true"`.
 */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'
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
import {
  groupSessionsByMonth,
  type GroupableSession,
} from '@/lib/groupSessionsByMonth'
import { cn } from '@/lib/cn'
import { useSyncStore } from '@/stores/syncStore'
import { formatCurrency } from '@/utils/currency'
import { useSetting } from '@/stores/settingsStore'

type SourceFilter = 'all' | 'manual' | 'synthesis' | 'cariad'

type DateRange = 'this_month' | 'last_30' | 'last_90' | 'this_year' | 'all'

const DATE_LABEL: Record<DateRange, string> = {
  this_month: 'This month',
  last_30: 'Last 30 days',
  last_90: 'Last 90 days',
  this_year: 'This year',
  all: 'All time',
}

const SOURCE_TONE: Record<string, PillTone> = {
  manual: 'amber',
  synthesis: 'cyan',
  cariad: 'purple',
}

const SOURCE_LABEL: Record<string, string> = {
  manual: 'Manual',
  synthesis: 'Cupra',
  cariad: 'Cariad',
}

function dateRangeBounds(range: DateRange): {
  date_from?: string
  date_to?: string
} {
  if (range === 'all') return {}
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

interface SessionRowProps {
  session: ChargingSessionPayload
  highlighted: boolean
  currency: string
}

function SessionRow({ session, highlighted, currency }: SessionRowProps) {
  const tone = SOURCE_TONE[session.source] ?? 'slate'
  const label = SOURCE_LABEL[session.source] ?? session.source
  const day = session.date.slice(8, 10)
  const locationName =
    session.location_name ??
    (session.location_id !== null
      ? `loc#${session.location_id}`
      : 'No location')
  const tariff = session.tariff_p_per_kwh
    ? `@ ${session.tariff_p_per_kwh.toFixed(0)}p`
    : null
  return (
    <Link
      to={`/sessions/${session.id}`}
      className={cn(
        'flex items-center gap-3 border-b border-slate-200 px-3 py-3 transition last:border-b-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/50',
        highlighted &&
          'animate-pulse-soft bg-emerald-50/60 dark:bg-emerald-950/20',
      )}
      data-testid="session-row"
      data-highlighted={highlighted ? 'true' : 'false'}
    >
      <span className="w-9 text-base font-semibold tabular-nums text-slate-700 dark:text-slate-200">
        {day}
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
          {locationName}
        </p>
        <p className="truncate text-xs text-slate-500 dark:text-slate-400">
          {session.kwh_added.toFixed(1)} kWh
          {tariff && <span> {tariff}</span>}
        </p>
      </div>
      <div className="flex flex-col items-end gap-1">
        <GradientNumber size="sm" data-testid="session-cost">
          {formatCurrency(session.cost_pence, currency)}
        </GradientNumber>
        <Pill tone={tone} data-testid={`source-badge-${session.source}`}>
          {label}
        </Pill>
      </div>
    </Link>
  )
}

export default function Sessions() {
  const [sessions, setSessions] = useState<ChargingSessionPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [dateRange, setDateRange] = useState<DateRange>('last_90')
  const recentlyImported = useSyncStore((s) => s.recentlyImportedSessionIds)
  const currency = useSetting<string>('currency') ?? 'GBP'

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        setLoading(true)
        const params = new URLSearchParams()
        if (sourceFilter !== 'all') params.set('source', sourceFilter)
        const bounds = dateRangeBounds(dateRange)
        if (bounds.date_from) params.set('date_from', bounds.date_from)
        if (bounds.date_to) params.set('date_to', bounds.date_to)
        const qs = params.toString()
        const data = await api.getSessions(qs ? `?${qs}` : undefined)
        if (!cancelled) {
          setSessions(data)
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
  }, [sourceFilter, dateRange])

  const groups = useMemo(
    () =>
      groupSessionsByMonth(
        sessions as unknown as GroupableSession[] as never,
      ),
    [sessions],
  )

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <PageHeader
        title="Sessions"
        actions={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1.5">
                {DATE_LABEL[dateRange]}
                <ChevronDown className="h-3.5 w-3.5" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              {(Object.keys(DATE_LABEL) as DateRange[]).map((r) => (
                <DropdownMenuItem
                  key={r}
                  onSelect={() => setDateRange(r)}
                >
                  {DATE_LABEL[r]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2" data-testid="source-tabs">
        {(['all', 'manual', 'synthesis', 'cariad'] as SourceFilter[]).map(
          (f) => (
            <button
              key={f}
              type="button"
              onClick={() => setSourceFilter(f)}
              className={cn(
                'rounded-md border px-2.5 py-1 text-xs font-medium transition',
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
            </button>
          ),
        )}
      </div>

      {loading && <p className="text-sm text-slate-500">Loading…</p>}
      {error && (
        <div role="alert" className="text-sm text-red-600">
          {error}
        </div>
      )}
      {!loading && groups.length === 0 && (
        <EmptyState
          title="No sessions yet"
          body="Sessions matching the current filters will appear here."
        />
      )}

      <div className="space-y-6">
        {groups.map((group) => (
          <div key={group.key}>
            <div className="mb-2 flex items-baseline justify-between text-[11px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
              <span className="font-semibold">{group.label}</span>
              <span className="tabular-nums">
                {group.count}{' '}
                {group.count === 1 ? 'session' : 'sessions'} ·{' '}
                {formatCurrency(group.totalCostPence, currency)}
              </span>
            </div>
            <Card className="p-0">
              {(group.sessions as unknown as ChargingSessionPayload[]).map(
                (session) => (
                  <SessionRow
                    key={session.id}
                    session={session}
                    highlighted={recentlyImported.includes(session.id)}
                    currency={currency}
                  />
                ),
              )}
            </Card>
          </div>
        ))}
      </div>
    </div>
  )
}
