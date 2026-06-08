/**
 * Compact lat/lng picker built on the same react-leaflet stack as
 * LocationsMap. Click anywhere on the map to drop the marker and report
 * the coordinates up via `onPick`. The marker also follows externally
 * controlled `lat`/`lng` so typing into the numeric inputs keeps the map
 * in sync (two-way: map → inputs via onPick, inputs → map via props).
 */
import { useEffect } from 'react'
import {
  CircleMarker,
  MapContainer,
  TileLayer,
  useMap,
  useMapEvents,
} from 'react-leaflet'
import { useTheme } from '@/theme'

interface ClickHandlerProps {
  onPick: (lat: number, lng: number) => void
}

function ClickHandler({ onPick }: ClickHandlerProps) {
  useMapEvents({
    click(e) {
      onPick(e.latlng.lat, e.latlng.lng)
    },
  })
  return null
}

interface RecenterProps {
  lat: number | null
  lng: number | null
}

/** Pan the map when the controlled coordinates change (e.g. typed in, or
 *  set from the browser geolocation button) without resetting the zoom. */
function Recenter({ lat, lng }: RecenterProps) {
  const map = useMap()
  useEffect(() => {
    if (lat === null || lng === null) return
    map.setView([lat, lng], Math.max(map.getZoom(), 13))
  }, [map, lat, lng])
  return null
}

export interface LocationPickerMapProps {
  lat: number | null
  lng: number | null
  onPick: (lat: number, lng: number) => void
  className?: string
}

export function LocationPickerMap({
  lat,
  lng,
  onPick,
  className,
}: LocationPickerMapProps) {
  const { theme } = useTheme()
  const isDark =
    theme === 'dark' ||
    (theme === 'system' &&
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches)
  const tileUrl = isDark
    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
  const tileAttribution = isDark
    ? '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
    : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

  const hasPoint = lat !== null && lng !== null
  const center: [number, number] = hasPoint ? [lat, lng] : [51.5, -0.1]
  const mapKey = isDark ? 'dark' : 'light'

  return (
    <div
      className={`h-64 w-full overflow-hidden rounded border border-slate-200 dark:border-slate-700 ${className ?? ''}`}
      data-testid="location-picker-map"
    >
      <MapContainer
        key={mapKey}
        center={center}
        zoom={hasPoint ? 13 : 6}
        scrollWheelZoom={false}
        className="h-full w-full"
      >
        <TileLayer attribution={tileAttribution} url={tileUrl} />
        <ClickHandler onPick={onPick} />
        <Recenter lat={lat} lng={lng} />
        {hasPoint && (
          <CircleMarker
            center={[lat, lng]}
            radius={8}
            pathOptions={{
              color: '#6366f1',
              fillColor: '#6366f1',
              fillOpacity: 0.6,
              weight: 2,
            }}
          />
        )}
      </MapContainer>
    </div>
  )
}
