/**
 * Car detail / lifetime page.
 *
 * Shows the car header (make/model, battery, masked VIN, Active/Archived badge,
 * ownership span) and lifetime tiles (total sessions, kWh, cost, avg p/kWh,
 * mi/kWh, home/public split). Links to Insights filtered for this car.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api, type CarLifetimePayload, type CarPayload } from '@/api/client'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pill } from '@/components/ui/Pill'
import { EfficiencyValue } from '@/components/EfficiencyValue'
import { formatCurrency } from '@/utils/currency'
import { formatDistance, useSetting } from '@/stores/settingsStore'

export default function CarDetail() {
  const { id } = useParams<{ id: string }>()
  const carId = Number(id)
  const currency = useSetting<string>('currency') ?? 'GBP'
  const [car, setCar] = useState<CarPayload | null>(null)
  const [lifetime, setLifetime] = useState<CarLifetimePayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!carId) return
    let cancelled = false
    void (async () => {
      setLoading(true)
      setError(null)
      try {
        const [carData, ltData] = await Promise.all([
          api.getCar(carId),
          api.getCarLifetime(carId),
        ])
        if (!cancelled) {
          setCar(carData)
          setLifetime(ltData)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? `${err.status}: ${err.message}` : String(err))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [carId])

  if (loading) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-6">
        <p className="text-sm text-slate-500">Loading…</p>
      </main>
    )
  }

  if (error || !car || !lifetime) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-6">
        <div role="alert" className="rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error ?? 'Car not found.'}
        </div>
      </main>
    )
  }

  const span = lifetime.ownership_span
  const spanText = span.first && span.last
    ? `${span.first} – ${span.last}`
    : span.first
      ? `From ${span.first}`
      : '—'

  return (
    <main className="mx-auto max-w-5xl px-4 py-6">
      <PageHeader
        title={car.display_name}
        subtitle={`${car.make} ${car.model} · ${car.battery_kwh} kWh`}
        actions={
          <div className="flex items-center gap-2">
            {car.active ? (
              <Pill tone="green">Active</Pill>
            ) : (
              <Pill tone="slate">Archived</Pill>
            )}
            <Link
              to={`/insights?car=${car.id}`}
              className="rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              View in Insights
            </Link>
          </div>
        }
      />

      {/* Header strip: VIN + ownership span */}
      <div className="mb-6 flex flex-wrap gap-6 text-sm text-slate-600 dark:text-slate-400">
        {car.vin && (
          <div>
            <span className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">VIN</span>
            <p className="font-mono text-[13px] text-slate-700 dark:text-slate-200">{car.vin}</p>
          </div>
        )}
        <div>
          <span className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">Ownership span</span>
          <p className="text-slate-700 dark:text-slate-200">{spanText}</p>
        </div>
      </div>

      {/* Lifetime tiles */}
      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <LifetimeTile label="Sessions" value={String(lifetime.total_sessions)} />
        <LifetimeTile label="kWh" value={lifetime.total_kwh.toFixed(1)} />
        <LifetimeTile label="Total cost" value={formatCurrency(lifetime.total_cost_pence, currency)} />
        <LifetimeTile
          label="Avg p/kWh"
          value={lifetime.lifetime_avg_p_per_kwh !== null ? `${lifetime.lifetime_avg_p_per_kwh.toFixed(1)}p` : '—'}
          testId="tile-avg-p-per-kwh"
        />
        <LifetimeTile
          label="Efficiency"
          value={<EfficiencyValue miPerKwh={lifetime.lifetime_mi_per_kwh} />}
          testId="tile-mi-per-kwh"
        />
        <LifetimeTile
          label="Home sessions"
          value={String(lifetime.home_public.home.sessions)}
        />
      </div>

      {/* Battery health & seasonal range — only when estimated_usable_kwh is present */}
      {lifetime.estimated_usable_kwh != null && (
        <BatteryHealthCard
          estimatedUsableKwh={lifetime.estimated_usable_kwh}
          nominalKwh={car.battery_kwh}
          seasonalRangeSpan={lifetime.seasonal_range_span}
        />
      )}

      {/* Home vs Public breakdown */}
      <Card className="mb-6">
        <p className="mb-3 text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">Home vs public charging</p>
        <div className="grid grid-cols-2 gap-4">
          <HomePublicTile label="Home" bucket={lifetime.home_public.home} currency={currency} />
          <HomePublicTile label="Public" bucket={lifetime.home_public.public} currency={currency} />
        </div>
      </Card>
    </main>
  )
}

function LifetimeTile({ label, value, testId }: { label: string; value: ReactNode; testId?: string }) {
  return (
    <Card className="flex flex-col gap-1 p-3">
      <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">{label}</dt>
      <dd className="text-lg font-semibold text-slate-900 dark:text-slate-100" data-testid={testId}>{value}</dd>
    </Card>
  )
}

function HomePublicTile({ label, bucket, currency }: {
  label: string
  bucket: { spend_pence: number; kwh: number; sessions: number; avg_p_per_kwh: number | null }
  currency: string
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-semibold text-slate-700 dark:text-slate-200">{label}</p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400">
        <div><dt className="text-[10px] uppercase tracking-[0.1em]">Sessions</dt><dd className="font-medium">{bucket.sessions}</dd></div>
        <div><dt className="text-[10px] uppercase tracking-[0.1em]">kWh</dt><dd className="font-medium">{bucket.kwh.toFixed(1)}</dd></div>
        <div><dt className="text-[10px] uppercase tracking-[0.1em]">Cost</dt><dd className="font-medium">{formatCurrency(bucket.spend_pence, currency)}</dd></div>
        <div><dt className="text-[10px] uppercase tracking-[0.1em]">Avg p/kWh</dt><dd className="font-medium">{bucket.avg_p_per_kwh !== null ? `${bucket.avg_p_per_kwh.toFixed(1)}p` : '—'}</dd></div>
      </dl>
    </div>
  )
}

function BatteryHealthCard({ estimatedUsableKwh, nominalKwh, seasonalRangeSpan }: {
  estimatedUsableKwh: number
  nominalKwh: number
  seasonalRangeSpan: { min_km: number | null; max_km: number | null; avg_km: number | null } | null
}) {
  // Degradation vs nominal — guard against negative values (estimated > nominal edge case)
  let degradationText: string
  if (nominalKwh > 0) {
    const rawPct = (1 - estimatedUsableKwh / nominalKwh) * 100
    if (rawPct < 0) {
      degradationText = '—'
    } else {
      degradationText = `${rawPct.toFixed(1)}%`
    }
  } else {
    degradationText = '—'
  }

  // Seasonal range span — convert km to user unit; both min and max must be present
  let seasonalSpanText: string
  if (
    seasonalRangeSpan != null &&
    seasonalRangeSpan.min_km != null &&
    seasonalRangeSpan.max_km != null
  ) {
    const { value: minVal, unit } = formatDistance(seasonalRangeSpan.min_km)
    const { value: maxVal } = formatDistance(seasonalRangeSpan.max_km)
    seasonalSpanText = `${Math.round(minVal)}–${Math.round(maxVal)} ${unit}`
  } else {
    seasonalSpanText = '—'
  }

  return (
    <Card className="mb-6">
      <p className="mb-3 text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
        Battery health &amp; seasonal range
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {/* Estimated usable capacity */}
        <div>
          <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">Estimated usable</dt>
          <dd
            className="text-lg font-semibold text-slate-900 dark:text-slate-100"
            data-testid="tile-estimated-usable"
          >
            {estimatedUsableKwh.toFixed(1)} kWh
          </dd>
          <p
            className="mt-0.5 text-[11px] text-slate-400 dark:text-slate-500"
            data-testid="tile-estimated-usable-caveat"
          >
            Indicative, not a certified SoH
          </p>
        </div>

        {/* Degradation vs nominal */}
        <div>
          <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">
            vs {nominalKwh} kWh nominal
          </dt>
          <dd
            className="text-lg font-semibold text-slate-900 dark:text-slate-100"
            data-testid="tile-degradation"
          >
            {degradationText}
          </dd>
          <p className="mt-0.5 text-[11px] text-slate-400 dark:text-slate-500">degradation</p>
        </div>

        {/* Seasonal range span */}
        <div>
          <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">Seasonal range span</dt>
          <dd
            className="text-lg font-semibold text-slate-900 dark:text-slate-100"
            data-testid="tile-seasonal-span"
          >
            {seasonalSpanText}
          </dd>
          <p className="mt-0.5 text-[11px] text-slate-400 dark:text-slate-500">worst–best range</p>
        </div>
      </div>
    </Card>
  )
}
