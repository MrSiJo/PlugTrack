import { useState } from 'react'
import { ApiError, api, type LocationCreateRequest } from '@/api/client'
import { LocationPickerMap } from '@/components/locations/LocationPickerMap'

interface Toast {
  kind: 'success' | 'error'
  message: string
}

export interface LocationCreateFormProps {
  onCreated: () => Promise<void>
  onCancel: () => void
  onToast: (t: Toast) => void
}

export function LocationCreateForm({
  onCreated,
  onCancel,
  onToast,
}: LocationCreateFormProps) {
  const [name, setName] = useState('')
  const [lat, setLat] = useState<number | null>(null)
  const [lng, setLng] = useState<number | null>(null)
  const [radiusM, setRadiusM] = useState('100')
  const [defaultRate, setDefaultRate] = useState('')
  const [defaultNetwork, setDefaultNetwork] = useState('')
  const [isHome, setIsHome] = useState(false)
  const [isFree, setIsFree] = useState(false)
  const [busy, setBusy] = useState(false)
  const [geoBusy, setGeoBusy] = useState(false)
  const [addressQuery, setAddressQuery] = useState('')
  const [searching, setSearching] = useState(false)

  const latText = lat === null ? '' : String(lat)
  const lngText = lng === null ? '' : String(lng)

  const handlePick = (pickedLat: number, pickedLng: number) => {
    // Round to 6dp — ~0.1 m precision, plenty for a charge site centroid.
    setLat(Number(pickedLat.toFixed(6)))
    setLng(Number(pickedLng.toFixed(6)))
  }

  const handleUseMyLocation = () => {
    if (!('geolocation' in navigator)) {
      onToast({ kind: 'error', message: 'Geolocation not available in this browser.' })
      return
    }
    setGeoBusy(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        handlePick(pos.coords.latitude, pos.coords.longitude)
        setGeoBusy(false)
      },
      (err) => {
        setGeoBusy(false)
        onToast({ kind: 'error', message: `Couldn't get your location: ${err.message}` })
      },
      { enableHighAccuracy: true, timeout: 10_000 },
    )
  }

  const handleFindByAddress = async () => {
    if (addressQuery.trim() === '') {
      onToast({ kind: 'error', message: 'Type an address or place to search.' })
      return
    }
    setSearching(true)
    try {
      const r = await api.geocode(addressQuery.trim())
      handlePick(r.lat, r.lng)
      if (name.trim() === '') setName(addressQuery.trim())
      onToast({ kind: 'success', message: `Found: ${r.address}` })
    } catch (err) {
      onToast({
        kind: 'error',
        message:
          err instanceof ApiError
            ? err.status === 404
              ? 'No match for that address — try adding the town or postcode.'
              : err.message
            : 'Address search failed',
      })
    } finally {
      setSearching(false)
    }
  }

  const handleCreate = async () => {
    if (lat === null || lng === null) {
      onToast({ kind: 'error', message: 'Pick a point on the map or type a lat/lng.' })
      return
    }
    setBusy(true)
    try {
      const payload: LocationCreateRequest = {
        name: name.trim() === '' ? null : name.trim(),
        centroid_lat: lat,
        centroid_lng: lng,
        radius_m: Number(radiusM) || 100,
        is_home: isHome,
        is_free: isFree,
        default_cost_per_kwh_p: defaultRate === '' ? null : Number(defaultRate),
        default_charge_network:
          defaultNetwork.trim() === '' ? null : defaultNetwork.trim(),
      }
      await api.createLocation(payload)
      onToast({ kind: 'success', message: 'Location created.' })
      await onCreated()
    } catch (err) {
      onToast({
        kind: 'error',
        message: err instanceof ApiError ? err.message : 'Create failed',
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="mb-6 rounded border border-indigo-200 bg-indigo-50/40 p-4 dark:border-indigo-900 dark:bg-indigo-950/20"
      data-testid="location-create-form"
    >
      <h2 className="mb-3 text-sm font-semibold">New location</h2>
      <p className="mb-3 text-xs text-slate-500 dark:text-slate-400">
        Search by address, click the map to drop a pin, type coordinates
        directly, or use your current location. Set a default rate now so
        charges here are costed correctly instead of falling back to the home
        rate.
      </p>

      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-1 flex-col gap-1 text-xs">
          <span className="font-medium">Find by address</span>
          <input
            type="text"
            value={addressQuery}
            onChange={(e) => setAddressQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void handleFindByAddress()
              }
            }}
            placeholder="e.g. Instavolt McDonalds, Lysander Road, Yeovil"
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
            data-testid="geocode-query-input"
          />
        </label>
        <button
          type="button"
          onClick={handleFindByAddress}
          disabled={searching}
          className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          data-testid="geocode-search-button"
        >
          {searching ? 'Searching…' : 'Find'}
        </button>
      </div>

      <div className="mb-3">
        <LocationPickerMap lat={lat} lng={lng} onPick={handlePick} />
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Tesla Camborne"
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
            data-testid="create-name-input"
          />
        </label>
        <div className="flex items-end gap-2">
          <label className="flex flex-1 flex-col gap-1 text-xs">
            <span className="font-medium">Latitude</span>
            <input
              type="number"
              step="0.000001"
              value={latText}
              onChange={(e) =>
                setLat(e.target.value === '' ? null : Number(e.target.value))
              }
              className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
              data-testid="create-lat-input"
            />
          </label>
          <label className="flex flex-1 flex-col gap-1 text-xs">
            <span className="font-medium">Longitude</span>
            <input
              type="number"
              step="0.000001"
              value={lngText}
              onChange={(e) =>
                setLng(e.target.value === '' ? null : Number(e.target.value))
              }
              className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
              data-testid="create-lng-input"
            />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Default cost (p/kWh)</span>
          <input
            type="number"
            min="0"
            step="0.1"
            value={defaultRate}
            onChange={(e) => setDefaultRate(e.target.value)}
            placeholder="e.g. 45"
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Default charge network</span>
          <input
            type="text"
            value={defaultNetwork}
            onChange={(e) => setDefaultNetwork(e.target.value)}
            placeholder="e.g. Tesla, MFG, Outfox Energy"
            className="rounded border border-slate-300 px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
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
          onClick={handleCreate}
          disabled={busy}
          className="rounded bg-indigo-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          data-testid="create-location-submit"
        >
          Create location
        </button>
        <button
          type="button"
          onClick={handleUseMyLocation}
          disabled={geoBusy}
          className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
        >
          {geoBusy ? 'Locating…' : 'Use my location'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="ml-auto rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
