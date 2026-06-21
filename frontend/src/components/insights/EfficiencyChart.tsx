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
      <p className="tabular-nums text-amber-600 dark:text-amber-300">
        {p.cost_per_mile_p == null ? '—' : `${p.cost_per_mile_p.toFixed(1)} p/mile`}
      </p>
    </div>
  )
}

export function EfficiencyChart({ data, className, 'data-testid': testId }: EfficiencyChartProps) {
  const hasData = data.some((d) => d.observed_mi_per_kwh != null || d.cost_per_mile_p != null)
  if (!hasData) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No odometer data for this range — efficiency needs odometer readings to compute.
      </p>
    )
  }
  return (
    <div className={`h-56 ${className ?? ''}`} data-testid={testId}>
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
          <Line yAxisId="cpm" type="monotone" dataKey="cost_per_mile_p" stroke="#f59e0b"
            strokeWidth={2} dot={false} connectNulls={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
