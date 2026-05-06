import { Zap } from 'lucide-react'
import type { DashboardCarPanel, DashboardMileageYear } from '@/api/client'
import { Card } from '@/components/ui/Card'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { Pill, type PillTone } from '@/components/ui/Pill'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { useDistanceUnit, type DistanceUnit } from '@/stores/settingsStore'
import { kmToMi } from '@/utils/distance'

interface StateMeta {
  label: string
  tone: PillTone
}

const STATE_META: Record<string, StateMeta> = {
  IDLE: { label: 'Disconnected', tone: 'slate' },
  PLUGGED_IN: { label: 'Plugged in', tone: 'amber' },
  CHARGING: { label: 'Charging', tone: 'cyan' },
  CHARGING_DONE: { label: 'Charge complete', tone: 'green' },
}

function formatRelative(iso: string | null): string {
  if (!iso) return 'never'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return 'never'
  const delta = Date.now() - t
  if (delta < 0) {
    const ahead = Math.round(-delta / 1000)
    if (ahead < 60) return `in ${ahead}s`
    if (ahead < 3600) return `in ${Math.round(ahead / 60)}m`
    return `in ${Math.round(ahead / 3600)}h`
  }
  const seconds = Math.round(delta / 1000)
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`
  return `${Math.round(seconds / 86_400)}d ago`
}

export interface HeroCarCardProps {
  car: DashboardCarPanel
}

export function HeroCarCard({ car }: HeroCarCardProps) {
  const meta = car.last_state ? STATE_META[car.last_state] : null
  const isCharging = car.last_state === 'CHARGING'
  const unit = useDistanceUnit()
  const battery = car.battery_level

  const rangeDisplay =
    car.electric_range_km !== null && car.electric_range_km !== undefined
      ? unit === 'mi'
        ? `${Math.round(kmToMi(car.electric_range_km))} mi`
        : `${car.electric_range_km} km`
      : null

  let chargeRateDisplay: string | null = null
  if (
    isCharging &&
    car.charging_power_kw !== null &&
    car.charging_power_kw !== undefined &&
    car.charging_power_kw > 0 &&
    car.nominal_efficiency_mi_per_kwh
  ) {
    const miPerHour =
      car.charging_power_kw * car.nominal_efficiency_mi_per_kwh
    chargeRateDisplay =
      unit === 'mi'
        ? `${miPerHour.toFixed(1)} mi/h`
        : `${(miPerHour / 0.621371).toFixed(1)} km/h`
  }

  const locationDisplay = car.location_address
    ? car.location_name
      ? `${car.location_name} · ${car.location_address}`
      : car.location_address
    : car.location_name

  return (
    <Card
      variant="hero"
      data-testid={`car-panel-${car.id}`}
      className="flex flex-col gap-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
            {car.make} {car.model}
          </p>
          {meta && (
            <Pill tone={meta.tone} className="mt-1.5" data-testid="state-pill">
              {isCharging && <Zap className="mr-1 h-3 w-3" aria-hidden />}
              {meta.label}
            </Pill>
          )}
        </div>
        {isCharging &&
          car.charging_power_kw !== null &&
          car.charging_power_kw !== undefined &&
          car.charging_power_kw > 0 && (
            <Pill tone="cyan" data-testid="car-charging">
              {car.charging_power_kw.toFixed(1)} kW
              {chargeRateDisplay && (
                <span className="ml-1 opacity-75">· {chargeRateDisplay}</span>
              )}
            </Pill>
          )}
      </div>

      <div className="flex items-baseline gap-2" data-testid="car-soc">
        {battery !== null && battery !== undefined ? (
          <>
            <GradientNumber size="xl">{battery}</GradientNumber>
            <span className="text-2xl font-semibold tabular-nums text-slate-400 dark:text-slate-500">
              %
            </span>
          </>
        ) : (
          <span className="text-3xl font-semibold tabular-nums text-slate-400">
            —
          </span>
        )}
        {car.target_soc !== null && car.target_soc !== undefined && (
          <span className="ml-2 text-xs text-slate-500 dark:text-slate-400">
            target {car.target_soc}%
          </span>
        )}
      </div>

      <ProgressBar
        value={battery ?? 0}
        gradient
        pulsing={isCharging}
        className="h-2.5"
      />

      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
        {rangeDisplay && (
          <div data-testid="car-range">
            <span className="text-slate-400 dark:text-slate-500">Range </span>
            <span className="font-medium tabular-nums text-slate-700 dark:text-slate-200">
              {rangeDisplay}
            </span>
          </div>
        )}
        {locationDisplay && (
          <div className="truncate" data-testid="car-location">
            <span className="text-slate-400 dark:text-slate-500">Where </span>
            <span className="font-medium text-slate-700 dark:text-slate-200">
              {locationDisplay}
            </span>
          </div>
        )}
        <div>
          <span className="text-slate-400 dark:text-slate-500">Seen </span>
          <span className="font-medium text-slate-700 dark:text-slate-200">
            {formatRelative(car.last_connected)}
          </span>
        </div>
        <div>
          <span className="text-slate-400 dark:text-slate-500">Sync </span>
          <span className="font-medium text-slate-700 dark:text-slate-200">
            {formatRelative(car.next_poll_at)}
          </span>
        </div>
      </div>

      {car.mileage_year && (
        <MileageYearTile mileage={car.mileage_year} unit={unit} />
      )}
    </Card>
  )
}

function convertKm(km: number, unit: DistanceUnit): number {
  return unit === 'km' ? km : kmToMi(km)
}

function formatPeriodMonth(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

interface MileageYearTileProps {
  mileage: DashboardMileageYear
  unit: DistanceUnit
}

function MileageYearTile({ mileage, unit }: MileageYearTileProps) {
  const usedKm = Math.max(
    0,
    mileage.current_odometer_km - mileage.opening_odometer_km,
  )
  const used = convertKm(usedKm, unit)
  const target =
    mileage.annual_mileage_target_km !== null
      ? convertKm(mileage.annual_mileage_target_km, unit)
      : null
  const pct = target && target > 0 ? Math.min(100, (used / target) * 100) : null
  const overLimit = target !== null && used > target

  return (
    <div
      className="flex flex-col gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-800/40"
      data-testid="car-mileage-year"
    >
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
          Mileage{' '}
          <span className="normal-case tracking-normal text-slate-400 dark:text-slate-500">
            {formatPeriodMonth(mileage.period_start_date)} →{' '}
            {formatPeriodMonth(mileage.period_end_date)}
          </span>
        </span>
        <span
          className={
            overLimit
              ? 'font-semibold tabular-nums text-amber-600 dark:text-amber-400'
              : 'font-semibold tabular-nums text-slate-700 dark:text-slate-200'
          }
        >
          {Math.round(used).toLocaleString()}
          {target !== null && (
            <>
              {' '}
              <span className="font-normal text-slate-500 dark:text-slate-400">
                / {Math.round(target).toLocaleString()}
              </span>
            </>
          )}{' '}
          {unit}
        </span>
      </div>
      {pct !== null && (
        <ProgressBar
          value={pct}
          gradient={!overLimit}
          className="h-1.5"
          aria-label="Annual mileage used"
        />
      )}
    </div>
  )
}
