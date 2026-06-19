/**
 * Cars browse page (B6 stripped).
 *
 * Shows the car cards (image, specs, mileage display) and the Cupra
 * "discover" flow. Car add/edit/delete and mileage-setup have moved to
 * Admin → CarsManagement.
 */
import { useEffect, useState } from 'react'
import {
  ApiError,
  api,
  type CarPayload,
  type DiscoveredVehicle,
} from '@/api/client'
import { CarImage } from '@/components/cars/CarImage'
import { CarMileageSection } from '@/components/cars/CarMileageSection'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pill } from '@/components/ui/Pill'

export default function CarsPage() {
  const [cars, setCars] = useState<CarPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [discovering, setDiscovering] = useState(false)
  const [discovered, setDiscovered] = useState<DiscoveredVehicle[] | null>(null)

  async function handleDiscover() {
    setDiscovering(true)
    setError(null)
    setDiscovered(null)
    try {
      const list = await api.discoverVehicles()
      setDiscovered(list)
      if (list.length === 0) {
        setError('No vehicles returned by Cupra Connect.')
      }
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : String(err))
    } finally {
      setDiscovering(false)
    }
  }

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
      <PageHeader
        title="Cars"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => void handleDiscover()}
            disabled={discovering}
          >
            {discovering ? 'Discovering…' : 'Discover from Cupra'}
          </Button>
        }
      />

      {discovered && discovered.length > 0 && (
        <Card className="mb-6">
          <p className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
            Vehicles found on your Cupra Connect account
          </p>
          <ul className="mt-2 space-y-2">
            {discovered.map((v) => (
              <li
                key={v.vin}
                className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-700 dark:bg-slate-900"
              >
                <div className="min-w-0 text-sm">
                  <code className="font-mono text-slate-900 dark:text-slate-100">
                    {v.vin}
                  </code>
                  <span className="ml-3 text-slate-500">
                    {v.model ?? 'unknown model'} {v.year ?? ''}
                  </span>
                </div>
                <span className="text-xs text-slate-500">
                  Add via Admin → Cars
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

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
