import type { CarCreateRequest } from '@/api/client'

export interface CarFieldsProps {
  draft: CarCreateRequest
  setDraft: (next: CarCreateRequest) => void
}

export function CarFields({ draft, setDraft }: CarFieldsProps) {
  const fieldClass =
    'mt-1 w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100'
  const labelClass = 'block text-xs font-medium text-slate-700 dark:text-slate-300'

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <label className={`${labelClass} sm:col-span-2`}>
        Name (optional)
        <input
          value={draft.name ?? ''}
          onChange={(e) => setDraft({ ...draft, name: e.target.value || null })}
          className={fieldClass}
          placeholder="e.g. Work car (defaults to Make + Model)"
        />
      </label>
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
      <label className={labelClass}>
        Max AC kW (optional)
        <input
          type="number"
          step="0.1"
          min="0.1"
          placeholder="e.g. 11 for 3-phase Type-2"
          value={Number.isFinite(draft.max_ac_kw ?? NaN) ? (draft.max_ac_kw as number) : ''}
          onChange={(e) =>
            setDraft({
              ...draft,
              max_ac_kw: e.target.value === '' ? null : Number(e.target.value),
            })
          }
          className={fieldClass}
        />
      </label>
      <label className={labelClass}>
        Max DC kW (optional)
        <input
          type="number"
          step="1"
          min="0.1"
          placeholder="e.g. 100 for CCS fast-charge"
          value={Number.isFinite(draft.max_dc_kw ?? NaN) ? (draft.max_dc_kw as number) : ''}
          onChange={(e) =>
            setDraft({
              ...draft,
              max_dc_kw: e.target.value === '' ? null : Number(e.target.value),
            })
          }
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
