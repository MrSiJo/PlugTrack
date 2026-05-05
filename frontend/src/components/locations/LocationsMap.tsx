import { useEffect, useMemo } from 'react'
import {
  CircleMarker,
  MapContainer,
  Popup,
  TileLayer,
  useMap,
} from 'react-leaflet'
import type { LocationListPayload } from '@/api/client'
import { Card } from '@/components/ui/Card'
import { GradientNumber } from '@/components/ui/GradientNumber'
import {
  classifyCostBand,
  type CostBand,
} from '@/lib/costBand'
import { useTheme } from '@/theme'
import { formatCurrency } from '@/utils/currency'

const BAND_FILL: Record<CostBand, string> = {
  green: '#10b981',
  cyan: '#22d3ee',
  amber: '#f59e0b',
  red: '#ef4444',
  slate: '#64748b',
}

interface FitBoundsProps {
  points: { lat: number; lng: number }[]
}

function FitBounds({ points }: FitBoundsProps) {
  const map = useMap()
  useEffect(() => {
    if (points.length === 0) return
    if (points.length === 1) {
      const point = points[0]
      if (point) map.setView([point.lat, point.lng], 13)
      return
    }
    const bounds = points.map((p) => [p.lat, p.lng] as [number, number])
    map.fitBounds(bounds, { padding: [24, 24] })
  }, [map, points])
  return null
}

export interface LocationsMapProps {
  locations: LocationListPayload[]
  homeRatePence: number
  currency: string
  className?: string
}

export function LocationsMap({
  locations,
  homeRatePence,
  currency,
  className,
}: LocationsMapProps) {
  const points = useMemo(
    () =>
      locations.map((loc) => ({
        id: loc.id,
        lat: loc.centroid_lat,
        lng: loc.centroid_lng,
        name: loc.name ?? `Unlabelled #${loc.id}`,
        is_free: loc.is_free,
        default_cost_per_kwh_p: loc.default_cost_per_kwh_p,
        visit_count: loc.visit_count,
        total_cost_pence: loc.total_cost_pence,
        total_kwh: loc.total_kwh,
      })),
    [locations],
  )

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

  if (points.length === 0) {
    return (
      <Card className={className}>
        <p className="text-sm text-slate-500">
          No locations to map yet. Plug in to seed your first cluster.
        </p>
      </Card>
    )
  }

  // Use a key that flips on theme change so the TileLayer remounts.
  const mapKey = isDark ? 'dark' : 'light'

  return (
    <Card className={`overflow-hidden p-0 ${className ?? ''}`}>
      <div className="h-80 w-full">
        <MapContainer
          key={mapKey}
          center={[51.5, -0.1]}
          zoom={6}
          scrollWheelZoom={false}
          className="h-full w-full"
        >
          <TileLayer attribution={tileAttribution} url={tileUrl} />
          <FitBounds points={points} />
          {points.map((p) => {
            const band = classifyCostBand(
              {
                is_free: p.is_free,
                default_cost_per_kwh_p: p.default_cost_per_kwh_p,
              },
              { homeRatePence },
            )
            const radius = 5 + Math.sqrt(Math.max(0, p.visit_count))
            return (
              <CircleMarker
                key={p.id}
                center={[p.lat, p.lng]}
                radius={radius}
                pathOptions={{
                  color: BAND_FILL[band],
                  fillColor: BAND_FILL[band],
                  fillOpacity: 0.7,
                  weight: 2,
                  opacity: 0.9,
                }}
              >
                <Popup>
                  <div className="text-xs">
                    <p className="font-semibold">{p.name}</p>
                    <p className="mt-1">
                      {p.visit_count}{' '}
                      {p.visit_count === 1 ? 'visit' : 'visits'} ·{' '}
                      {p.total_kwh.toFixed(1)} kWh
                    </p>
                    <p className="mt-1">
                      <GradientNumber size="sm">
                        {formatCurrency(p.total_cost_pence, currency)}
                      </GradientNumber>
                    </p>
                  </div>
                </Popup>
              </CircleMarker>
            )
          })}
        </MapContainer>
      </div>
    </Card>
  )
}
