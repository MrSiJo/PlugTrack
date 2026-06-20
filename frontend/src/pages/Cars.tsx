/**
 * Cars browse page (B6 stripped).
 *
 * Shows the car cards (image, specs, mileage display). Car add/edit/delete
 * and mileage-setup live in Admin → CarsManagement.
 */
import { useEffect, useState } from 'react'
import { ApiError, api, type CarPayload } from '@/api/client'
import { CarImage } from '@/components/cars/CarImage'
import { CarMileageSection } from '@/components/cars/CarMileageSection'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pill } from '@/components/ui/Pill'

export default function CarsPage() {
  const [cars, setCars] = useState<CarPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      const list = await api.getCars()
      setCars(list)
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void reload()
  }, [])

  return (
    <main className="mx-auto max-w-7xl px-4 py-6">
      <PageHeader title="Cars" />

      {error && (
        <div role="alert" className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : cars.length === 0 ? (
        <EmptyState
          title="No cars yet"
          body="Add your first vehicle from the Admin page."
        />
      ) : (
        <ul className="grid gap-4 md:grid-cols-2">
          {cars.map((car) => (
            <li key={car.id}>
              <CarCard car={car} />
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}

function CarCard({ car }: { car: CarPayload }) {
  return (
    <Card variant="hero" className="p-4">
      <div className="flex gap-4">
        <CarImage
          carId={car.id}
          className="aspect-[4/3] h-28 w-44 flex-shrink-0"
          alt={`${car.make} ${car.model}`}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              {car.make} {car.model}
            </h3>
            <div className="flex gap-1">
              {car.active ? (
                <Pill tone="green">Active</Pill>
              ) : (
                <Pill tone="slate">Inactive</Pill>
              )}
            </div>
          </div>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400">
            <div>
              <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">
                Battery
              </dt>
              <dd className="font-medium text-slate-900 dark:text-slate-100">
                {car.battery_kwh} kWh
              </dd>
            </div>
            <div>
              <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">
                Efficiency
              </dt>
              <dd className="font-medium text-slate-900 dark:text-slate-100">
                {car.nominal_efficiency_mi_per_kwh} mi/kWh
              </dd>
            </div>
            <div>
              <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">
                Provider
              </dt>
              <dd className="font-medium text-slate-900 dark:text-slate-100">
                {car.provider}
              </dd>
            </div>
            {car.vin && (
              <div>
                <dt className="text-[10px] uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">
                  VIN
                </dt>
                <dd className="truncate font-mono text-[11px] text-slate-700 dark:text-slate-200">
                  {car.vin}
                </dd>
              </div>
            )}
          </dl>
        </div>
      </div>
      <CarMileageSection carId={car.id} />
    </Card>
  )
}
