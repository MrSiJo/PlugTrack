import { useEffect, useState } from 'react'
import {
  ApiError,
  api,
  type CarPayload,
  type CarCreateRequest,
  type DiscoveredVehicle,
} from '@/api/client'
import { CarFields } from '@/components/cars/CarFields'
import { CarImage } from '@/components/cars/CarImage'
import { CarMileageSection } from '@/components/cars/CarMileageSection'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { PageHeader } from '@/components/ui/PageHeader'
import { Pill } from '@/components/ui/Pill'

// `battery_kwh` and `nominal_efficiency_mi_per_kwh` are typed `number` on
// the API but rendered with `value={... || ''}` so the input starts blank;
// HTML5 `required` then prevents an empty submit before the backend's
// `gt=0` validator can reject it.
const EMPTY_NEW: CarCreateRequest = {
  make: '',
  model: '',
  vin: '',
  battery_kwh: NaN,
  nominal_efficiency_mi_per_kwh: NaN,
  provider: 'cupra_connect',
  provider_vehicle_id: '',
  active: true,
}

export default function CarsPage() {
  const [cars, setCars] = useState<CarPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState<CarCreateRequest>(EMPTY_NEW)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState<CarCreateRequest>(EMPTY_NEW)
  const [busy, setBusy] = useState(false)
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

  function applyDiscovered(v: DiscoveredVehicle) {
    setCreating(true)
    setDraft({
      ...EMPTY_NEW,
      make: 'Cupra',
      model: v.model ?? '',
      vin: v.vin,
      provider: 'cupra_connect',
      provider_vehicle_id: v.vin,
    })
    setDiscovered(null)
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

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.createCar({
        ...draft,
        vin: draft.vin?.trim() || null,
        provider_vehicle_id: draft.provider_vehicle_id?.trim() || null,
      })
      setDraft(EMPTY_NEW)
      setCreating(false)
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function handleSave(id: number, e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.updateCar(id, {
        ...editDraft,
        vin: editDraft.vin?.trim() || null,
        provider_vehicle_id: editDraft.provider_vehicle_id?.trim() || null,
      })
      setEditingId(null)
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm('Delete this car? Charging sessions will remain but lose their car link.')) {
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.deleteCar(id)
      await reload()
    } catch (err) {
      setError(err instanceof ApiError ? `${err.status}: ${err.message}` : String(err))
    } finally {
      setBusy(false)
    }
  }

  function startEdit(car: CarPayload) {
    setEditingId(car.id)
    setEditDraft({
      make: car.make,
      model: car.model,
      vin: car.vin ?? '',
      battery_kwh: car.battery_kwh,
      nominal_efficiency_mi_per_kwh: car.nominal_efficiency_mi_per_kwh,
      provider: car.provider,
      provider_vehicle_id: car.provider_vehicle_id ?? '',
      active: car.active,
    })
  }

  return (
    <main className="mx-auto max-w-7xl px-4 py-6">
      <PageHeader
        title="Cars"
        actions={
          <>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleDiscover()}
              disabled={discovering}
            >
              {discovering ? 'Discovering…' : 'Discover from Cupra'}
            </Button>
            <Button size="sm" onClick={() => setCreating((v) => !v)}>
              {creating ? 'Cancel' : 'Add car manually'}
            </Button>
          </>
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
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => applyDiscovered(v)}
                >
                  Use this vehicle
                </Button>
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

      {creating && (
        <Card variant="hero" className="mb-6">
          <form onSubmit={handleCreate}>
            <CarFields draft={draft} setDraft={setDraft} />
            <div className="mt-4 flex gap-2">
              <Button type="submit" size="sm" disabled={busy}>
                {busy ? 'Creating…' : 'Create'}
              </Button>
            </div>
          </form>
        </Card>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : cars.length === 0 ? (
        <EmptyState
          title="No cars yet"
          body="Add your first vehicle manually, or use Discover from Cupra to pull one off your Cupra Connect account."
        />
      ) : (
        <ul className="grid gap-4 md:grid-cols-2">
          {cars.map((car) => (
            <li key={car.id}>
              {editingId === car.id ? (
                <Card variant="hero">
                  <form onSubmit={(e) => handleSave(car.id, e)}>
                    <CarFields draft={editDraft} setDraft={setEditDraft} />
                    <div className="mt-4 flex gap-2">
                      <Button type="submit" size="sm" disabled={busy}>
                        Save
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        onClick={() => setEditingId(null)}
                      >
                        Cancel
                      </Button>
                    </div>
                  </form>
                </Card>
              ) : (
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
                      <div className="mt-3 flex gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => startEdit(car)}
                        >
                          Edit
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() => void handleDelete(car.id)}
                          className="text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
                        >
                          Delete
                        </Button>
                      </div>
                    </div>
                  </div>
                  <CarMileageSection carId={car.id} />
                </Card>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}

