/**
 * Home charge planner page.
 *
 * Lets the user pick a car, a start SoC %, and a target SoC %, then
 * calls GET /api/charge-plan and renders:
 *   - Total duration (formatted as Xh YYm / Ym)
 *   - A verdict line (fits one window, or needs N nights)
 *   - Per-night breakdown when nights_needed > 1
 *   - Estimated cost in GBP
 *   - Power basis caption
 */
import { useEffect, useState } from 'react'
import { ApiError, api, type CarPayload, type ChargePlan } from '@/api/client'
import { Card } from '@/components/ui/Card'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { PageHeader } from '@/components/ui/PageHeader'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes}m`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m === 0 ? `${h}h` : `${h}h ${String(m).padStart(2, '0')}m`
}

function fmtPence(pence: number): string {
  return `£${(pence / 100).toFixed(2)}`
}

// ---------------------------------------------------------------------------
// Result card
// ---------------------------------------------------------------------------

interface PlanResultProps {
  plan: ChargePlan
}

function PlanResult({ plan }: PlanResultProps) {
  const verdict = plan.fits_one_window
    ? `Finishes ~${plan.finish_at}, within your ${plan.window_start}–${plan.window_end} window`
    : `Needs ${plan.nights_needed} nights, finishes ~${plan.finish_at} on night ${plan.nights_needed}`

  const powerCaption =
    plan.power_basis === 'history'
      ? `Based on your last ${plan.sample_size} home charge${plan.sample_size === 1 ? '' : 's'} (~${plan.power_kw} kW)`
      : `Estimated at ${plan.power_kw} kW (not enough home history yet)`

  return (
    <div data-testid="plan-result">
      {/* Hero strip */}
      <Card variant="hero" className="mb-4 flex flex-wrap items-center gap-6">
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
            Duration
          </span>
          <GradientNumber size="lg" data-testid="plan-duration">
            {fmtMinutes(plan.total_minutes)}
          </GradientNumber>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {plan.kwh_needed} kWh needed
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
            Est. cost
          </span>
          <GradientNumber size="lg" data-testid="plan-cost">
            {plan.is_free ? 'Free' : fmtPence(plan.cost_pence)}
          </GradientNumber>
          {!plan.is_free && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              @ {plan.home_rate_p_per_kwh}p / kWh
            </span>
          )}
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
            SoC
          </span>
          <GradientNumber size="lg">
            {plan.start_soc}→{plan.target_soc}%
          </GradientNumber>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {plan.target_soc - plan.start_soc}% gain
          </span>
        </div>
      </Card>

      {/* Verdict */}
      <p
        className="mb-4 text-sm text-slate-700 dark:text-slate-300"
        data-testid="plan-verdict"
      >
        {verdict}
      </p>

      {/* Per-night breakdown */}
      {plan.nights_needed > 1 && (
        <section className="mb-4" data-testid="plan-nights">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
            Night-by-night
          </h2>
          <ul className="space-y-1">
            {plan.nights.map((night) => (
              <li
                key={night.index}
                className="flex items-center gap-3 rounded border border-slate-200 px-3 py-2 text-sm dark:border-slate-700"
                data-testid={`plan-night-${night.index}`}
              >
                <span className="font-medium text-slate-700 dark:text-slate-300">
                  Night {night.index}
                </span>
                <span className="text-slate-500 dark:text-slate-400">
                  {fmtMinutes(night.minutes)} → reaches{' '}
                  <strong>{night.end_soc}%</strong>, finishes at{' '}
                  {night.finish_at}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Power basis caption */}
      <p
        className="text-xs text-slate-400 dark:text-slate-500"
        data-testid="plan-power-caption"
      >
        {powerCaption}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Planner() {
  const [cars, setCars] = useState<CarPayload[]>([])
  const [carsLoading, setCarsLoading] = useState(true)
  const [carsError, setCarsError] = useState<string | null>(null)

  const [carId, setCarId] = useState<number | null>(null)
  const [startSoc, setStartSoc] = useState<number>(20)
  const [targetSoc, setTargetSoc] = useState<number>(100)

  const [plan, setPlan] = useState<ChargePlan | null>(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)

  // Load cars once on mount.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const list = await api.getCars()
        if (!cancelled) {
          setCars(list)
          const activeCar = list.find((c) => c.active) ?? list[0] ?? null
          if (activeCar) setCarId(activeCar.id)
          setCarsLoading(false)
        }
      } catch (err) {
        if (!cancelled) {
          setCarsError(
            err instanceof ApiError ? err.message : 'Failed to load cars',
          )
          setCarsLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Fetch the plan whenever inputs change (and cars are ready).
  useEffect(() => {
    if (carId === null) return
    if (targetSoc <= startSoc) {
      setPlan(null)
      setPlanError('Target must be greater than start.')
      return
    }
    let cancelled = false
    setPlanLoading(true)
    setPlanError(null)
    void (async () => {
      try {
        const result = await api.getChargePlan(carId, startSoc, targetSoc)
        if (!cancelled) {
          setPlan(result)
          setPlanLoading(false)
        }
      } catch (err) {
        if (!cancelled) {
          setPlanError(
            err instanceof ApiError ? err.message : 'Failed to load plan',
          )
          setPlan(null)
          setPlanLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [carId, startSoc, targetSoc])

  const inputCls =
    'w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900'

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <PageHeader
        title="Charge Planner"
        subtitle="Estimate how many nights it will take to reach your target SoC."
      />

      {/* Inputs */}
      <Card className="mb-6">
        {carsLoading ? (
          <p className="text-sm text-slate-500">Loading cars…</p>
        ) : carsError ? (
          <p role="alert" className="text-sm text-red-600">
            {carsError}
          </p>
        ) : cars.length === 0 ? (
          <p className="text-sm text-slate-500">No cars found. Add one first.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-3">
            <label className="block">
              <span className="text-xs font-medium uppercase tracking-[0.1em] text-slate-500">
                Car
              </span>
              <select
                className={inputCls}
                value={carId ?? ''}
                onChange={(e) => setCarId(Number(e.target.value))}
                data-testid="planner-car-select"
              >
                {cars.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.make} {c.model}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-medium uppercase tracking-[0.1em] text-slate-500">
                Current SoC %
              </span>
              <input
                className={inputCls}
                type="number"
                min={0}
                max={100}
                value={startSoc}
                onChange={(e) => setStartSoc(Math.min(100, Math.max(0, Number(e.target.value))))}
                data-testid="planner-start-soc"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium uppercase tracking-[0.1em] text-slate-500">
                Target SoC %
              </span>
              <input
                className={inputCls}
                type="number"
                min={0}
                max={100}
                value={targetSoc}
                onChange={(e) => setTargetSoc(Math.min(100, Math.max(0, Number(e.target.value))))}
                data-testid="planner-target-soc"
              />
            </label>
          </div>
        )}
      </Card>

      {/* Result area */}
      {planLoading && (
        <p className="text-sm text-slate-500" data-testid="plan-loading">
          Calculating…
        </p>
      )}
      {planError && !planLoading && (
        <p role="alert" className="text-sm text-red-600" data-testid="plan-error">
          {planError}
        </p>
      )}
      {plan && !planLoading && !planError && <PlanResult plan={plan} />}
    </div>
  )
}
