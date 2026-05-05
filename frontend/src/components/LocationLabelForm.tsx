/**
 * Inline form rendered next to an unlabelled location pill on the
 * SessionDetail page. Posts to `PATCH /api/locations/{id}/label`.
 *
 * On success the parent receives a `(saved, recomputedCount)` callback
 * so it can show "Saved. Recomputed cost on N past sessions."
 *
 * Behaviour:
 * - `is_free` checkbox disables the per-kWh rate input.
 * - `name` is required (min 1 char) — matches backend validation.
 */
import { useState, type FormEvent } from 'react'
import { ApiError, api } from '@/api/client'

export interface LocationLabelFormProps {
  locationId: number
  onSaved?: (recomputedCount: number, label: { name: string; isHome: boolean; isFree: boolean }) => void
}

export default function LocationLabelForm({ locationId, onSaved }: LocationLabelFormProps) {
  const [name, setName] = useState('')
  const [isHome, setIsHome] = useState(false)
  const [isFree, setIsFree] = useState(false)
  const [defaultRate, setDefaultRate] = useState('')
  const [defaultNetwork, setDefaultNetwork] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const rate = isFree || defaultRate === '' ? null : Number(defaultRate)
      const result = await api.labelLocation(locationId, {
        name: name.trim(),
        is_home: isHome,
        is_free: isFree,
        default_cost_per_kwh_p: rate,
        default_charge_network:
          defaultNetwork.trim() === '' ? null : defaultNetwork.trim(),
      })
      onSaved?.(result.sessions_recomputed_count, {
        name: result.location.name ?? name.trim(),
        isHome,
        isFree,
      })
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : 'Failed to label location'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }

  const inputClass =
    'w-full rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800'

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3 rounded border border-slate-200 p-3 text-sm dark:border-slate-700"
      aria-label="Label this location"
    >
      <label className="block">
        <span className="block text-xs font-medium">Name</span>
        <input
          type="text"
          required
          minLength={1}
          maxLength={128}
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={inputClass}
          placeholder="e.g. Home, Work, Tesco Supercharger"
        />
      </label>
      <div className="flex items-center gap-4">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={isHome}
            onChange={(e) => setIsHome(e.target.checked)}
          />
          <span className="text-xs">Is home</span>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={isFree}
            onChange={(e) => setIsFree(e.target.checked)}
          />
          <span className="text-xs">Free charging</span>
        </label>
      </div>
      <label className="block">
        <span className="block text-xs font-medium">
          Default cost (p/kWh)
        </span>
        <input
          type="number"
          min={0}
          step="0.1"
          value={defaultRate}
          disabled={isFree}
          onChange={(e) => setDefaultRate(e.target.value)}
          className={`${inputClass} ${isFree ? 'opacity-40' : ''}`}
          placeholder={isFree ? 'Disabled — free' : 'e.g. 35.0'}
          aria-label="Default cost per kWh"
        />
      </label>
      <label className="block">
        <span className="block text-xs font-medium">
          Default charge network
        </span>
        <input
          type="text"
          maxLength={64}
          value={defaultNetwork}
          onChange={(e) => setDefaultNetwork(e.target.value)}
          className={inputClass}
          placeholder="e.g. Outfox Energy, Tesla, MFG"
          aria-label="Default charge network"
        />
      </label>
      {error && (
        <p role="alert" className="text-xs text-red-600">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={submitting || name.trim().length === 0}
        className="rounded bg-indigo-600 px-3 py-1 text-sm text-white disabled:opacity-50"
      >
        {submitting ? 'Saving…' : 'Save'}
      </button>
    </form>
  )
}
