import { useEffect, useState } from 'react'
import {
  ApiError,
  api,
  type MileageStatusPayload,
  type MileagePeriodPayload,
} from '@/api/client'
import { Button } from '@/components/ui/button'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { useDistanceUnit, type DistanceUnit } from '@/stores/settingsStore'
import { kmToMi } from '@/utils/distance'

interface CarMileageSectionProps {
  carId: number
}

interface DraftConfig {
  start_date: string
  opening_miles: string
  annual_mileage_target_miles: string
}

const EMPTY_DRAFT: DraftConfig = {
  start_date: '',
  opening_miles: '',
  annual_mileage_target_miles: '',
}

function convertKmDisplay(km: number, unit: DistanceUnit): number {
  return unit === 'km' ? km : kmToMi(km)
}

function formatMonth(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

function formatDate(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

export function CarMileageSection({ carId }: CarMileageSectionProps) {
  const unit = useDistanceUnit()
  const [status, setStatus] = useState<MileageStatusPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<DraftConfig>(EMPTY_DRAFT)
  const [busy, setBusy] = useState(false)

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      const data = await api.getCarMileage(carId)
      setStatus(data)
    } catch (err) {
      setError(
        err instanceof ApiError ? `${err.status}: ${err.message}` : String(err),
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void reload()
  }, [carId])

  function startEdit() {
    if (status?.current_period) {
      const cp = status.current_period
      setDraft({
        start_date: cp.period_start_date,
        opening_miles: String(
          Math.round(convertKmDisplay(cp.opening_odometer_km, 'mi')),
        ),
        annual_mileage_target_miles:
          cp.annual_mileage_target_km !== null
            ? String(
                Math.round(convertKmDisplay(cp.annual_mileage_target_km, 'mi')),
              )
            : '',
      })
    } else {
      setDraft({
        ...EMPTY_DRAFT,
        start_date: new Date().toISOString().slice(0, 10),
      })
    }
    setEditing(true)
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    if (!draft.start_date || !draft.opening_miles) return
    setBusy(true)
    setError(null)
    try {
      const target = draft.annual_mileage_target_miles.trim()
      await api.setCarMileage(carId, {
        start_date: draft.start_date,
        opening_miles: Number(draft.opening_miles),
        annual_mileage_target_miles: target === '' ? null : Number(target),
      })
      setEditing(false)
      await reload()
    } catch (err) {
      setError(
        err instanceof ApiError ? `${err.status}: ${err.message}` : String(err),
      )
    } finally {
      setBusy(false)
    }
  }

  async function handleDisable() {
    if (
      !window.confirm(
        'Disable mileage tracking? This deletes the current period and all history.',
      )
    ) {
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.clearCarMileage(carId)
      await reload()
    } catch (err) {
      setError(
        err instanceof ApiError ? `${err.status}: ${err.message}` : String(err),
      )
    } finally {
      setBusy(false)
    }
  }

  if (loading) {
    return (
      <div className="text-xs text-slate-500 dark:text-slate-400">
        Loading mileage…
      </div>
    )
  }

  return (
    <div
      className="mt-3 border-t border-slate-200 pt-3 dark:border-slate-700"
      data-testid={`car-mileage-${carId}`}
    >
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
          Annual mileage
        </h4>
        {!editing && (
          <div className="flex gap-1">
            {status?.enabled ? (
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={startEdit}
                  disabled={busy}
                >
                  Edit
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => void handleDisable()}
                  disabled={busy}
                  className="text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
                >
                  Disable
                </Button>
              </>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={startEdit}
              >
                Enable tracking
              </Button>
            )}
          </div>
        )}
      </div>

      {error && (
        <div role="alert" className="mt-2 text-xs text-red-600">
          {error}
        </div>
      )}

      {editing && (
        <form
          onSubmit={handleSave}
          className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3"
        >
          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
            Start date
            <input
              required
              type="date"
              value={draft.start_date}
              onChange={(e) => setDraft({ ...draft, start_date: e.target.value })}
              className="mt-1 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
            />
          </label>
          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
            Opening mileage (mi)
            <input
              required
              type="number"
              step="1"
              min="0"
              value={draft.opening_miles}
              onChange={(e) =>
                setDraft({ ...draft, opening_miles: e.target.value })
              }
              className="mt-1 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              placeholder="e.g. 7022"
            />
          </label>
          <label className="block text-xs font-medium text-slate-700 dark:text-slate-300">
            Annual limit (mi){' '}
            <span className="font-normal text-slate-400">optional</span>
            <input
              type="number"
              step="1"
              min="1"
              value={draft.annual_mileage_target_miles}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  annual_mileage_target_miles: e.target.value,
                })
              }
              className="mt-1 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100"
              placeholder="e.g. 10000 for a lease cap"
            />
          </label>
          <div className="sm:col-span-3 flex gap-2">
            <Button type="submit" size="sm" disabled={busy}>
              {busy ? 'Saving…' : 'Save'}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setEditing(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            {status?.enabled && (
              <span className="self-center text-[11px] text-slate-500 dark:text-slate-400">
                Saving replaces the current period and clears history.
              </span>
            )}
          </div>
        </form>
      )}

      {!editing && status?.enabled && status.current_period && (
        <CurrentPeriodView period={status.current_period} unit={unit} />
      )}

      {!editing && status?.history && status.history.length > 0 && (
        <HistoryTable history={status.history} unit={unit} />
      )}

      {!editing && !status?.enabled && (
        <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
          Track your annual mileage from a chosen start date. Closing mileage
          is captured automatically before each anniversary so you keep
          year-on-year history.
        </p>
      )}
    </div>
  )
}

interface CurrentPeriodViewProps {
  period: MileageStatusPayload['current_period']
  unit: DistanceUnit
}

function CurrentPeriodView({ period, unit }: CurrentPeriodViewProps) {
  if (!period) return null
  const usedKm = Math.max(
    0,
    period.current_odometer_km - period.opening_odometer_km,
  )
  const used = convertKmDisplay(usedKm, unit)
  const target =
    period.annual_mileage_target_km !== null
      ? convertKmDisplay(period.annual_mileage_target_km, unit)
      : null
  const pct = target && target > 0 ? Math.min(100, (used / target) * 100) : null
  const overLimit = target !== null && used > target

  return (
    <div className="mt-2">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-slate-500 dark:text-slate-400">
          {formatMonth(period.period_start_date)} →{' '}
          {formatMonth(period.period_end_date)}
        </span>
        <span
          className={
            overLimit
              ? 'font-semibold tabular-nums text-amber-600 dark:text-amber-400'
              : 'font-semibold tabular-nums text-slate-900 dark:text-slate-100'
          }
        >
          {Math.round(used).toLocaleString()}
          {target !== null && (
            <span className="font-normal text-slate-500 dark:text-slate-400">
              {' '}
              / {Math.round(target).toLocaleString()}
            </span>
          )}{' '}
          {unit}
        </span>
      </div>
      {pct !== null && (
        <ProgressBar
          value={pct}
          gradient={!overLimit}
          className="mt-1 h-1.5"
          aria-label="Annual mileage used"
        />
      )}
      <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400 tabular-nums">
        Opening{' '}
        {Math.round(
          convertKmDisplay(period.opening_odometer_km, unit),
        ).toLocaleString()}{' '}
        {unit} · current{' '}
        {Math.round(
          convertKmDisplay(period.current_odometer_km, unit),
        ).toLocaleString()}{' '}
        {unit}
      </p>
    </div>
  )
}

interface HistoryTableProps {
  history: MileagePeriodPayload[]
  unit: DistanceUnit
}

function HistoryTable({ history, unit }: HistoryTableProps) {
  return (
    <div className="mt-3">
      <h5 className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
        Previous years
      </h5>
      <table className="mt-1 w-full table-auto text-xs">
        <thead className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">
          <tr>
            <th className="py-1 text-left font-normal">Period</th>
            <th className="py-1 text-right font-normal">Used</th>
            <th className="py-1 text-right font-normal">Limit</th>
          </tr>
        </thead>
        <tbody>
          {history.map((row) => {
            const usedKm =
              row.closing_odometer_km !== null
                ? Math.max(0, row.closing_odometer_km - row.opening_odometer_km)
                : null
            const used =
              usedKm !== null ? convertKmDisplay(usedKm, unit) : null
            const target =
              row.annual_mileage_target_km !== null
                ? convertKmDisplay(row.annual_mileage_target_km, unit)
                : null
            const overLimit =
              used !== null && target !== null && used > target
            return (
              <tr
                key={row.period_start_date}
                className="border-t border-slate-200 dark:border-slate-700"
              >
                <td className="py-1 text-slate-600 dark:text-slate-400">
                  {formatDate(row.period_start_date)} →{' '}
                  {formatDate(row.period_end_date)}
                </td>
                <td
                  className={
                    overLimit
                      ? 'py-1 text-right font-semibold tabular-nums text-amber-600 dark:text-amber-400'
                      : 'py-1 text-right font-semibold tabular-nums text-slate-900 dark:text-slate-100'
                  }
                >
                  {used !== null
                    ? `${Math.round(used).toLocaleString()} ${unit}`
                    : '—'}
                </td>
                <td className="py-1 text-right tabular-nums text-slate-500 dark:text-slate-400">
                  {target !== null
                    ? `${Math.round(target).toLocaleString()} ${unit}`
                    : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
