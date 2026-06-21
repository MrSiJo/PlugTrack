import {
  CartesianGrid,
  Line,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { SeasonalEfficiencyPoint } from '@/api/client'
import { formatDistance } from '@/stores/settingsStore'
import { EfficiencyValue } from '@/components/EfficiencyValue'

export interface SeasonalEfficiencyChartProps {
  data: SeasonalEfficiencyPoint[]
  className?: string
  'data-testid'?: string
}

interface TooltipProps {
  active?: boolean
  payload?: { payload?: SeasonalEfficiencyPoint; name?: string; value?: number | null }[]
}

export function ChartTooltip({ active, payload }: TooltipProps) {
  const point = payload?.[0]?.payload
  if (!active || !point) return null
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <p className="font-medium text-slate-900 dark:text-slate-100">
        {point.period}
        {point.low_confidence && (
          <span className="ml-1.5 text-[9px] uppercase tracking-wide text-amber-500">
            low confidence
          </span>
        )}
      </p>
      <p className="text-emerald-600 dark:text-emerald-300">
        <EfficiencyValue miPerKwh={point.mi_per_kwh} />
      </p>
      <p className="tabular-nums text-sky-600 dark:text-sky-300">
        Range: {point.derived_range_km != null
          ? (() => {
              const { value, unit } = formatDistance(point.derived_range_km)
              return `${Math.round(value)} ${unit}`
            })()
          : '—'}
      </p>
    </div>
  )
}

/** Derived range axis label uses the user's distance unit. */
function rangeAxisLabel(): string {
  // Call formatDistance with a dummy value to read the unit; value is irrelevant.
  const { unit } = formatDistance(0)
  return `Range (${unit})`
}

export function SeasonalEfficiencyChart({
  data,
  className,
  'data-testid': testId,
}: SeasonalEfficiencyChartProps) {
  const hasData = data.length > 0 && data.some((d) => d.mi_per_kwh != null)

  if (!hasData) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No trend data yet.
      </p>
    )
  }

  const rangeLabel = rangeAxisLabel()

  // Enrich data with a converted range value for the right axis.
  const chartData = data.map((d) => ({
    ...d,
    derived_range_display:
      d.derived_range_km != null ? formatDistance(d.derived_range_km).value : null,
  }))

  return (
    <div className={className} data-testid={testId}>
      <div className="mb-2 flex items-center gap-4 text-[10px] text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 rounded-sm bg-emerald-400" />
          mi/kWh
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 rounded-sm border border-dashed border-sky-400" />
          {rangeLabel}
        </span>
      </div>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid
              strokeDasharray="3 3"
              vertical={false}
              stroke="currentColor"
              className="text-slate-200 dark:text-slate-800"
            />
            <XAxis
              dataKey="period"
              tick={{ fontSize: 10 }}
              stroke="currentColor"
              className="text-slate-500 dark:text-slate-400"
              interval="preserveStartEnd"
              minTickGap={20}
            />
            <YAxis
              yAxisId="eff"
              tickFormatter={(v: number) => v.toFixed(1)}
              tick={{ fontSize: 10 }}
              stroke="currentColor"
              className="text-slate-500 dark:text-slate-400"
              width={32}
              label={{
                value: 'mi/kWh',
                angle: -90,
                position: 'insideLeft',
                offset: 8,
                style: { fontSize: 9, fill: 'currentColor' },
              }}
            />
            <YAxis
              yAxisId="range"
              orientation="right"
              tickFormatter={(v: number) => v.toFixed(0)}
              tick={{ fontSize: 10 }}
              stroke="currentColor"
              className="text-slate-500 dark:text-slate-400"
              width={40}
              label={{
                value: rangeLabel,
                angle: 90,
                position: 'insideRight',
                offset: 8,
                style: { fontSize: 9, fill: 'currentColor' },
              }}
            />
            <Tooltip content={<ChartTooltip />} />
            <Line
              yAxisId="eff"
              type="monotone"
              dataKey="mi_per_kwh"
              stroke="#10b981"
              strokeWidth={2}
              dot={(props: { cx?: number; cy?: number; payload?: SeasonalEfficiencyPoint }) => {
                const { cx = 0, cy = 0, payload } = props
                if (payload?.low_confidence) {
                  return (
                    <circle
                      key={`dot-${payload.period}`}
                      cx={cx}
                      cy={cy}
                      r={3}
                      fill="#10b981"
                      fillOpacity={0.4}
                      stroke="#10b981"
                      strokeWidth={1}
                      strokeDasharray="2 2"
                    />
                  )
                }
                return <circle key={`dot-${payload?.period}`} cx={cx} cy={cy} r={3} fill="#10b981" />
              }}
              connectNulls={false}
            />
            <Line
              yAxisId="range"
              type="monotone"
              dataKey="derived_range_display"
              name={rangeLabel}
              stroke="#38bdf8"
              strokeWidth={2}
              strokeDasharray="4 2"
              dot={false}
              connectNulls={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="mt-2 text-[10px] text-slate-400 dark:text-slate-500">
        Range is derived (mi/kWh &times; battery). A full year of data is needed for a true
        seasonal comparison.
      </p>
    </div>
  )
}
