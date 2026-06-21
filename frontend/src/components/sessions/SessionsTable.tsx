import { Link } from 'react-router-dom'
import { ChevronDown, ChevronUp } from 'lucide-react'
import type { ChargingSessionPayload } from '@/api/client'
import { Card } from '@/components/ui/Card'
import { EfficiencyValue } from '@/components/EfficiencyValue'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { Pill, type PillTone } from '@/components/ui/Pill'
import { cn } from '@/lib/cn'
import { formatCurrency } from '@/utils/currency'

export type SortField = 'date' | 'cost' | 'energy' | 'saved'
export type SortDir = 'asc' | 'desc'

const SOURCE_TONE: Record<string, PillTone> = {
  telegram: 'green',
  manual: 'amber',
  synthesis: 'cyan',
  import: 'purple',
}

export const SOURCE_LABEL: Record<string, string> = {
  telegram: 'Telegram',
  manual: 'Manual',
  synthesis: 'Cupra',
  import: 'Import',
}

const TYPE_LABEL: Record<string, string> = { ac: 'AC', dc: 'DC' }

const MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

/** "27 May" from an ISO date (yyyy-mm-dd...). */
export function formatDayMonth(iso: string): string {
  const day = Number(iso.slice(8, 10))
  const month = MONTHS[Number(iso.slice(5, 7)) - 1] ?? ''
  return `${day} ${month}`.trim()
}

interface SortHeaderProps {
  label: string
  field: SortField
  sort: SortField
  dir: SortDir
  onSort: (field: SortField) => void
  className?: string
}

function SortHeader({ label, field, sort, dir, onSort, className }: SortHeaderProps) {
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

const PLAIN_TH =
  'px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400'

export function SavingsCell({
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
    return <span className={cn('text-slate-400 dark:text-slate-500', className)}>—</span>
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
  breakeven: number | null
}

function SessionRow({ session, highlighted, currency, breakeven }: SessionRowProps) {
  const tone = SOURCE_TONE[session.source] ?? 'slate'
  const sourceLabel = SOURCE_LABEL[session.source] ?? session.source
  const locationName =
    session.location_name ??
    (session.location_id !== null ? `loc#${session.location_id}` : 'No location')
  const tariffValue = session.tariff_p_per_kwh
  const tariffText = tariffValue !== null ? `@${tariffValue.toFixed(0)}p` : null
  const typeLabel = TYPE_LABEL[session.charging_type] ?? null
  const estimated = session.comparison_basis === 'estimated'
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
        highlighted && 'animate-pulse-soft bg-emerald-50/60 dark:bg-emerald-950/20',
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
        <Link to={`/sessions/${session.id}`} className="flex items-center gap-2">
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
      <td data-testid="session-saved" className="px-3 py-2.5 text-sm">
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
      <td className="hidden px-3 py-2.5 text-sm text-slate-700 dark:text-slate-200 md:table-cell" data-testid="session-efficiency">
        <Link to={`/sessions/${session.id}`} className="block">
          <EfficiencyValue miPerKwh={session.efficiency_mi_per_kwh} primaryOnly />
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

export interface SessionsTableSortControls {
  sort: SortField
  dir: SortDir
  onSort: (field: SortField) => void
}

export interface SessionsTableProps {
  sessions: ChargingSessionPayload[]
  currency: string
  breakeven?: number | null
  highlightedIds?: number[]
  sortControls?: SessionsTableSortControls
}

export function SessionsTable({
  sessions,
  currency,
  breakeven = null,
  highlightedIds = [],
  sortControls,
}: SessionsTableProps) {
  const sortable = (label: string, field: SortField) =>
    sortControls ? (
      <SortHeader
        label={label}
        field={field}
        sort={sortControls.sort}
        dir={sortControls.dir}
        onSort={sortControls.onSort}
      />
    ) : (
      <th scope="col" className={PLAIN_TH}>
        {label}
      </th>
    )

  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-slate-200 dark:border-slate-800">
            {sortable('Date', 'date')}
            <th scope="col" className={PLAIN_TH}>
              Location
            </th>
            {sortable('kWh', 'energy')}
            {sortable('Cost', 'cost')}
            {sortable('Saved', 'saved')}
            <th scope="col" className={cn(PLAIN_TH, 'hidden md:table-cell')}>
              SoC
            </th>
            <th scope="col" className={cn(PLAIN_TH, 'hidden md:table-cell')}>
              Efficiency
            </th>
            <th scope="col" className={cn(PLAIN_TH, 'hidden md:table-cell')}>
              <span>Rate</span>
              {breakeven !== null && (
                <span
                  className="ml-1 font-normal normal-case tracking-normal text-[10px] text-slate-400 dark:text-slate-500"
                  title="Charge rate above which electricity costs more than petrol per mile"
                >
                  vs petrol break-even ~{Math.round(breakeven)}p/kWh
                </span>
              )}
            </th>
            <th scope="col" className={cn(PLAIN_TH, 'hidden md:table-cell')}>
              Type
            </th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((session) => (
            <SessionRow
              key={session.id}
              session={session}
              highlighted={highlightedIds.includes(session.id)}
              currency={currency}
              breakeven={breakeven}
            />
          ))}
        </tbody>
      </table>
    </Card>
  )
}
