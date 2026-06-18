import { useEffect, useState } from 'react'
import {
  ApiError,
  api,
  type LocationPayload,
  type LocationUpdateRequest,
} from '@/api/client'

interface Toast {
  kind: 'success' | 'error'
  message: string
}

export interface LocationEditFormProps {
  location: LocationPayload
  onSaved: () => void | Promise<void>
  onToast?: (t: Toast) => void
  showRadius?: boolean
  showRecalculate?: boolean
}

/**
 * Shared, non-destructive location edit form. Used by the Locations admin
 * page (with radius) and the location detail page. Forward-going PUT only;
 * the explicit "Recalculate past costs" button is the sole way to re-rate
 * history. Delete / merge / create live in the admin surface, not here.
 */
export function LocationEditForm({
  location,
  onSaved,
  onToast,
  showRadius = false,
  showRecalculate = true,
}: LocationEditFormProps) {
  const id = location.id
  const [name, setName] = useState<string>(location.name ?? '')
  const [isHome, setIsHome] = useState<boolean>(location.is_home)
  const [isFree, setIsFree] = useState<boolean>(location.is_free)
  const [defaultRate, setDefaultRate] = useState<string>(
    location.default_cost_per_kwh_p === null
      ? ''
      : String(location.default_cost_per_kwh_p),
  )
  const [defaultNetwork, setDefaultNetwork] = useState<string>(
    location.default_charge_network ?? '',
  )
  const [radiusM, setRadiusM] = useState<string>(String(location.radius_m))
  const [busy, setBusy] = useState(false)

  // Re-sync local state when the location prop changes (parent refresh).
  useEffect(() => {
    setName(location.name ?? '')
    setIsHome(location.is_home)
    setIsFree(location.is_free)
    setDefaultRate(
      location.default_cost_per_kwh_p === null
        ? ''
        : String(location.default_cost_per_kwh_p),
    )
    setDefaultNetwork(location.default_charge_network ?? '')
    setRadiusM(String(location.radius_m))
  }, [location])

  const emit = (t: Toast) => onToast?.(t)

  const handleSave = async () => {
    setBusy(true)
    try {
      const payload: LocationUpdateRequest = {
        name: name === '' ? null : name,
        is_home: isHome,
        is_free: isFree,
        default_cost_per_kwh_p: defaultRate === '' ? null : Number(defaultRate),
        default_charge_network:
          defaultNetwork.trim() === '' ? null : defaultNetwork.trim(),
        ...(showRadius ? { radius_m: Number(radiusM) } : {}),
      }
      await api.updateLocation(id, payload)
      emit({ kind: 'success', message: 'Saved.' })
      await onSaved()
    } catch (err) {
      emit({
        kind: 'error',
        message: err instanceof ApiError ? err.message : 'Save failed',
      })
    } finally {
      setBusy(false)
    }
  }

  const handleRecalculate = async () => {
    if (
      !window.confirm(
        "Re-apply this location's tariff to all past non-override sessions linked here?",
      )
    ) {
      return
    }
    setBusy(true)
    try {
      const result = await api.recalculateLocationPastCosts(id)
      emit({
        kind: 'success',
        message: `Recomputed ${result.sessions_recomputed_count} session(s).`,
      })
      await onSaved()
    } catch (err) {
      emit({
        kind: 'error',
        message: err instanceof ApiError ? err.message : 'Recalculate failed',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
            data-testid={`name-input-${id}`}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Default cost (p/kWh)</span>
          <input
            type="number"
            min="0"
            step="0.1"
            value={defaultRate}
            onChange={(e) => setDefaultRate(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Default charge network</span>
          <input
            type="text"
            value={defaultNetwork}
            onChange={(e) => setDefaultNetwork(e.target.value)}
            placeholder="e.g. Outfox Energy, Tesla, MFG"
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
            data-testid={`default-network-input-${id}`}
          />
        </label>
        {showRadius && (
          <label className="flex flex-col gap-1 text-xs">
            <span className="font-medium">Cluster radius (m)</span>
            <input
              type="number"
              min="1"
              step="1"
              value={radiusM}
              onChange={(e) => setRadiusM(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
            />
          </label>
        )}
        <div className="flex items-center gap-3 text-xs">
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={isHome}
              onChange={(e) => setIsHome(e.target.checked)}
            />
            <span>Is home</span>
          </label>
          <label className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={isFree}
              onChange={(e) => setIsFree(e.target.checked)}
            />
            <span>Is free</span>
          </label>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={busy}
          className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          data-testid={`save-button-${id}`}
        >
          Save
        </button>
        {showRecalculate && (
          <button
            type="button"
            onClick={handleRecalculate}
            disabled={busy}
            className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
            data-testid={`recalculate-button-${id}`}
          >
            Recalculate past costs
          </button>
        )}
      </div>
    </div>
  )
}
