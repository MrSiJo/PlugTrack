/**
 * Session detail page (redesigned).
 *
 * Renders:
 * - PageHeader (date · location, address subtitle).
 * - Hero summary strip: Energy / Cost / SoC / Duration as gradient
 *   numerals + source pill + cost-basis tooltip.
 * - <ChargeCurve /> when `power_curve` is non-empty (cyan power line,
 *   emerald SoC line). Updated live by the sync worker.
 * - Petrol comparison KPI tiles when metrics are available.
 * - Location section: small map thumbnail + address + edit link.
 * - Edit form, gated behind an "Edit" toggle.
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
import { LocationMiniMap } from '@/components/locations/LocationMiniMap'
import { Card } from '@/components/ui/Card'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pill, type PillTone } from '@/components/ui/Pill'
import { StatTile } from '@/components/ui/StatTile'
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

interface ChargeMechanicsProps {
  metrics: SessionMetricsPayload
  unit: 'mi' | 'km'
  kwhAdded: number
  kwhCalculated: number | null
}

function fmtDuration(minutes: number | null): string {
  if (minutes === null) return '—'
  if (minutes < 60) return `${minutes} min`
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return m === 0 ? `${h}h` : `${h}h ${m}m`
}

function fmtKw(v: number | null): string {
  return v === null ? '—' : `${v.toFixed(1)} kW`
}

function fmtRange(miles: number | null, unit: 'mi' | 'km'): string {
  if (miles === null) return '—'
  return unit === 'mi'
    ? `${miles.toFixed(0)} mi`
    : `${(miles * 1.609344).toFixed(0)} km`
}

function ChargeMechanics({
  metrics,
  unit,
  kwhAdded,
  kwhCalculated,
}: ChargeMechanicsProps) {
  // Suppress the whole section if every field is None (e.g. a manual
  // session with only SoC + kWh + cost — nothing useful to display).
  const hasAny =
    metrics.range_added_miles !== null
    || metrics.duration_minutes !== null
    || metrics.average_power_kw !== null
    || metrics.peak_power_kw !== null
    || metrics.efficiency_percent !== null
  if (!hasAny) return null

  return (
    <section className="mb-6" data-testid="charge-mechanics">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
        Charge mechanics
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Range added"
          value={
            <span data-testid="metric-range-added">
              {fmtRange(metrics.range_added_miles, unit)}
            </span>
          }
        />
        <StatTile
          label="Duration"
          value={
            <span data-testid="metric-duration">
              {fmtDuration(metrics.duration_minutes)}
            </span>
          }
        />
        <StatTile
          label="Avg power"
          value={
            <span data-testid="metric-avg-power">
              {fmtKw(metrics.average_power_kw)}
            </span>
          }
        />
        <StatTile
          label="Peak power"
          value={
            <span data-testid="metric-peak-power">
              {fmtKw(metrics.peak_power_kw)}
            </span>
          }
        />
      </div>
      {metrics.efficiency_percent !== null && (
        <p
          className="mt-3 text-[11px] text-slate-500 dark:text-slate-400"
          data-testid="metric-efficiency"
        >
          Energy efficiency: <strong>{metrics.efficiency_percent.toFixed(1)}%</strong>
          {kwhCalculated !== null && (
            <>
              {' '}(charger {kwhAdded.toFixed(1)} kWh → pack{' '}
              {kwhCalculated.toFixed(1)} kWh)
            </>
          )}
        </p>
      )}
    </section>
  )
}

interface ChargeContextProps {
  session: ChargingSessionPayload
}

const CHARGING_MODE_LABEL: Record<string, string> = {
  manual: 'Manual',
  timer: 'Timer',
  profile: 'Profile',
}

const CHARGING_TYPE_LABEL: Record<string, string> = {
  ac: 'AC',
  dc: 'DC',
}

function fmtMaxCurrent(v: string | null): string {
  if (v === null) return '—'
  if (v === 'maximum') return 'Maximum'
  if (v === 'reduced') return 'Reduced'
  return v
}

function ChargeContext({ session }: ChargeContextProps) {
  const modeKnown =
    session.charging_mode !== 'unknown' && Boolean(session.charging_mode)
  const typeKnown =
    session.charging_type !== 'unknown' && Boolean(session.charging_type)
  const hasAny =
    modeKnown
    || typeKnown
    || session.battery_care !== null
    || session.max_charge_current !== null
  if (!hasAny) return null

  const modeLabel = modeKnown
    ? (CHARGING_MODE_LABEL[session.charging_mode] ?? session.charging_mode)
    : '—'
  const typeLabel = typeKnown
    ? (CHARGING_TYPE_LABEL[session.charging_type] ?? session.charging_type)
    : '—'
  const careLabel =
    session.battery_care === null
      ? '—'
      : session.battery_care
        ? 'On'
        : 'Off'

  return (
    <section className="mb-6" data-testid="charge-context">
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
        Charge context
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Mode"
          value={<span data-testid="ctx-mode">{modeLabel}</span>}
        />
        <StatTile
          label="Type"
          value={<span data-testid="ctx-type">{typeLabel}</span>}
        />
        <StatTile
          label="Battery care"
          value={<span data-testid="ctx-battery-care">{careLabel}</span>}
        />
        <StatTile
          label="Max current"
          value={
            <span data-testid="ctx-max-current">
              {fmtMaxCurrent(session.max_charge_current)}
            </span>
          }
        />
      </div>
    </section>
  )
}

interface PetrolComparisonProps {
  metrics: SessionMetricsPayload
  unit: 'mi' | 'km'
}

function PetrolComparison({ metrics, unit }: PetrolComparisonProps) {
  const settingsConfigured =
    metrics.petrol_price_p_per_litre !== null && metrics.petrol_mpg !== null
  // miles_since_previous is the energy-estimated range (drives the Distance tile).
  const hasEstimatedMiles =
    metrics.miles_since_previous !== null && metrics.miles_since_previous > 0
  const isEstimated = metrics.comparison_basis === 'estimated'
  // `~` prefix on estimate-derived figures (energy × efficiency).
  const approx = isEstimated ? '~' : ''

  // Formatted energy-estimated distance for the Distance tile.
  const estimatedDistanceDisplay =
    metrics.miles_since_previous === null
      ? '—'
      : unit === 'mi'
        ? `${metrics.miles_since_previous.toFixed(0)} mi`
        : `${(metrics.miles_since_previous * 1.609344).toFixed(0)} km`

  // Formatted genuine odometer-measured distance (informational only).
  const measuredDistanceDisplay =
    metrics.measured_miles_since_previous === null
      ? null
      : unit === 'mi'
        ? `${metrics.measured_miles_since_previous.toFixed(0)} mi`
        : `${(metrics.measured_miles_since_previous * 1.609344).toFixed(0)} km`

  const savings = metrics.savings_vs_petrol_p
  const savingsPositive = savings !== null && savings > 0

  // Arrow + colour savings hero — no +/- sign.
  const renderSavingsHero = () => {
    if (savings === null) {
      return (
        <span
          className="text-3xl font-bold tabular-nums tracking-tight text-slate-400"
          data-testid="metric-savings"
        >
          —
        </span>
      )
    }
    const cheaper = savings > 0
    const magnitude = Math.abs(savings)
    const arrow = cheaper ? '↓' : '↑'
    const colourCls = cheaper
      ? 'text-emerald-600 dark:text-emerald-400'
      : 'text-rose-600 dark:text-rose-400'
    return (
      <span
        className={`text-3xl font-bold tabular-nums tracking-tight ${colourCls}`}
        data-testid="metric-savings"
      >
        {approx}{arrow} {fmtPence(magnitude)}
      </span>
    )
  }

  const renderEmpty = (body: string, testid?: string) => (
    <Card className="p-4 text-sm" data-testid={testid ?? 'petrol-comparison'}>
      <p className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
        Petrol comparison
      </p>
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        {body}
      </p>
    </Card>
  )

  if (!settingsConfigured) {
    return renderEmpty(
      'Set "Petrol price (p/litre)" and "Petrol MPG" in Settings to enable this comparison.',
    )
  }

  if (!hasEstimatedMiles) {
    return renderEmpty('Needs energy or odometer data to compare.')
  }

  return (
    <div data-testid="petrol-comparison">
      <div className="mb-3 flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
            Petrol comparison
          </h2>
          {isEstimated && (
            <span
              className="cursor-help rounded-full bg-amber-100 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
              data-testid="estimated-badge"
              title="Estimated from this charge's energy × your car's real-world efficiency (from its odometer history, or the configured nominal if none yet)."
            >
              Estimated
            </span>
          )}
        </div>
        <span className="text-[10px] text-slate-400 dark:text-slate-500">
          {metrics.petrol_price_p_per_litre}p/L petrol @ {metrics.petrol_mpg}{' '}
          MPG
        </span>
      </div>

      {/* Hero "you saved" card. */}
      <Card variant="hero" className="mb-3 flex items-baseline gap-3 p-4">
        <div className="flex flex-col">
          <span className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
            {savingsPositive ? 'Saved vs petrol' : 'Spent over petrol'}
          </span>
          {renderSavingsHero()}
          <span className="text-xs text-slate-500 dark:text-slate-400">
            over ~{estimatedDistanceDisplay} of estimated range
          </span>
        </div>
      </Card>

      {/* KPI tile row */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Estimated range"
          value={
            <span data-testid="metric-miles">{`${approx}${estimatedDistanceDisplay}`}</span>
          }
        />
        <StatTile
          label="EV cost / mile"
          value={
            <span data-testid="metric-cost-per-mile">
              {`${approx}${fmtPencePerMile(metrics.cost_per_mile_p)}`}
            </span>
          }
        />
        <StatTile
          label="Petrol cost / mile"
          value={
            <span data-testid="metric-petrol-ppm">
              {fmtPencePerMile(metrics.petrol_ppm)}
            </span>
          }
        />
        <StatTile
          label="Petrol equivalent"
          value={
            <span data-testid="metric-petrol-cost">
              {`${approx}${fmtPence(metrics.petrol_equivalent_cost_p)}`}
            </span>
          }
        />
      </div>

      {/* Odometer-measured distance — informational only, distinct from the
          energy-estimated range that feeds savings. */}
      {measuredDistanceDisplay !== null && (
        <p
          className="mt-3 text-[11px] text-slate-500 dark:text-slate-400"
          data-testid="measured-distance-info"
        >
          Odometer reading: {measuredDistanceDisplay} driven since last
          odometer reading.
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
  const [batteryCare, setBatteryCare] = useState<boolean>(
    session.battery_care ?? false,
  )
  const [maxChargeCurrent, setMaxChargeCurrent] = useState<string>(
    session.max_charge_current ?? '',
  )
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
        battery_care: batteryCare,
        max_charge_current:
          maxChargeCurrent.trim() === '' ? null : maxChargeCurrent,
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
          <span className="text-xs uppercase text-slate-500">Max current</span>
          <select
            className={inputCls}
            value={maxChargeCurrent}
            onChange={(e) => setMaxChargeCurrent(e.target.value)}
            data-testid="edit-max-charge-current"
          >
            <option value="">—</option>
            <option value="maximum">Maximum</option>
            <option value="reduced">Reduced</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={batteryCare}
            onChange={(e) => setBatteryCare(e.target.checked)}
            data-testid="edit-battery-care"
          />
          <span className="text-xs uppercase text-slate-500">Battery care</span>
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

  const durationDisplay = (() => {
    const start = session.charge_start_at
      ? Date.parse(session.charge_start_at)
      : null
    const end = session.charge_end_at
      ? Date.parse(session.charge_end_at)
      : null
    if (start === null || end === null || Number.isNaN(start) || Number.isNaN(end)) {
      return null
    }
    const totalMin = Math.max(0, Math.round((end - start) / 60_000))
    const h = Math.floor(totalMin / 60)
    const m = totalMin % 60
    if (h === 0) return { value: `${m}`, suffix: 'min' }
    return { value: `${h}h ${String(m).padStart(2, '0')}`, suffix: 'h m' }
  })()

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
          {durationDisplay && (
            <div className="flex flex-col" data-testid="session-duration">
              <span className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
                Duration
              </span>
              <GradientNumber size="lg">{durationDisplay.value}</GradientNumber>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {durationDisplay.suffix}
              </span>
            </div>
          )}
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
        <ChargeMechanics
          metrics={session.metrics}
          unit={unit}
          kwhAdded={session.kwh_added}
          kwhCalculated={session.kwh_calculated ?? null}
        />
      )}

      <ChargeContext session={session} />

      {session.metrics && (
        <section className="mb-6">
          <PetrolComparison
            metrics={session.metrics}
            unit={unit}
          />
        </section>
      )}

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
          Location
        </h2>
        {session.location_id === null ? (
          <Card className="text-sm text-slate-500">No location attached.</Card>
        ) : session.location_name ? (
          <div
            className="grid gap-3 md:grid-cols-[260px_1fr]"
            data-testid="location-summary"
          >
            {session.location_lat !== null && session.location_lng !== null ? (
              <Link
                to="/locations"
                aria-label="Open this location on the Locations page"
              >
                <LocationMiniMap
                  lat={session.location_lat}
                  lng={session.location_lng}
                  height={140}
                />
              </Link>
            ) : (
              <Card className="flex items-center justify-center text-xs text-slate-500">
                No coordinates
              </Card>
            )}
            <Card className="flex flex-col gap-1">
              <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                {session.location_name}
              </p>
              {session.location_address && (
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  {session.location_address}
                </p>
              )}
              <Link
                to="/locations"
                className="mt-2 text-xs text-cyan-600 hover:underline dark:text-cyan-300"
              >
                Edit on the Locations page →
              </Link>
            </Card>
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
