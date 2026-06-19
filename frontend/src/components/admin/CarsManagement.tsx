/**
 * CarsManagement — relocated from Cars.tsx (Phase B6).
 *
 * Handles:
 *   - List cars
 *   - Add car (CarFields + api.createCar)
 *   - Edit car — calls api.revealCarVin(car.id) to seed the full VIN BEFORE
 *     rendering CarFields, then api.updateCar
 *   - Delete car (confirm + api.deleteCar)
 *   - Mileage-tracking setup (CarMileageSection per car)
 *
 * Does NOT handle:
 *   - Car display/browse cards, the Cupra "discover" flow, mileage display
 *     — those stay in Cars.tsx.
 */
import { useEffect, useRef, useState } from 'react'
import {
  ApiError,
  api,
  type CarPayload,
  type CarCreateRequest,
} from '@/api/client'
import { CarFields } from '@/components/cars/CarFields'
import { CarMileageSection } from '@/components/cars/CarMileageSection'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/Card'

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

export function CarsManagement() {
  const [cars, setCars] = useState<CarPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState<CarCreateRequest>(EMPTY_NEW)
  const [editingId, setEditingId] = useState<number | null>(null)
  const editingIdRef = useRef<number | null>(null)
  const [editDraft, setEditDraft] = useState<CarCreateRequest>(EMPTY_NEW)
  const [busy, setBusy] = useState(false)

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

  // Keep editingIdRef in sync so async closures (startEdit) can check whether
  // the active edit has changed since the VIN reveal was dispatched.
  useEffect(() => {
    editingIdRef.current = editingId
  }, [editingId])

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

  /**
   * Start editing a car: call revealCarVin first so the edit form shows the
   * full plaintext VIN (the list payload shows a masked value like "········XYZ12").
   */
  async function startEdit(car: CarPayload) {
    setEditingId(car.id)
    // Seed with masked VIN initially, then replace once reveal completes.
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
    try {
      const { vin } = await api.revealCarVin(car.id)
      // Guard against cross-car VIN leak: only apply if this car is still the
      // active edit. editingIdRef (not the closure-captured editingId, which
      // is stale) reflects any edit change that happened while the await was
      // in flight (e.g. user clicked Edit on a different car, or clicked Cancel).
      setEditDraft((prev) =>
        editingIdRef.current === car.id ? { ...prev, vin: vin ?? '' } : prev,
      )
    } catch {
      // Clear VIN on reveal failure so the masked sentinel can't be saved back.
      // The user can type the correct VIN manually.
      setEditDraft((prev) =>
        editingIdRef.current === car.id ? { ...prev, vin: '' } : prev,
      )
    }
  }

  return (
    <div data-testid="cars-management">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-slate-600 dark:text-slate-400">
          Add, edit, or delete cars. To browse charges and mileage history, visit the{' '}
          <a href="/cars" className="text-indigo-600 underline dark:text-indigo-400">
            Cars page
          </a>
          .
        </p>
        <Button
          size="sm"
          onClick={() => {
            setCreating((v) => !v)
            setDraft(EMPTY_NEW)
          }}
        >
          {creating ? 'Cancel' : 'Add car'}
        </Button>
      </div>

      {error && (
        <div role="alert" className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {creating && (
        <Card variant="hero" className="mb-6">
          <form onSubmit={(e) => void handleCreate(e)}>
            <CarFields draft={draft} setDraft={setDraft} />
            <div className="mt-4 flex gap-2">
              <Button type="submit" size="sm" disabled={busy}>
                {busy ? 'Creating…' : 'Create'}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setCreating(false)}
              >
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}

      {loading && <p className="text-sm text-slate-500">Loading…</p>}

      {!loading && cars.length === 0 && !creating && (
        <p className="text-sm text-slate-500">No cars yet.</p>
      )}

      <ul className="space-y-4">
        {cars.map((car) => (
          <li key={car.id} data-testid="admin-car-row" data-car-id={car.id}>
            {editingId === car.id ? (
              <Card variant="hero">
                <form onSubmit={(e) => void handleSave(car.id, e)}>
                  <CarFields draft={editDraft} setDraft={setEditDraft} />
                  <div className="mt-4 flex gap-2">
                    <Button type="submit" size="sm" disabled={busy}>
                      {busy ? 'Saving…' : 'Save'}
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
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                      {car.make} {car.model}
                    </p>
                    {car.vin && (
                      <p className="mt-0.5 font-mono text-[11px] text-slate-500 dark:text-slate-400">
                        {car.vin}
                      </p>
                    )}
                    <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                      {car.battery_kwh} kWh · {car.provider}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => void startEdit(car)}
                      data-testid={`admin-edit-car-${car.id}`}
                    >
                      Edit
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => void handleDelete(car.id)}
                      className="text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40"
                      data-testid={`admin-delete-car-${car.id}`}
                    >
                      Delete
                    </Button>
                  </div>
                </div>
                <CarMileageSection carId={car.id} />
              </Card>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
