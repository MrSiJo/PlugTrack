import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts'
import { formatCurrency } from '@/utils/currency'
import type { InsightsSplitBucket } from '@/api/client'

export interface HomePublicSplitProps {
  split: { home: InsightsSplitBucket; public: InsightsSplitBucket }
  currency: string
  className?: string
  'data-testid'?: string
}

const COLORS = { home: '#10b981', public: '#22d3ee' }

function row(label: string, b: InsightsSplitBucket, currency: string) {
  return (
    <tr className="border-t border-slate-100 dark:border-slate-800">
      <td className="py-1.5 pr-4 text-slate-700 dark:text-slate-200">{label}</td>
      <td className="py-1.5 pr-4 text-right tabular-nums">{formatCurrency(b.spend_pence, currency)}</td>
      <td className="py-1.5 pr-4 text-right tabular-nums">{b.kwh.toFixed(1)} kWh</td>
      <td className="py-1.5 pr-4 text-right tabular-nums">{b.sessions}</td>
      <td className="py-1.5 text-right tabular-nums">
        {b.avg_p_per_kwh == null ? '—' : `${b.avg_p_per_kwh.toFixed(1)} p`}
      </td>
    </tr>
  )
}

export function HomePublicSplit({
  split,
  currency,
  className,
  'data-testid': testId,
}: HomePublicSplitProps) {
  const total = split.home.spend_pence + split.public.spend_pence
  if (total === 0 && split.home.sessions === 0 && split.public.sessions === 0) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">No data for this range.</p>
  }
  const pie = [
    { name: 'Home', value: split.home.spend_pence, key: 'home' as const },
    { name: 'Public', value: split.public.spend_pence, key: 'public' as const },
  ].filter((d) => d.value > 0)

  return (
    <div className={`flex flex-col gap-4 sm:flex-row sm:items-center ${className ?? ''}`} data-testid={testId}>
      <div className="h-40 w-40 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={pie} dataKey="value" nameKey="name" innerRadius={42} outerRadius={64} paddingAngle={2}>
              {pie.map((d) => (
                <Cell key={d.key} fill={COLORS[d.key]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
            <th className="pb-1 text-left font-medium"> </th>
            <th className="pb-1 text-right font-medium">Spend</th>
            <th className="pb-1 text-right font-medium">Energy</th>
            <th className="pb-1 text-right font-medium">Sessions</th>
            <th className="pb-1 text-right font-medium">Avg</th>
          </tr>
        </thead>
        <tbody>
          {row('Home (AC)', split.home, currency)}
          {row('Public (DC)', split.public, currency)}
        </tbody>
      </table>
    </div>
  )
}
