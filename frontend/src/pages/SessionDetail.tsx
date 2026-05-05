/**
 * Session detail page.
 *
 * Renders:
 * - Header (date, source, kWh, SoC delta)
 * - Cost breakdown widget (`CostBreakdown`) showing
 *   `kwh × tariff = computed_cost`. When the user has set a total
 *   override, also shows the receipt vs computed delta.
 * - `<ChargeCurve />` SVG chart when `power_curve` is non-empty —
 *   shows SoC% (left axis, sky) and charging power kW (right axis,
 *   amber) over the duration of the session. Updated live by the sync
 *   worker on every poll while CHARGING.
 * - Inline `<LocationLabelForm />` when location is unlabelled.
 * - Edit form, gated behind an "Edit" toggle so the page reads as
 *   view-only by default. Editable fields: kWh, odometer, SoC,
 *   charging type/mode, network, notes, and cost overrides. Surfaces
 *   calculated kWh next to editable value so user can compare metered
 *   vs SoC-derived energy.
 * - `charge_network` shown as a badge under the header summary when set.
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Info } from 'lucide-react'
import {
  ApiError,
  api,
  type ChargingSessionPayload,
  type CostBasis,
  type SessionMetricsPayload,
  type SessionUpdateRequest,
} from '@/api/client'
import LocationLabelForm from '@/components/LocationLabelForm'
import { Card } from '@/components/ui/Card'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pill, type PillTone } from '@/components/ui/Pill'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
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

interface ChargeCurveProps {
  samples: number[][]
}

function ChargeCurve({ samples }: ChargeCurveProps) {
  // Normalise the [delta_seconds, soc, power_kw] triplets to a typed
  // shape up-front so the rest of the function isn't littered with
  // index-access guards.
  const points = samples
    .filter((s): s is [number, number, number] => s.length >= 3)
    .map(([t, soc, kw]) => ({ t, soc, kw }))

  if (points.length < 2) {
    return (
      <p className="text-xs text-slate-500">
        Not enough samples yet — the curve appears once the charger has
        reported a couple of readings.
      </p>
    )
  }

  const W = 480
  const H = 160
  const PAD_L = 32
  const PAD_R = 36
  const PAD_T = 8
  const PAD_B = 22

  const ts = points.map((p) => p.t)
  const tMin = Math.min(...ts)
  const tMax = Math.max(...ts)
  const tSpan = tMax - tMin || 1

  // Power axis auto-scales to the observed max (round up to nearest 5
  // for a clean grid). SoC axis is fixed 0–100.
  const powers = points.map((p) => p.kw)
  const pMaxObserved = Math.max(...powers, 1)
  const pMax = Math.max(5, Math.ceil(pMaxObserved / 5) * 5)

  const xAt = (t: number) =>
    PAD_L + ((t - tMin) / tSpan) * (W - PAD_L - PAD_R)
  const ySoc = (soc: number) =>
    PAD_T + (1 - soc / 100) * (H - PAD_T - PAD_B)
  const yPower = (kw: number) =>
    PAD_T + (1 - kw / pMax) * (H - PAD_T - PAD_B)

  const socPath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${xAt(p.t).toFixed(1)},${ySoc(p.soc).toFixed(1)}`)
    .join(' ')
  const powerPath = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${xAt(p.t).toFixed(1)},${yPower(p.kw).toFixed(1)}`)
    .join(' ')

  const durationMin = Math.round(tSpan / 60)

  return (
    <div data-testid="charge-curve">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label="Charge curve"
      >
        {/* Frame */}
        <rect
          x={PAD_L}
          y={PAD_T}
          width={W - PAD_L - PAD_R}
          height={H - PAD_T - PAD_B}
          fill="none"
          className="stroke-slate-200 dark:stroke-slate-700"
          strokeWidth={1}
        />
        {/* Y-grid: 0/25/50/75/100 */}
        {[0, 25, 50, 75, 100].map((soc) => (
          <g key={soc}>
            <line
              x1={PAD_L}
              x2={W - PAD_R}
              y1={ySoc(soc)}
              y2={ySoc(soc)}
              className="stroke-slate-200 dark:stroke-slate-700"
              strokeDasharray="2 3"
              strokeWidth={0.5}
            />
            <text
              x={PAD_L - 4}
              y={ySoc(soc) + 3}
              textAnchor="end"
              className="fill-slate-500 text-[9px]"
            >
              {soc}%
            </text>
          </g>
        ))}
        {/* Right axis labels — power max */}
        <text
          x={W - PAD_R + 4}
          y={yPower(pMax) + 3}
          className="fill-cyan-600 text-[9px] dark:fill-cyan-400"
        >
          {pMax}kW
        </text>
        <text
          x={W - PAD_R + 4}
          y={yPower(0) + 3}
          className="fill-cyan-600 text-[9px] dark:fill-cyan-400"
        >
          0
        </text>
        {/* SoC line — emerald */}
        <path
          d={socPath}
          fill="none"
          className="stroke-emerald-500 dark:stroke-emerald-400"
          strokeWidth={1.75}
        />
        {/* Power line — cyan */}
        <path
          d={powerPath}
          fill="none"
          className="stroke-cyan-500 dark:stroke-cyan-400"
          strokeWidth={1.75}
        />
        {/* X-axis bottom labels */}
        <text
          x={PAD_L}
          y={H - 6}
          className="fill-slate-500 text-[9px]"
        >
          0 min
        </text>
        <text
          x={W - PAD_R}
          y={H - 6}
          textAnchor="end"
          className="fill-slate-500 text-[9px]"
        >
          {durationMin} min
        </text>
      </svg>
      <p className="mt-2 flex gap-3 text-[10px] text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1">
          <span className="inline-block h-1.5 w-3 rounded-sm bg-emerald-500" />
          SoC
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block h-1.5 w-3 rounded-sm bg-cyan-500" />
          Power (kW, peak {pMaxObserved.toFixed(1)})
        </span>
        <span className="tabular-nums">{points.length} samples</span>
      </p>
    </div>
  )
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
  const [editing, setEditing] = useState(false)

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

  const sourceTone: PillTone =
    session.source === 'manual'
      ? 'amber'
      : session.source === 'cariad'
        ? 'purple'
        : 'cyan'
  const sourceLabel =
    session.source === 'manual'
      ? 'Manual'
      : session.source === 'cariad'
        ? 'Cariad'
        : 'Cupra'
  const titleLocation = session.location_name ?? 'Session'
  const subtitleParts = [
    session.date,
    session.location_address ?? null,
  ].filter((p): p is string => Boolean(p))

  return (
    <TooltipProvider>
      <div className="mx-auto max-w-7xl px-6 py-8">
        <PageHeader
          title={`${session.date} · ${titleLocation}`}
          subtitle={subtitleParts.length > 1 ? subtitleParts[1] : null}
          actions={
            <Link
              to="/sessions"
              className="text-xs text-cyan-600 hover:underline dark:text-cyan-300"
            >
              ← All sessions
            </Link>
          }
        />

        {/* Summary strip */}
        <Card variant="hero" className="mb-6 flex flex-wrap items-center gap-4">
          <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
              Energy
            </span>
            <GradientNumber size="lg">
              {session.kwh_added.toFixed(1)}
            </GradientNumber>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              kWh
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
              Cost
            </span>
            <GradientNumber size="lg">
              {fmtPence(session.cost_pence)}
            </GradientNumber>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {session.tariff_p_per_kwh
                ? `${session.tariff_p_per_kwh.toFixed(1)}p / kWh`
                : '—'}
            </span>
          </div>
          <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
              SoC
            </span>
            <GradientNumber size="lg">
              {session.start_soc}→{session.end_soc}
            </GradientNumber>
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {session.end_soc - session.start_soc}% gained
            </span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {session.charge_network && (
              <Pill data-testid="charge-network-badge">
                {session.charge_network}
              </Pill>
            )}
            <Pill tone={sourceTone}>{sourceLabel}</Pill>
            <Tooltip>
              <TooltipTrigger asChild>
                <span
                  className="cursor-help text-xs text-slate-500 underline decoration-dotted underline-offset-4 dark:text-slate-400"
                  data-testid="cost-basis-tile"
                >
                  <Info className="mr-1 inline h-3 w-3" aria-hidden />
                  {COST_BASIS_LABEL[session.cost_basis]}
                </span>
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">
                <p className="font-medium">Cost precedence</p>
                <ol className="mt-1 list-inside list-decimal space-y-0.5 text-[11px]">
                  <li>Total-cost override (sacred)</li>
                  <li>Per-kWh override (sacred)</li>
                  <li>Location free flag</li>
                  <li>Location default rate</li>
                  <li>Home rate setting</li>
                  <li>Otherwise: unknown</li>
                </ol>
              </TooltipContent>
            </Tooltip>
          </div>
        </Card>
        {session.kwh_calculated !== null &&
          Math.abs(session.kwh_calculated - session.kwh_added) >= 0.01 && (
            <p
              className="mb-6 text-xs text-slate-400"
              data-testid="kwh-calc-hint"
            >
              Calculated from SoC delta: {session.kwh_calculated.toFixed(2)} kWh
            </p>
          )}

        <section className="mb-6">
          <CostBreakdown session={session} />
        </section>

        {session.power_curve && session.power_curve.length > 0 && (
          <section className="mb-6">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
              Charge curve
            </h2>
            <Card>
              <ChargeCurve samples={session.power_curve} />
            </Card>
          </section>
        )}

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
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-medium">Edit session</h2>
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 dark:border-slate-700 dark:text-slate-200"
            data-testid="toggle-edit"
          >
            {editing ? 'Cancel' : 'Edit'}
          </button>
        </div>
        {editing && (
          <SessionEditForm
            session={session}
            unit={unit}
            onSaved={(updated) => {
              setSession(updated)
              setEditing(false)
            }}
          />
        )}
        </section>
      </div>
    </TooltipProvider>
  )
}
