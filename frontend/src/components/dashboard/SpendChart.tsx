import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { SpendTrendDay } from '@/api/client'
import { Card } from '@/components/ui/Card'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { formatCurrency } from '@/utils/currency'

export interface SpendChartProps {
  data: SpendTrendDay[]
  currency: string
  className?: string
  'data-testid'?: string
}

interface TooltipPayload {
  payload?: SpendTrendDay
}

interface CustomTooltipProps {
  active?: boolean
  payload?: TooltipPayload[]
  currency: string
}

function CustomTooltip({ active, payload, currency }: CustomTooltipProps) {
  const first = payload?.[0]
  if (!active || !first?.payload) return null
  const day = first.payload
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <p className="font-medium text-slate-900 dark:text-slate-100">
        {new Date(day.date).toLocaleDateString(undefined, {
          weekday: 'short',
          day: 'numeric',
          month: 'short',
        })}
      </p>
      <p className="tabular-nums text-cyan-600 dark:text-cyan-300">
        {formatCurrency(day.cost_pence, currency)}
      </p>
    </div>
  )
}

export function SpendChart({
  data,
  currency,
  className,
  ...rest
}: SpendChartProps) {
  const total = data.reduce((sum, d) => sum + d.cost_pence, 0)
  const days = data.length

  if (data.length === 0 || total === 0) {
    return (
      <Card className={className} data-testid={rest['data-testid']}>
        <p className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
          Last {days || 30} days
        </p>
        <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
          No spend yet — sessions with cost data will show here.
        </p>
      </Card>
    )
  }

  return (
    <Card className={className} data-testid={rest['data-testid']}>
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
            Last {days} days
          </p>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            <GradientNumber size="lg" className="mr-1.5">
              {formatCurrency(total, currency)}
            </GradientNumber>
            spent
          </p>
        </div>
      </div>
      <div className="mt-3 h-40 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="spend-gradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.95} />
                <stop offset="100%" stopColor="#10b981" stopOpacity={0.85} />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 3"
              vertical={false}
              stroke="currentColor"
              className="text-slate-200 dark:text-slate-800"
            />
            <XAxis
              dataKey="date"
              tickFormatter={(d: string) =>
                new Date(d).toLocaleDateString(undefined, { day: 'numeric' })
              }
              tick={{ fontSize: 10 }}
              stroke="currentColor"
              className="text-slate-500 dark:text-slate-400"
              interval="preserveStartEnd"
              minTickGap={20}
            />
            <YAxis
              tickFormatter={(v: number) =>
                v === 0 ? '0' : `${(v / 100).toFixed(0)}`
              }
              tick={{ fontSize: 10 }}
              stroke="currentColor"
              className="text-slate-500 dark:text-slate-400"
              width={28}
            />
            <Tooltip
              content={<CustomTooltip currency={currency} />}
              cursor={{ fill: 'rgba(34,211,238,0.05)' }}
            />
            <Bar
              dataKey="cost_pence"
              fill="url(#spend-gradient)"
              radius={[3, 3, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
