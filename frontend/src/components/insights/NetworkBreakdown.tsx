import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatCurrency } from '@/utils/currency'
import type { InsightsNetworkRow } from '@/api/client'

export interface NetworkBreakdownProps {
  rows: InsightsNetworkRow[]
  currency: string
  className?: string
  'data-testid'?: string
}

interface TooltipProps {
  active?: boolean
  payload?: { payload?: InsightsNetworkRow }[]
  currency: string
}

function NetTooltip({ active, payload, currency }: TooltipProps) {
  const r = payload?.[0]?.payload
  if (!active || !r) return null
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <p className="font-medium text-slate-900 dark:text-slate-100">{r.network}</p>
      <p className="tabular-nums text-cyan-600 dark:text-cyan-300">{formatCurrency(r.spend_pence, currency)}</p>
    </div>
  )
}

export function NetworkBreakdown({
  rows,
  currency,
  className,
  'data-testid': testId,
}: NetworkBreakdownProps) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">No data for this range.</p>
  }
  return (
    <div className={className} data-testid={testId}>
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="currentColor"
              className="text-slate-200 dark:text-slate-800" />
            <XAxis type="number" tickFormatter={(v: number) => `${(v / 100).toFixed(0)}`}
              tick={{ fontSize: 10 }} stroke="currentColor" className="text-slate-500 dark:text-slate-400" />
            <YAxis type="category" dataKey="network" width={90} tick={{ fontSize: 11 }} stroke="currentColor"
              className="text-slate-500 dark:text-slate-400" />
            <Tooltip content={<NetTooltip currency={currency} />} cursor={{ fill: 'rgba(34,211,238,0.05)' }} />
            <Bar dataKey="spend_pence" fill="#22d3ee" radius={[0, 3, 3, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="mt-3 w-full text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
            <th className="pb-1 text-left font-medium">Network</th>
            <th className="pb-1 text-right font-medium">Spend</th>
            <th className="pb-1 text-right font-medium">Energy</th>
            <th className="pb-1 text-right font-medium">Sessions</th>
            <th className="pb-1 text-right font-medium">Avg</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.network} className="border-t border-slate-100 dark:border-slate-800">
              <td className="py-1.5 pr-4 text-slate-700 dark:text-slate-200">{r.network}</td>
              <td className="py-1.5 pr-4 text-right tabular-nums">{formatCurrency(r.spend_pence, currency)}</td>
              <td className="py-1.5 pr-4 text-right tabular-nums">{r.kwh.toFixed(1)} kWh</td>
              <td className="py-1.5 pr-4 text-right tabular-nums">{r.sessions}</td>
              <td className="py-1.5 text-right tabular-nums">
                {r.avg_p_per_kwh == null ? '—' : `${r.avg_p_per_kwh.toFixed(1)} p`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
