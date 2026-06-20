/**
 * Home charge planner page.
 *
 * Lets the user pick a car, a start SoC %, a target SoC %, and an optional
 * custom kW value, then calls GET /api/charge-plan and renders a multi-scenario
 * table with one row per scenario: label, effective power, estimated time,
 * finish/nights for AC window rows, and a confidence/source tag pill.
 */
import { useEffect, useState } from 'react'
import { ApiError, api, type CarPayload, type ScenarioPlanResponse, type ScenarioRow, type ScenarioSourceTag } from '@/api/client'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pill, type PillTone } from '@/components/ui/Pill'

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
// Page
// ---------------------------------------------------------------------------

export default function Planner() {
  const [cars, setCars] = useState<CarPayload[]>([])
  const [carsLoading, setCarsLoading] = useState(true)
  const [carsError, setCarsError] = useState<string | null>(null)

  const [carId, setCarId] = useState<number | null>(null)
  const [startSoc, setStartSoc] = useState<number>(20)
  const [targetSoc, setTargetSoc] = useState<number>(100)
  const [customKw, setCustomKw] = useState<number | undefined>(undefined)

  const [plan, setPlan] = useState<ScenarioPlanResponse | null>(null)
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
  }, [carId, startSoc, targetSoc, customKw])

  const inputCls =
    'w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900'

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <PageHeader
        title="Charge Planner"
        subtitle="Compare charging scenarios across different power levels."
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
          <div className="grid gap-4 sm:grid-cols-4">
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
      {plan && !planLoading && !planError && <PlanTable plan={plan} />}
    </div>
  )
}
