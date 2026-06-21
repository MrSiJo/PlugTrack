/**
 * Home charge planner page.
 *
 * Lets the user pick a car, a start SoC %, a target SoC %, and an optional
 * custom kW value, then calls GET /api/charge-plan and renders a multi-scenario
 * table with one row per scenario: label, effective power, estimated time,
 * finish/nights for AC window rows, and a confidence/source tag pill.
 */
import { useEffect, useState } from 'react'
import { ApiError, api, type BlendedPlanResponse, type CarPayload, type ScenarioPlanResponse, type ScenarioRow, type ScenarioSourceTag } from '@/api/client'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pill, type PillTone } from '@/components/ui/Pill'
import { EfficiencyValue } from '@/components/EfficiencyValue'
import { formatCurrency } from '@/utils/currency'
import { useSetting } from '@/stores/settingsStore'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes}m`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m === 0 ? `${h}h` : `${h}h ${String(m).padStart(2, '0')}m`
}

// ---------------------------------------------------------------------------
// Source tag → pill label + tone
// ---------------------------------------------------------------------------

interface TagDisplay {
  label: string
  tone: PillTone
}

const SOURCE_TAG_DISPLAY: Record<ScenarioSourceTag, TagDisplay> = {
  history: { label: 'from your history', tone: 'green' },
  spec: { label: 'spec', tone: 'cyan' },
  curve: { label: 'curve-derived', tone: 'green' },
  average: { label: 'average-derived', tone: 'amber' },
  modelled: { label: 'modelled', tone: 'slate' },
}

function sourceTagDisplay(tag: ScenarioSourceTag): TagDisplay {
  return SOURCE_TAG_DISPLAY[tag] ?? { label: tag, tone: 'slate' }
}

// ---------------------------------------------------------------------------
// Scenario table
// ---------------------------------------------------------------------------

interface PlanTableProps {
  plan: ScenarioPlanResponse
}

function PlanTable({ plan }: PlanTableProps) {
  return (
    <div data-testid="plan-table">
      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
                Scenario
              </th>
              <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
                Power
              </th>
              <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
                Est. time
              </th>
              <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
                Finishes
              </th>
              <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
                Source
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {plan.rows.map((row: ScenarioRow, i: number) => {
              const { label: tagLabel, tone } = sourceTagDisplay(row.source_tag)
              const finishCell =
                row.finish_at != null
                  ? `${row.finish_at}${row.nights != null ? ` (${row.nights} night${row.nights === 1 ? '' : 's'})` : ''}`
                  : '—'

              return (
                <tr
                  key={i}
                  data-testid={`plan-row-${i}`}
                  className="hover:bg-slate-50 dark:hover:bg-slate-800/30"
                >
                  <td className="px-4 py-3">
                    <span className="font-medium text-slate-800 dark:text-slate-200">
                      {row.label}
                    </span>
                    {row.note != null && (
                      <span className="ml-2 text-xs text-amber-600 dark:text-amber-400">
                        {row.note}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-700 dark:text-slate-300">
                    {row.power_kw} kW
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-700 dark:text-slate-300">
                    {fmtMinutes(row.minutes)}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-500 dark:text-slate-400">
                    {finishCell}
                  </td>
                  <td className="px-4 py-3">
                    <Pill tone={tone}>{tagLabel}</Pill>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Blended two-phase view (rapid DC → home AC)
// ---------------------------------------------------------------------------

interface PhaseCardProps {
  title: string
  subtitle: string
  kwh: number
  minutes: number
  costPence: number
  currency: string
  testId: string
}

function PhaseCard({ title, subtitle, kwh, minutes, costPence, currency, testId }: PhaseCardProps) {
  return (
    <Card className="flex flex-col gap-2 p-4" data-testid={testId}>
      <div>
        <p className="text-sm font-semibold text-slate-800 dark:text-slate-200">{title}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>
      </div>
      <dl className="grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400">Energy</dt>
          <dd className="tabular-nums font-medium text-slate-800 dark:text-slate-200">{kwh.toFixed(1)} kWh</dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400">Time</dt>
          <dd className="tabular-nums font-medium text-slate-800 dark:text-slate-200">{fmtMinutes(minutes)}</dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400">Cost</dt>
          <dd className="tabular-nums font-medium text-slate-800 dark:text-slate-200">{formatCurrency(costPence, currency)}</dd>
        </div>
      </dl>
    </Card>
  )
}

function BlendedView({ plan, currency }: { plan: BlendedPlanResponse; currency: string }) {
  return (
    <div className="space-y-4" data-testid="blended-view">
      <PhaseCard
        title="DC phase (rapid)"
        subtitle={`${plan.start_soc}% → ${plan.dc_stop_soc}% · ${plan.dc_rate_p}p/kWh`}
        kwh={plan.dc_phase.kwh}
        minutes={plan.dc_phase.minutes}
        costPence={plan.dc_phase.cost_pence}
        currency={currency}
        testId="blended-dc-phase"
      />
      <PhaseCard
        title="Home phase (overnight AC)"
        subtitle={`${plan.dc_stop_soc}% → ${plan.target_soc}% · ${plan.is_free ? 'free' : `${plan.home_rate_p_per_kwh}p/kWh`}`}
        kwh={plan.home_phase.kwh}
        minutes={plan.home_phase.minutes}
        costPence={plan.home_phase.cost_pence}
        currency={currency}
        testId="blended-home-phase"
      />
      <Card className="flex flex-col gap-2 border-indigo-200 p-4 dark:border-indigo-900" data-testid="blended-total">
        <p className="text-sm font-semibold text-indigo-700 dark:text-indigo-300">Blended total</p>
        <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400">Energy</dt>
            <dd className="tabular-nums font-semibold text-slate-900 dark:text-slate-100">{plan.total.kwh.toFixed(1)} kWh</dd>
          </div>
          <div>
            <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400">Total time</dt>
            <dd className="tabular-nums font-semibold text-slate-900 dark:text-slate-100">{fmtMinutes(plan.total.minutes)}</dd>
          </div>
          <div>
            <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400">Total cost</dt>
            <dd className="tabular-nums font-semibold text-slate-900 dark:text-slate-100" data-testid="blended-total-cost">
              {formatCurrency(plan.total.cost_pence, currency)}
            </dd>
          </div>
          <div>
            <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400">Cost / mile</dt>
            <dd className="tabular-nums font-semibold text-slate-900 dark:text-slate-100">
              {plan.total.cost_per_mile_p != null ? `${plan.total.cost_per_mile_p.toFixed(1)}p` : '—'}
            </dd>
          </div>
        </dl>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Efficiency: <EfficiencyValue miPerKwh={plan.total.mi_per_kwh} />
          <span className="ml-1 text-slate-400">(drive time between chargers not included)</span>
        </p>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type PlannerMode = 'scenarios' | 'blended'

export default function Planner() {
  const currency = useSetting<string>('currency') ?? 'GBP'
  const [cars, setCars] = useState<CarPayload[]>([])
  const [carsLoading, setCarsLoading] = useState(true)
  const [carsError, setCarsError] = useState<string | null>(null)

  const [mode, setMode] = useState<PlannerMode>('scenarios')
  const [carId, setCarId] = useState<number | null>(null)
  const [startSoc, setStartSoc] = useState<number | ''>(60)
  const [targetSoc, setTargetSoc] = useState<number | ''>(80)
  const [customKw, setCustomKw] = useState<number | undefined>(undefined)

  // Blended-mode inputs.
  const [dcStopSoc, setDcStopSoc] = useState<number | ''>(70)
  const [dcRateP, setDcRateP] = useState<number | ''>(45)

  const [plan, setPlan] = useState<ScenarioPlanResponse | null>(null)
  const [planLoading, setPlanLoading] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)

  const [blended, setBlended] = useState<BlendedPlanResponse | null>(null)
  const [blendedLoading, setBlendedLoading] = useState(false)
  const [blendedError, setBlendedError] = useState<string | null>(null)

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

  // Fetch the scenario plan whenever inputs change (and cars are ready).
  useEffect(() => {
    if (mode !== 'scenarios') return
    if (carId === null) return
    if (startSoc === '' || targetSoc === '') {
      setPlan(null)
      setPlanError('Enter a start and target SoC.')
      return
    }
    if (targetSoc <= startSoc) {
      setPlan(null)
      setPlanError('Target must be higher than start.')
      return
    }
    let cancelled = false
    setPlanLoading(true)
    setPlanError(null)
    void (async () => {
      try {
        const result = await api.getChargePlan(carId, startSoc, targetSoc, customKw)
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
  }, [mode, carId, startSoc, targetSoc, customKw])

  // Fetch the blended plan whenever its inputs change.
  useEffect(() => {
    if (mode !== 'blended') return
    if (carId === null) return
    if (startSoc === '' || dcStopSoc === '' || targetSoc === '') {
      setBlended(null)
      setBlendedError('Enter start, DC-stop and target SoC.')
      return
    }
    if (!(startSoc <= dcStopSoc && dcStopSoc <= targetSoc)) {
      setBlended(null)
      setBlendedError('Need start ≤ DC-stop ≤ target.')
      return
    }
    if (targetSoc <= startSoc) {
      setBlended(null)
      setBlendedError('Target must be higher than start.')
      return
    }
    let cancelled = false
    setBlendedLoading(true)
    setBlendedError(null)
    void (async () => {
      try {
        const result = await api.getBlendedChargePlan(
          carId,
          startSoc,
          dcStopSoc,
          targetSoc,
          dcRateP === '' ? undefined : dcRateP,
        )
        if (!cancelled) {
          setBlended(result)
          setBlendedLoading(false)
        }
      } catch (err) {
        if (!cancelled) {
          setBlendedError(err instanceof ApiError ? err.message : 'Failed to load plan')
          setBlended(null)
          setBlendedLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [mode, carId, startSoc, dcStopSoc, targetSoc, dcRateP])

  const inputCls =
    'w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900'

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <PageHeader
        title="Charge Planner"
        subtitle="Compare charging scenarios, or split a charge across rapid + home."
      />

      {/* Mode toggle */}
      <div className="mb-4 inline-flex rounded-lg border border-slate-200 p-0.5 dark:border-slate-700" role="tablist">
        {(['scenarios', 'blended'] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => setMode(m)}
            data-testid={`planner-mode-${m}`}
            className={
              'rounded-md px-3 py-1 text-sm font-medium transition ' +
              (mode === m
                ? 'bg-indigo-600 text-white'
                : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800')
            }
          >
            {m === 'scenarios' ? 'Scenarios' : 'Blended'}
          </button>
        ))}
      </div>

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
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
                    {c.display_name}
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
                onChange={(e) => {
                  const raw = e.target.value
                  if (raw === '') { setStartSoc(''); return }
                  const n = Number(raw)
                  if (!Number.isFinite(n)) return
                  setStartSoc(Math.min(100, Math.max(0, Math.floor(n))))
                }}
                data-testid="planner-start-soc"
              />
            </label>

            {mode === 'blended' && (
              <label className="block">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-slate-500">
                  DC stop SoC %
                </span>
                <input
                  className={inputCls}
                  type="number"
                  min={0}
                  max={100}
                  value={dcStopSoc}
                  onChange={(e) => {
                    const raw = e.target.value
                    if (raw === '') { setDcStopSoc(''); return }
                    const n = Number(raw)
                    if (!Number.isFinite(n)) return
                    setDcStopSoc(Math.min(100, Math.max(0, Math.floor(n))))
                  }}
                  data-testid="planner-dc-stop-soc"
                />
              </label>
            )}

            <label className="block">
              <span className="text-xs font-medium uppercase tracking-[0.1em] text-slate-500">
                {mode === 'blended' ? 'Home target SoC %' : 'Target SoC %'}
              </span>
              <input
                className={inputCls}
                type="number"
                min={0}
                max={100}
                value={targetSoc}
                onChange={(e) => {
                  const raw = e.target.value
                  if (raw === '') { setTargetSoc(''); return }
                  const n = Number(raw)
                  if (!Number.isFinite(n)) return
                  setTargetSoc(Math.min(100, Math.max(0, Math.floor(n))))
                }}
                data-testid="planner-target-soc"
              />
            </label>

            {mode === 'scenarios' ? (
              <label className="block">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-slate-500">
                  Custom kW
                </span>
                <input
                  className={inputCls}
                  type="number"
                  min={1}
                  max={350}
                  step={0.1}
                  placeholder="e.g. 22"
                  value={customKw ?? ''}
                  onChange={(e) => {
                    const v = e.target.value
                    setCustomKw(v === '' ? undefined : Number(v))
                  }}
                  data-testid="planner-custom-kw"
                />
              </label>
            ) : (
              <label className="block">
                <span className="text-xs font-medium uppercase tracking-[0.1em] text-slate-500">
                  DC rate (p/kWh)
                </span>
                <input
                  className={inputCls}
                  type="number"
                  min={0}
                  step={0.1}
                  placeholder="e.g. 45"
                  value={dcRateP}
                  onChange={(e) => {
                    const raw = e.target.value
                    if (raw === '') { setDcRateP(''); return }
                    const n = Number(raw)
                    if (!Number.isFinite(n)) return
                    setDcRateP(Math.max(0, n))
                  }}
                  data-testid="planner-dc-rate"
                />
              </label>
            )}
          </div>
        )}
      </Card>

      {/* Result area */}
      {mode === 'scenarios' && (
        <>
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
          {plan && !planLoading && !planError && <PlanTable plan={plan} />}
        </>
      )}

      {mode === 'blended' && (
        <>
          {blendedLoading && (
            <p className="text-sm text-slate-500" data-testid="blended-loading">
              Calculating…
            </p>
          )}
          {blendedError && !blendedLoading && (
            <p role="alert" className="text-sm text-red-600" data-testid="blended-error">
              {blendedError}
            </p>
          )}
          {blended && !blendedLoading && !blendedError && (
            <BlendedView plan={blended} currency={currency} />
          )}
        </>
      )}
    </div>
  )
}
