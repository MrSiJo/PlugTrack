import {
  CartesianGrid,
  Line,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { CapacityTrendPoint } from '@/api/client'

export interface CapacityTrendChartProps {
  data: CapacityTrendPoint[]
  className?: string
  'data-testid'?: string
}

interface TooltipProps {
  active?: boolean
  payload?: { payload?: CapacityTrendPoint & { usable_kwh_ac?: number | null; usable_kwh_dc?: number | null } }[]
}

function ChartTooltip({ active, payload }: TooltipProps) {
  const point = payload?.[0]?.payload
  if (!active || !point) return null
  const kwh = point.usable_kwh_ac ?? point.usable_kwh_dc ?? point.usable_kwh
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <p className="font-medium text-slate-900 dark:text-slate-100">
        {point.date}
        {point.low_confidence && (
          <span className="ml-1.5 text-[9px] uppercase tracking-wide text-amber-500">
            low confidence
          </span>
        )}
      </p>
      <p className="tabular-nums text-violet-600 dark:text-violet-300">
        {kwh != null ? `${kwh.toFixed(1)} kWh` : '—'}{' '}
        <span className="text-slate-400">
          ({point.charging_type?.toUpperCase()})
        </span>
      </p>
    </div>
  )
}

/**
 * Split data into AC and DC series so they can be coloured and
 * distinguished in the legend. Points belonging to the other type
 * get `null` so Recharts draws gaps rather than connecting across.
 */
function splitSeries(data: CapacityTrendPoint[]): {
  chartData: (CapacityTrendPoint & { usable_kwh_ac: number | null; usable_kwh_dc: number | null })[]
} {
  const chartData = data.map((d) => ({
    ...d,
    usable_kwh_ac: d.charging_type === 'ac' ? d.usable_kwh : null,
    usable_kwh_dc: d.charging_type === 'dc' ? d.usable_kwh : null,
  }))
  return { chartData }
}

export function CapacityTrendChart({
  data,
  className,
  'data-testid': testId,
}: CapacityTrendChartProps) {
  if (data.length === 0) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        No trend data yet.
      </p>
    )
  }

  const { chartData } = splitSeries(data)

  return (
    <div className={className} data-testid={testId}>
      <div className="mb-2 flex items-center gap-4 text-[10px] text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 rounded-sm bg-violet-400" />
          AC
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-2 w-4 rounded-sm bg-amber-400" />
          DC
        </span>
        <span className="ml-auto text-[9px] text-slate-400 dark:text-slate-500">usable kWh</span>
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
              dataKey="date"
              tick={{ fontSize: 10 }}
              stroke="currentColor"
              className="text-slate-500 dark:text-slate-400"
              interval="preserveStartEnd"
              minTickGap={30}
            />
            <YAxis
              tickFormatter={(v: number) => v.toFixed(1)}
              tick={{ fontSize: 10 }}
              stroke="currentColor"
              className="text-slate-500 dark:text-slate-400"
              width={36}
              label={{
                value: 'kWh',
                angle: -90,
                position: 'insideLeft',
                offset: 8,
                style: { fontSize: 9, fill: 'currentColor' },
              }}
            />
            <Tooltip content={<ChartTooltip />} />
            <Line
              type="monotone"
              dataKey="usable_kwh_ac"
              name="usable_kwh_ac"
              stroke="#a78bfa"
              strokeWidth={2}
              dot={(props: { cx?: number; cy?: number; payload?: CapacityTrendPoint }) => {
                const { cx = 0, cy = 0, payload } = props
                if (payload?.low_confidence) {
                  return (
                    <circle
                      key={`ac-dot-${payload.date}`}
                      cx={cx}
                      cy={cy}
                      r={3}
                      fill="#a78bfa"
                      fillOpacity={0.4}
                      stroke="#a78bfa"
                      strokeWidth={1}
                      strokeDasharray="2 2"
                    />
                  )
                }
                return payload ? (
                  <circle
                    key={`ac-dot-${payload.date}`}
                    cx={cx}
                    cy={cy}
                    r={3}
                    fill="#a78bfa"
                  />
                ) : <circle key="ac-dot-empty" cx={cx} cy={cy} r={0} />
              }}
              connectNulls={false}
            />
            <Line
              type="monotone"
              dataKey="usable_kwh_dc"
              name="usable_kwh_dc"
              stroke="#fbbf24"
              strokeWidth={2}
              dot={(props: { cx?: number; cy?: number; payload?: CapacityTrendPoint }) => {
                const { cx = 0, cy = 0, payload } = props
                if (payload?.low_confidence) {
                  return (
                    <circle
                      key={`dc-dot-${payload.date}`}
                      cx={cx}
                      cy={cy}
                      r={3}
                      fill="#fbbf24"
                      fillOpacity={0.4}
                      stroke="#fbbf24"
                      strokeWidth={1}
                      strokeDasharray="2 2"
                    />
                  )
                }
                return payload ? (
                  <circle
                    key={`dc-dot-${payload.date}`}
                    cx={cx}
                    cy={cy}
                    r={3}
                    fill="#fbbf24"
                  />
                ) : <circle key="dc-dot-empty" cx={cx} cy={cy} r={0} />
              }}
              connectNulls={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="mt-2 text-[10px] text-slate-400 dark:text-slate-500">
        Indicative trend, not a certified state-of-health. AC charging overstates usable
        capacity; cold weather lowers it.
      </p>
    </div>
  )
}
