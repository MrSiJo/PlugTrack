/**
 * Session detail page.
 *
 * Renders:
 * - Header (date, source, kWh, SoC delta)
 * - Cost breakdown widget (`CostBreakdown`) showing
 *   `kwh × tariff = computed_cost`. When the user has set a total
 *   override, also shows the receipt vs computed delta.
 * - Inline `<LocationLabelForm />` when location is unlabelled.
 * - Edit form for kWh, odometer, SoC, charging type/mode, network,
 *   notes, and cost overrides. Surfaces calculated kWh next to editable
 *   value so user can compare metered vs SoC-derived energy.
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ApiError,
  api,
  type ChargingSessionPayload,
  type CostBasis,
  type SessionMetricsPayload,
  type SessionUpdateRequest,
} from '@/api/client'
import LocationLabelForm from '@/components/LocationLabelForm'
import { useDistanceUnit } from '@/stores/settingsStore'
import { kmToMi, miToKm } from '@/utils/distance'

const COST_BASIS_LABEL: Record<CostBasis, string> = {
  override_total: 'Total cost overridden by user',
  override_per_kwh: 'Per-kWh cost overridden by user',
  location_free: 'Free at this location',
  location_rate: 'Location default rate',
  home_rate: 'Default home rate',
  unknown: 'Unknown',
}

function fmtPence(pence: number | null): string {
  if (pence === null) return '—'
  return `£${(pence / 100).toFixed(2)}`
}

function fmtPencePerMile(p: number | null): string {
  if (p === null) return '—'
  return `${p.toFixed(1)}p/mi`
}

interface PetrolComparisonProps {
  metrics: SessionMetricsPayload
  unit: 'mi' | 'km'
  currentSessionId: number
}

function PetrolComparison({
  metrics,
  unit,
  currentSessionId,
}: PetrolComparisonProps) {
  const settingsConfigured =
    metrics.petrol_price_p_per_litre !== null && metrics.petrol_mpg !== null
  const hasMiles =
    metrics.miles_since_previous !== null && metrics.miles_since_previous > 0
  const isChainFollowup = metrics.chain_anchor_id !== null
  const chainPartners = metrics.chain_session_ids.filter(
    (id) => id !== currentSessionId,
  )
  const distanceDisplay =
    metrics.miles_since_previous === null
      ? '—'
      : unit === 'mi'
        ? `${metrics.miles_since_previous.toFixed(1)} mi`
        : `${(metrics.miles_since_previous * 1.609344).toFixed(1)} km`

  const savings = metrics.savings_vs_petrol_p
  const savingsClass =
    savings === null
      ? 'text-slate-500'
      : savings > 0
        ? 'text-emerald-700 dark:text-emerald-400'
        : 'text-rose-700 dark:text-rose-400'

  return (
    <div
      className="rounded border border-slate-200 p-3 text-sm dark:border-slate-700"
      data-testid="petrol-comparison"
    >
      <p className="text-xs uppercase tracking-wide text-slate-500">
        Petrol comparison
      </p>
      {!settingsConfigured ? (
        <p className="mt-1 text-xs text-slate-500">
          Set <strong>Petrol price (p/litre)</strong> and{' '}
          <strong>Petrol MPG</strong> in Settings to enable this comparison.
        </p>
      ) : isChainFollowup ? (
        <p className="mt-1 text-xs text-slate-500" data-testid="chain-followup">
          No miles travelled since the last session — this charge is part of
          an ongoing top-up chain. The combined comparison lives on{' '}
          <Link
            to={`/sessions/${metrics.chain_anchor_id}`}
            className="text-indigo-600 underline"
          >
            session #{metrics.chain_anchor_id}
          </Link>
          .
        </p>
      ) : !hasMiles ? (
        <p className="mt-1 text-xs text-slate-500">
          Needs an odometer on this session and the previous one for the same
          car. Add the previous odometer to start tracking miles per session.
        </p>
      ) : (
        <>
          <dl className="mt-2 grid grid-cols-2 gap-y-1 text-xs">
            <dt className="text-slate-500">Miles since last session</dt>
            <dd className="text-right font-mono" data-testid="metric-miles">
              {distanceDisplay}
            </dd>

            <dt className="text-slate-500">Cost per mile (EV)</dt>
            <dd
              className="text-right font-mono"
              data-testid="metric-cost-per-mile"
            >
              {fmtPencePerMile(metrics.cost_per_mile_p)}
            </dd>

            <dt className="text-slate-500">Petrol equivalent</dt>
            <dd className="text-right font-mono" data-testid="metric-petrol-ppm">
              {fmtPencePerMile(metrics.petrol_ppm)}
            </dd>

            <dt className="text-slate-500">Petrol equivalent cost</dt>
            <dd
              className="text-right font-mono"
              data-testid="metric-petrol-cost"
            >
              {fmtPence(metrics.petrol_equivalent_cost_p)}
            </dd>

            <dt className="text-slate-500">Saving vs petrol</dt>
            <dd
              className={`text-right font-mono ${savingsClass}`}
              data-testid="metric-savings"
            >
              {savings !== null && savings > 0 ? '+' : ''}
              {fmtPence(savings)}
            </dd>
          </dl>
          {chainPartners.length > 0 && (
            <p
              className="mt-2 text-[10px] text-slate-500"
              data-testid="chain-anchor"
            >
              Includes top-up charges from{' '}
              {chainPartners.map((id, i) => (
                <span key={id}>
                  {i > 0 && ', '}
                  <Link
                    to={`/sessions/${id}`}
                    className="text-indigo-600 underline"
                  >
                    #{id}
                  </Link>
                </span>
              ))}{' '}
              · combined EV cost{' '}
              <strong>{fmtPence(metrics.chain_total_cost_pence)}</strong>.
            </p>
          )}
        </>
      )}
      {settingsConfigured && (
        <p className="mt-2 text-[10px] text-slate-400">
          Based on {metrics.petrol_price_p_per_litre}p/L petrol @{' '}
          {metrics.petrol_mpg} MPG.
        </p>
      )}
    </div>
  )
}

interface CostBreakdownProps {
  session: ChargingSessionPayload
}

export function CostBreakdown({ session }: CostBreakdownProps) {
  const tariff = session.tariff_p_per_kwh
  const computed =
    tariff !== null ? Math.round(session.kwh_added * tariff) : null

  return (
    <div
      className="rounded border border-slate-200 p-3 text-sm dark:border-slate-700"
      data-testid="cost-breakdown"
    >
      <p className="text-xs uppercase tracking-wide text-slate-500">
        Cost breakdown
      </p>
      {tariff !== null && (
        <p>
          {session.kwh_added.toFixed(2)} kWh × {tariff.toFixed(1)}p ={' '}
          <strong>{fmtPence(computed)}</strong>
        </p>
      )}
      <p className="mt-1 text-xs text-slate-500">
        Basis: {COST_BASIS_LABEL[session.cost_basis]}
      </p>
      {session.cost_basis === 'override_total' && (
        <p
          className="mt-2 rounded bg-blue-50 p-2 text-xs dark:bg-blue-950"
          data-testid="override-receipt"
        >
          Receipt: <strong>{fmtPence(session.cost_pence)}</strong>
          {tariff !== null && computed !== null && (
            <>
              {' '}
              ({fmtPence((session.cost_pence ?? 0) - computed)} fees over kWh × rate)
            </>
          )}
        </p>
      )}
    </div>
  )
}

interface EditFormProps {
  session: ChargingSessionPayload
  unit: 'mi' | 'km'
  onSaved: (updated: ChargingSessionPayload) => void
}

function SessionEditForm({ session, unit, onSaved }: EditFormProps) {
  const initialOdo =
    session.odometer_at_session_km !== null
      ? unit === 'mi'
        ? kmToMi(session.odometer_at_session_km)
        : session.odometer_at_session_km
      : null

  const [kwh, setKwh] = useState<string>(session.kwh_added.toFixed(2))
  const [odo, setOdo] = useState<string>(
    initialOdo !== null ? initialOdo.toFixed(0) : '',
  )
  const [startSoc, setStartSoc] = useState<string>(String(session.start_soc))
  const [endSoc, setEndSoc] = useState<string>(String(session.end_soc))
  const [chargingType, setChargingType] = useState(session.charging_type)
  const [chargingMode, setChargingMode] = useState(session.charging_mode)
  const [network, setNetwork] = useState(session.charge_network ?? '')
  const [notes, setNotes] = useState(session.notes ?? '')
  const [perKwh, setPerKwh] = useState<string>(
    session.cost_per_kwh_override_p !== null
      ? String(session.cost_per_kwh_override_p)
      : '',
  )
  const [totalOverride, setTotalOverride] = useState<string>(
    session.total_cost_pence_override !== null
      ? (session.total_cost_pence_override / 100).toFixed(2)
      : '',
  )
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr(null)
    setSaving(true)
    try {
      const odoNum = odo.trim() === '' ? null : Number(odo)
      const odoKm =
        odoNum === null
          ? null
          : unit === 'mi'
            ? miToKm(odoNum)
            : odoNum
      const body: SessionUpdateRequest = {
        kwh_added: Number(kwh),
        odometer_at_session_km: odoKm,
        start_soc: Number(startSoc),
        end_soc: Number(endSoc),
        charging_type: chargingType,
        charging_mode: chargingMode,
        charge_network: network.trim() === '' ? null : network,
        notes: notes.trim() === '' ? null : notes,
        cost_per_kwh_override_p: perKwh.trim() === '' ? null : Number(perKwh),
        total_cost_pence_override:
          totalOverride.trim() === ''
            ? null
            : Math.round(Number(totalOverride) * 100),
      }
      await api.updateSession(session.id, body)
      // Refetch via GET so the recomputed metrics payload comes along
      // — the PUT response intentionally skips metrics.
      const fresh = await api.getSession(session.id)
      onSaved(fresh)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const inputCls =
    'w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900'

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded border border-slate-200 p-3 text-sm dark:border-slate-700"
      data-testid="session-edit-form"
    >
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-xs uppercase text-slate-500">kWh added</span>
          <input
            className={inputCls}
            type="number"
            step="0.01"
            min="0"
            value={kwh}
            onChange={(e) => setKwh(e.target.value)}
            data-testid="edit-kwh"
          />
          {session.kwh_calculated !== null && (
            <span className="mt-1 block text-[10px] text-slate-500">
              Calculated from SoC: {session.kwh_calculated.toFixed(2)} kWh
            </span>
          )}
        </label>
        <label className="block">
          <span className="text-xs uppercase text-slate-500">
            Odometer ({unit})
          </span>
          <input
            className={inputCls}
            type="number"
            step="1"
            min="0"
            value={odo}
            onChange={(e) => setOdo(e.target.value)}
            data-testid="edit-odo"
          />
        </label>
        <label className="block">
          <span className="text-xs uppercase text-slate-500">Start SoC %</span>
          <input
            className={inputCls}
            type="number"
            min="0"
            max="100"
            value={startSoc}
            onChange={(e) => setStartSoc(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-xs uppercase text-slate-500">End SoC %</span>
          <input
            className={inputCls}
            type="number"
            min="0"
            max="100"
            value={endSoc}
            onChange={(e) => setEndSoc(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-xs uppercase text-slate-500">Charging type</span>
          <select
            className={inputCls}
            value={chargingType}
            onChange={(e) => setChargingType(e.target.value)}
          >
            <option value="ac">AC</option>
            <option value="dc">DC</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs uppercase text-slate-500">Charging mode</span>
          <select
            className={inputCls}
            value={chargingMode}
            onChange={(e) => setChargingMode(e.target.value)}
          >
            <option value="manual">Manual</option>
            <option value="timer">Timer</option>
            <option value="profile">Profile</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs uppercase text-slate-500">Charge network</span>
          <input
            className={inputCls}
            type="text"
            value={network}
            onChange={(e) => setNetwork(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-xs uppercase text-slate-500">
            Per-kWh override (p)
          </span>
          <input
            className={inputCls}
            type="number"
            step="0.01"
            min="0"
            value={perKwh}
            onChange={(e) => setPerKwh(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="text-xs uppercase text-slate-500">
            Total cost override (£)
          </span>
          <input
            className={inputCls}
            type="number"
            step="0.01"
            min="0"
            value={totalOverride}
            onChange={(e) => setTotalOverride(e.target.value)}
          />
        </label>
      </div>
      <label className="block">
        <span className="text-xs uppercase text-slate-500">Notes</span>
        <textarea
          className={inputCls}
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>
      {err && (
        <p role="alert" className="text-xs text-red-600">
          {err}
        </p>
      )}
      <div className="flex justify-end">
        <button
          type="submit"
          disabled={saving}
          className="rounded bg-indigo-600 px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
          data-testid="edit-save"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </form>
  )
}

export default function SessionDetail() {
  const params = useParams<{ id: string }>()
  const sessionId = params.id ? Number(params.id) : null
  const unit = useDistanceUnit()

  const [session, setSession] = useState<ChargingSessionPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [labelToast, setLabelToast] = useState<string | null>(null)

  useEffect(() => {
    if (sessionId === null) return
    let cancelled = false
    void (async () => {
      try {
        const data = await api.getSession(sessionId)
        if (!cancelled) {
          setSession(data)
          setLoading(false)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Failed to load session')
          setLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  if (loading) return <p className="p-6 text-sm text-slate-500">Loading…</p>
  if (error)
    return (
      <p role="alert" className="p-6 text-sm text-red-600">
        {error}
      </p>
    )
  if (!session) return <p className="p-6 text-sm">Not found.</p>

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <h1 className="mb-2 text-2xl font-semibold">
        Session #{session.id}
      </h1>
      <p className="mb-6 text-sm text-slate-500">
        {session.date} · {session.start_soc}% → {session.end_soc}% ·{' '}
        {session.kwh_added.toFixed(2)} kWh
        {session.kwh_calculated !== null &&
          Math.abs(session.kwh_calculated - session.kwh_added) >= 0.01 && (
            <span
              className="ml-2 text-xs text-slate-400"
              data-testid="kwh-calc-hint"
            >
              (calculated {session.kwh_calculated.toFixed(2)} kWh)
            </span>
          )}
      </p>

      <section className="mb-6">
        <CostBreakdown session={session} />
      </section>

      {session.metrics && (
        <section className="mb-6">
          <PetrolComparison
            metrics={session.metrics}
            unit={unit}
            currentSessionId={session.id}
          />
        </section>
      )}

      <section className="mb-6">
        <h2 className="mb-2 text-lg font-medium">Location</h2>
        {session.location_id === null ? (
          <p className="text-sm text-slate-500">No location attached.</p>
        ) : session.location_name ? (
          <div className="space-y-1" data-testid="location-summary">
            <p className="text-sm font-medium">{session.location_name}</p>
            {session.location_address && (
              <p className="text-xs text-slate-500">{session.location_address}</p>
            )}
            <p className="text-xs text-slate-500">
              <a
                href="/locations"
                className="text-indigo-600 underline"
              >
                Edit on the Locations page
              </a>
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            <p className="text-sm" data-testid="location-summary">
              Unlabelled location #{session.location_id} — name it below.
            </p>
            <LocationLabelForm
              locationId={session.location_id}
              onSaved={(count, label) => {
                setLabelToast(
                  `Saved "${label.name}". Recomputed cost on ${count} past session${count === 1 ? '' : 's'}.`,
                )
              }}
            />
            {labelToast && (
              <p
                role="status"
                className="text-xs text-emerald-600"
                data-testid="label-toast"
              >
                {labelToast}
              </p>
            )}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-lg font-medium">Edit session</h2>
        <SessionEditForm
          session={session}
          unit={unit}
          onSaved={(updated) => setSession(updated)}
        />
      </section>
    </div>
  )
}
