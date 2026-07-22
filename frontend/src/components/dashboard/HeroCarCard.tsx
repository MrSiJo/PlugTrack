import type { DashboardCarPanel, DashboardEved, DashboardMileageYear } from '@/api/client'
import { Card } from '@/components/ui/Card'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { ProgressBar } from '@/components/ui/ProgressBar'
import { useDistanceUnit, type DistanceUnit } from '@/stores/settingsStore'
import { formatCurrency } from '@/utils/currency'
import { kmToMi } from '@/utils/distance'

/**
 * Snapshot of the car's most recent charging session, derived on the
 * dashboard from the `recent_sessions` payload. Drives the battery readout
 * ("after last charge") and the compact most-recent-charge summary.
 */
export interface LatestCharge {
  date: string
  end_soc: number | null
  kwh_added: number
  cost_pence: number | null
  location_name: string | null
}

function formatChargeDate(iso: string): string {
  // ISO date (yyyy-mm-dd…). Render as a short "27 May" style label.
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  })
}

export interface HeroCarCardProps {
  car: DashboardCarPanel
  /** Most recent session for this car, or null when none exists. */
  latestCharge?: LatestCharge | null
  /** ISO 4217 currency code for the last-charge cost (defaults to GBP). */
  currency?: string
}

export function HeroCarCard({
  car,
  latestCharge = null,
  currency = 'GBP',
}: HeroCarCardProps) {
  const unit = useDistanceUnit()

  // Battery readout is a snapshot taken "after last charge", not a live sync
  // value. The backend already populates `battery_level` from the most recent
  // session's end_soc; fall back to the passed latest-charge end_soc. Hidden
  // when there is no session at all.
  const battery =
    car.battery_level !== null && car.battery_level !== undefined
      ? car.battery_level
      : latestCharge && latestCharge.end_soc !== null
        ? latestCharge.end_soc
        : null

  const summaryLocation =
    latestCharge?.location_name && latestCharge.location_name.trim() !== ''
      ? latestCharge.location_name
      : null

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
        </div>
      </div>

      {battery !== null && latestCharge && (
        <>
          <div className="flex items-baseline gap-2" data-testid="car-soc">
            <GradientNumber size="xl">{battery}</GradientNumber>
            <span className="text-2xl font-semibold tabular-nums text-slate-400 dark:text-slate-500">
              %
            </span>
            <span
              className="ml-2 text-xs text-slate-500 dark:text-slate-400"
              data-testid="car-battery-label"
            >
              after last charge · {formatChargeDate(latestCharge.date)}
            </span>
          </div>

          <ProgressBar value={battery} gradient className="h-2.5" />
        </>
      )}

      {latestCharge && (
        <div
          className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400"
          data-testid="car-last-charge"
        >
          <span>
            <span className="text-slate-400 dark:text-slate-500">Added </span>
            <span className="font-medium tabular-nums text-slate-700 dark:text-slate-200">
              {latestCharge.kwh_added.toFixed(1)} kWh
            </span>
          </span>
          <span>
            <span className="text-slate-400 dark:text-slate-500">Cost </span>
            <span className="font-medium tabular-nums text-slate-700 dark:text-slate-200">
              {formatCurrency(latestCharge.cost_pence, currency)}
            </span>
          </span>
          {summaryLocation && (
            <span className="truncate">
              <span className="text-slate-400 dark:text-slate-500">At </span>
              <span className="font-medium text-slate-700 dark:text-slate-200">
                {summaryLocation}
              </span>
            </span>
          )}
        </div>
      )}

      {car.mileage_year && (
        <MileageYearTile mileage={car.mileage_year} unit={unit} />
      )}

      {car.eved && <EvedTile eved={car.eved} currency={currency} />}
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

function formatRenewal(mmdd: string): string {
  const parts = mmdd.split('-')
  const month = Number(parts[0])
  const day = Number(parts[1])
  if (!month || !day) return mmdd
  const d = new Date(Date.UTC(2000, month - 1, day))
  return d.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  })
}

interface EvedTileProps {
  eved: DashboardEved
  currency: string
}

function EvedTile({ eved, currency }: EvedTileProps) {
  return (
    <div
      className="flex flex-col gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-700 dark:bg-slate-800/40"
      data-testid="car-eved"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
          eVED{' '}
          <span className="normal-case tracking-normal text-slate-400 dark:text-slate-500">
            est. from Apr 2028
          </span>
        </span>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
        <span>
          <span className="text-slate-400 dark:text-slate-500">So far </span>
          <span className="font-medium tabular-nums text-slate-700 dark:text-slate-200">
            {formatCurrency(eved.running_pence, currency)}
          </span>
        </span>
        <span>
          <span className="text-slate-400 dark:text-slate-500">Projected </span>
          <span className="font-medium tabular-nums text-slate-700 dark:text-slate-200">
            {formatCurrency(eved.projected_pence, currency)}/yr
          </span>
        </span>
      </div>
      <div className="text-xs">
        <span className="text-slate-400 dark:text-slate-500">
          + {formatCurrency(eved.ved_pence, currency)} VED →{' '}
        </span>
        <span className="font-semibold tabular-nums text-slate-700 dark:text-slate-200">
          ≈ {formatCurrency(eved.total_due_pence, currency)}
        </span>
        <span className="text-slate-400 dark:text-slate-500">
          {' '}due {formatRenewal(eved.renewal_date)}
        </span>
      </div>
      {eved.low_confidence && (
        <p className="text-[10px] text-slate-400 dark:text-slate-500">
          Estimate settles as the year progresses.
        </p>
      )}
    </div>
  )
}
