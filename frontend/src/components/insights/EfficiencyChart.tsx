import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { InsightsEfficiencyPoint } from '@/api/client'
import { EfficiencyValue } from '@/components/EfficiencyValue'

export interface EfficiencyChartProps {
  data: InsightsEfficiencyPoint[]
  className?: string
  'data-testid'?: string
}

interface TooltipProps {
  active?: boolean
  payload?: { payload?: InsightsEfficiencyPoint }[]
}

function EffTooltip({ active, payload }: TooltipProps) {
  const p = payload?.[0]?.payload
  if (!active || !p) return null
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <p className="font-medium text-slate-900 dark:text-slate-100">{p.period}</p>
      <p className="text-emerald-600 dark:text-emerald-300">
        <EfficiencyValue miPerKwh={p.observed_mi_per_kwh} />
      </p>
      <p className="text-emerald-500/80 dark:text-emerald-400/70">
        <span className="text-[10px] uppercase tracking-wide">rolling </span>
        <EfficiencyValue miPerKwh={p.rolling_mi_per_kwh} primaryOnly />
      </p>
      <p className="tabular-nums text-amber-600 dark:text-amber-300">
        {p.cost_per_mile_p == null ? '—' : `${p.cost_per_mile_p.toFixed(1)} p/mile`}
      </p>
    </div>
  )
}

const LEGEND: { swatch: string; label: string }[] = [
  { swatch: 'bg-emerald-400', label: 'mi/kWh' },
  { swatch: 'border border-dashed border-emerald-400', label: 'rolling lifetime' },
  { swatch: 'bg-amber-400', label: 'cost/mile' },
]

export function EfficiencyChart({ data, className, 'data-testid': testId }: EfficiencyChartProps) {
  const hasData = data.some((d) => d.observed_mi_per_kwh != null || d.cost_per_mile_p != null)
  if (!hasData) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No odometer data for this range — efficiency needs odometer readings to compute.
      </p>
    )
  }

  // Headline: the latest rolling-lifetime value in range (most recent non-null).
  const rolling =
    [...data].reverse().find((d) => d.rolling_mi_per_kwh != null)?.rolling_mi_per_kwh ?? null

  return (
    <div className={className} data-testid={testId}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        {rolling != null && (
          <div data-testid="efficiency-rolling-headline">
            <p className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">
              Rolling lifetime
            </p>
            <EfficiencyValue
              miPerKwh={rolling}
              className="text-lg font-semibold text-slate-900 dark:text-slate-100"
            />
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-slate-500 dark:text-slate-400">
          {LEGEND.map((l) => (
            <span key={l.label} className="flex items-center gap-1">
              <span className={`inline-block h-2 w-4 rounded-sm ${l.swatch}`} />
              {l.label}
            </span>
          ))}
        </div>
      </div>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor"
              className="text-slate-200 dark:text-slate-800" />
            <XAxis dataKey="period" tick={{ fontSize: 10 }} stroke="currentColor"
              className="text-slate-500 dark:text-slate-400" interval="preserveStartEnd" minTickGap={20} />
            <YAxis yAxisId="eff" tick={{ fontSize: 10 }} stroke="currentColor"
              className="text-slate-500 dark:text-slate-400" width={32} />
            <YAxis yAxisId="cpm" orientation="right" tick={{ fontSize: 10 }} stroke="currentColor"
              className="text-slate-500 dark:text-slate-400" width={32} />
            <Tooltip content={<EffTooltip />} />
            <Line yAxisId="eff" type="monotone" dataKey="observed_mi_per_kwh" stroke="#10b981"
              strokeWidth={2} dot={false} connectNulls={false} />
            <Line yAxisId="eff" type="monotone" dataKey="rolling_mi_per_kwh" stroke="#10b981"
              strokeWidth={1.5} strokeDasharray="5 3" dot={false} connectNulls />
            <Line yAxisId="cpm" type="monotone" dataKey="cost_per_mile_p" stroke="#f59e0b"
              strokeWidth={2} dot={false} connectNulls={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
