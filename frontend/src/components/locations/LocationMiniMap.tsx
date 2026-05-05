import { CircleMarker, MapContainer, TileLayer } from 'react-leaflet'
import { Card } from '@/components/ui/Card'
import { useTheme } from '@/theme'

export interface LocationMiniMapProps {
  lat: number
  lng: number
  /** Optional accent colour for the marker; defaults to cyan. */
  accent?: string
  className?: string
  zoom?: number
  height?: number
}

export function LocationMiniMap({
  lat,
  lng,
  accent = '#22d3ee',
  className,
  zoom = 14,
  height = 160,
}: LocationMiniMapProps) {
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
    ? '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
    : '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'

  // Remount the map when theme flips so the tile layer reloads.
  const mapKey = isDark ? 'dark' : 'light'

  return (
    <Card className={`overflow-hidden p-0 ${className ?? ''}`}>
      <div style={{ height: `${height}px` }} className="w-full">
        <MapContainer
          key={mapKey}
          center={[lat, lng]}
          zoom={zoom}
          dragging={false}
          scrollWheelZoom={false}
          doubleClickZoom={false}
          zoomControl={false}
          attributionControl={false}
          className="h-full w-full"
        >
          <TileLayer attribution={tileAttribution} url={tileUrl} />
          <CircleMarker
            center={[lat, lng]}
            radius={8}
            pathOptions={{
              color: accent,
              fillColor: accent,
              fillOpacity: 0.7,
              weight: 2,
            }}
          />
        </MapContainer>
      </div>
    </Card>
  )
}
