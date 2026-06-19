import { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, ApiError, type InsightsMileageResponse } from '@/api/client'
import { useDistanceUnit } from '@/stores/settingsStore'
import { kmToMi } from '@/utils/distance'

export interface MileageAllowanceProps {
  carId: number
}

function fmtDist(km: number | null, unit: 'mi' | 'km'): string {
  if (km == null) return '—'
  const v = unit === 'km' ? km : kmToMi(km)
  return `${Math.round(v).toLocaleString()} ${unit}`
}

const PACE_STYLE: Record<string, string> = {
  under: 'text-emerald-600 dark:text-emerald-300',
  on: 'text-cyan-600 dark:text-cyan-300',
  over: 'text-amber-600 dark:text-amber-300',
}

export function MileageAllowance({ carId }: MileageAllowanceProps) {
  const unit = useDistanceUnit()
  const [data, setData] = useState<InsightsMileageResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        setLoading(true)
        const res = await api.getInsightsMileage(carId)
        if (!cancelled) {
          setData(res)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load mileage')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [carId])

  if (loading) return <p className="text-sm text-slate-500 dark:text-slate-400">Loading…</p>
  if (error) return <p className="text-sm text-rose-600 dark:text-rose-400">{error}</p>
  if (!data || !data.enabled) {
    return (
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Set up mileage tracking on this car to see allowance pace.
      </p>
    )
  }

  // Burn-down: allowance pace line vs actual-used line over the period.
  const burn =
    data.target_km != null && data.days_total
      ? [
          { label: 'Start', allowance: 0, used: 0 },
          {
            label: 'Today',
            allowance: (data.target_km * (data.days_elapsed ?? 0)) / data.days_total,
            used: data.used_km ?? 0,
          },
          {
            label: 'Year end',
            allowance: data.target_km,
            used: data.projected_year_end_km != null ? data.projected_year_end_km - (data.opening_km ?? 0) : null,
          },
        ]
      : []

  const kpis: { label: string; value: string; tone?: string }[] = [
    { label: 'Used', value: fmtDist(data.used_km, unit) },
    { label: 'Allowance', value: fmtDist(data.target_km, unit) },
    data.remaining_km != null && data.remaining_km < 0
      ? { label: 'Over by', value: fmtDist(-data.remaining_km, unit), tone: 'text-amber-600 dark:text-amber-300' }
      : { label: 'Remaining', value: fmtDist(data.remaining_km, unit) },
    { label: 'Projected year-end use', value: fmtDist(
        data.projected_year_end_km != null && data.opening_km != null
          ? data.projected_year_end_km - data.opening_km
          : null, unit) },
    { label: 'Pace', value: data.pace ?? '—', tone: data.pace ? PACE_STYLE[data.pace] : undefined },
  ]

  return (
    <div data-testid="mileage-allowance" className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {kpis.map((k) => (
          <div key={k.label} className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            <p className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{k.label}</p>
            <p className={`text-lg font-semibold capitalize tabular-nums ${k.tone ?? 'text-slate-900 dark:text-slate-100'}`}>
              {k.value}
            </p>
          </div>
        ))}
      </div>
      {burn.length > 0 && (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={burn} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor"
                className="text-slate-200 dark:text-slate-800" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="currentColor"
                className="text-slate-500 dark:text-slate-400" />
              <YAxis tickFormatter={(v: number) => `${Math.round(unit === 'km' ? v : kmToMi(v))}`}
                tick={{ fontSize: 10 }} stroke="currentColor" className="text-slate-500 dark:text-slate-400" width={40} />
              <Tooltip />
              <ReferenceLine x="Today" stroke="#64748b" strokeDasharray="4 4" />
              <Line type="monotone" dataKey="allowance" stroke="#64748b" strokeWidth={2} dot strokeDasharray="5 4" />
              <Line type="monotone" dataKey="used" stroke="#22d3ee" strokeWidth={2} dot connectNulls={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
