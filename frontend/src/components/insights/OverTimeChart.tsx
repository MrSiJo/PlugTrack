import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatCurrency } from '@/utils/currency'
import type { InsightsOverTimePoint } from '@/api/client'

export interface OverTimeChartProps {
  data: InsightsOverTimePoint[]
  granularity: 'daily' | 'weekly' | 'monthly'
  currency: string
  className?: string
  'data-testid'?: string
}

interface TooltipProps {
  active?: boolean
  payload?: { payload?: InsightsOverTimePoint }[]
  currency: string
}

function ChartTooltip({ active, payload, currency }: TooltipProps) {
  const point = payload?.[0]?.payload
  if (!active || !point) return null
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <p className="font-medium text-slate-900 dark:text-slate-100">{point.period}</p>
      <p className="tabular-nums text-cyan-600 dark:text-cyan-300">
        {formatCurrency(point.spend_pence, currency)}
      </p>
      <p className="tabular-nums text-emerald-600 dark:text-emerald-300">
        {point.kwh.toFixed(1)} kWh · {point.sessions} sessions
      </p>
    </div>
  )
}

export function OverTimeChart({
  data,
  granularity,
  currency,
  className,
  'data-testid': testId,
}: OverTimeChartProps) {
  const totalSpend = data.reduce((a, d) => a + d.spend_pence, 0)
  const totalKwh = data.reduce((a, d) => a + d.kwh, 0)

  if (data.length === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No data for this range.
      </p>
    )
  }

  return (
    <div className={className} data-testid={testId}>
      <div className="mb-3 flex items-end justify-between gap-6">
        <div className="flex gap-6">
          <div>
            <p className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">Spend</p>
            <p className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100">
              {formatCurrency(totalSpend, currency)}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">Energy</p>
            <p className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100">
              {totalKwh.toFixed(1)} kWh
            </p>
          </div>
        </div>
        <span
          title="Bucket size adapts to the selected range"
          className="rounded-full border border-slate-200 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-500 dark:border-slate-700 dark:text-slate-400"
        >
          {granularity}
        </span>
      </div>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="ot-spend" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.95} />
                <stop offset="100%" stopColor="#10b981" stopOpacity={0.85} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor"
              className="text-slate-200 dark:text-slate-800" />
            <XAxis dataKey="period" tick={{ fontSize: 10 }} stroke="currentColor"
              className="text-slate-500 dark:text-slate-400" interval="preserveStartEnd" minTickGap={20} />
            <YAxis yAxisId="spend" tickFormatter={(v: number) => (v === 0 ? '0' : `${(v / 100).toFixed(0)}`)}
              tick={{ fontSize: 10 }} stroke="currentColor" className="text-slate-500 dark:text-slate-400" width={28} />
            <YAxis yAxisId="kwh" orientation="right" tick={{ fontSize: 10 }} stroke="currentColor"
              className="text-slate-500 dark:text-slate-400" width={28} />
            <Tooltip content={<ChartTooltip currency={currency} />} cursor={{ fill: 'rgba(34,211,238,0.05)' }} />
            <Bar yAxisId="spend" dataKey="spend_pence" fill="url(#ot-spend)" radius={[3, 3, 0, 0]} />
            <Line yAxisId="kwh" type="monotone" dataKey="kwh" stroke="#a855f7" strokeWidth={2} dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
