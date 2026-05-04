import { useEffect, useState } from 'react'
import {
  ApiError,
  api,
  type CarPayload,
  type CarCreateRequest,
  type DiscoveredVehicle,
} from '@/api/client'

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
    <main className="mx-auto max-w-5xl px-4 py-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">Cars</h1>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void handleDiscover()}
            disabled={discovering}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {discovering ? 'Discovering…' : 'Discover from Cupra'}
          </button>
          <button
            type="button"
            onClick={() => setCreating((v) => !v)}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900"
          >
            {creating ? 'Cancel' : 'Add car manually'}
          </button>
        </div>
      </div>

      {discovered && discovered.length > 0 && (
        <div className="mb-6 rounded border border-blue-300 bg-blue-50 p-4 dark:border-blue-700 dark:bg-blue-900/20">
          <div className="mb-2 text-sm font-medium text-blue-900 dark:text-blue-200">
            Vehicles found on your Cupra Connect account:
          </div>
          <ul className="space-y-2">
            {discovered.map((v) => (
              <li
                key={v.vin}
                className="flex items-center justify-between rounded bg-white px-3 py-2 dark:bg-slate-800"
              >
                <div className="text-sm">
                  <code className="font-mono text-slate-900 dark:text-slate-100">{v.vin}</code>
                  <span className="ml-3 text-slate-500">
                    {v.model ?? 'unknown model'} {v.year ?? ''}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => applyDiscovered(v)}
                  className="rounded bg-slate-900 px-2 py-1 text-xs text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900"
                >
                  Use this vehicle
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && (
        <div role="alert" className="mb-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {creating && (
        <form
          onSubmit={handleCreate}
          className="mb-6 rounded border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900"
        >
          <CarFields draft={draft} setDraft={setDraft} />
          <div className="mt-3 flex gap-2">
            <button
              type="submit"
              disabled={busy}
              className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
            >
              {busy ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : cars.length === 0 ? (
        <p className="text-sm text-slate-500">
          No cars yet. Click <strong>Add car</strong> to register your first vehicle.
        </p>
      ) : (
        <ul className="space-y-3">
          {cars.map((car) => (
            <li
              key={car.id}
              className="rounded border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900"
            >
              {editingId === car.id ? (
                <form onSubmit={(e) => handleSave(car.id, e)}>
                  <CarFields draft={editDraft} setDraft={setEditDraft} />
                  <div className="mt-3 flex gap-2">
                    <button
                      type="submit"
                      disabled={busy}
                      className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingId(null)}
                      className="rounded px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                    >
                      Cancel
                    </button>
                  </div>
                </form>
              ) : (
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="text-base font-semibold text-slate-900 dark:text-slate-100">
                      {car.make} {car.model}
                    </div>
                    <dl className="mt-1 grid grid-cols-2 gap-x-6 gap-y-0.5 text-xs text-slate-600 dark:text-slate-400">
                      <div>
                        <dt className="inline font-medium">Battery: </dt>
                        <dd className="inline">{car.battery_kwh} kWh</dd>
                      </div>
                      <div>
                        <dt className="inline font-medium">Nominal: </dt>
                        <dd className="inline">{car.nominal_efficiency_mi_per_kwh} mi/kWh</dd>
                      </div>
                      <div>
                        <dt className="inline font-medium">Provider: </dt>
                        <dd className="inline">{car.provider}</dd>
                      </div>
                      <div>
                        <dt className="inline font-medium">Vehicle ID: </dt>
                        <dd className="inline">{car.provider_vehicle_id ?? '—'}</dd>
                      </div>
                      {car.vin && (
                        <div className="col-span-2">
                          <dt className="inline font-medium">VIN: </dt>
                          <dd className="inline">{car.vin}</dd>
                        </div>
                      )}
                      <div>
                        <dt className="inline font-medium">Active: </dt>
                        <dd className="inline">{car.active ? 'yes' : 'no'}</dd>
                      </div>
                    </dl>
                  </div>
                  <div className="flex flex-shrink-0 gap-2">
                    <button
                      type="button"
                      onClick={() => startEdit(car)}
                      className="rounded px-3 py-1 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDelete(car.id)}
                      className="rounded px-3 py-1 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}

interface CarFieldsProps {
  draft: CarCreateRequest
  setDraft: (next: CarCreateRequest) => void
}

function CarFields({ draft, setDraft }: CarFieldsProps) {
  const fieldClass =
    'mt-1 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100'
  const labelClass = 'block text-xs font-medium text-slate-700 dark:text-slate-300'

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <label className={labelClass}>
        Make
        <input
          required
          value={draft.make}
          onChange={(e) => setDraft({ ...draft, make: e.target.value })}
          className={fieldClass}
        />
      </label>
      <label className={labelClass}>
        Model
        <input
          required
          value={draft.model}
          onChange={(e) => setDraft({ ...draft, model: e.target.value })}
          className={fieldClass}
        />
      </label>
      <label className={labelClass}>
        Battery (kWh) <span className="text-red-600">*</span>
        <input
          required
          type="number"
          step="0.1"
          min="0.1"
          placeholder="e.g. 58 for Cupra Born"
          value={Number.isFinite(draft.battery_kwh) ? draft.battery_kwh : ''}
          onChange={(e) =>
            setDraft({
              ...draft,
              battery_kwh: e.target.value === '' ? NaN : Number(e.target.value),
            })
          }
          className={fieldClass}
        />
        <span className="mt-0.5 block text-[11px] font-normal text-slate-500">
          Cupra Connect doesn't expose battery capacity — enter manually.
        </span>
      </label>
      <label className={labelClass}>
        Nominal efficiency (mi/kWh) <span className="text-red-600">*</span>
        <input
          required
          type="number"
          step="0.1"
          min="0.1"
          placeholder="e.g. 3.5 for Cupra Born"
          value={
            Number.isFinite(draft.nominal_efficiency_mi_per_kwh)
              ? draft.nominal_efficiency_mi_per_kwh
              : ''
          }
          onChange={(e) =>
            setDraft({
              ...draft,
              nominal_efficiency_mi_per_kwh:
                e.target.value === '' ? NaN : Number(e.target.value),
            })
          }
          className={fieldClass}
        />
        <span className="mt-0.5 block text-[11px] font-normal text-slate-500">
          Real-world miles per kWh. Used for range estimates.
        </span>
      </label>
      <label className={labelClass}>
        Provider
        <select
          value={draft.provider ?? 'cupra_connect'}
          onChange={(e) => setDraft({ ...draft, provider: e.target.value })}
          className={fieldClass}
        >
          <option value="cupra_connect">Cupra Connect</option>
          <option value="manual">Manual only</option>
        </select>
      </label>
      <label className={labelClass}>
        Provider vehicle ID (VIN-like handle from your account)
        <input
          value={draft.provider_vehicle_id ?? ''}
          onChange={(e) => setDraft({ ...draft, provider_vehicle_id: e.target.value })}
          className={fieldClass}
          placeholder="optional, required for Cupra Connect sync"
        />
      </label>
      <label className={`${labelClass} sm:col-span-2`}>
        VIN (optional, encrypted at rest)
        <input
          value={draft.vin ?? ''}
          onChange={(e) => setDraft({ ...draft, vin: e.target.value })}
          className={fieldClass}
        />
      </label>
      <label className="inline-flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
        <input
          type="checkbox"
          checked={draft.active ?? true}
          onChange={(e) => setDraft({ ...draft, active: e.target.checked })}
        />
        Active (synced + visible in dashboards)
      </label>
    </div>
  )
}
