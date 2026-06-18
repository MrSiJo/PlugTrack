/**
 * Location detail page (/locations/:id) — analytics drill-down.
 *
 * All-time stats header (reusing the GET /api/locations aggregate row),
 * the location's charges (GET /api/sessions?location_id=), and a
 * non-destructive in-context edit (shared LocationEditForm + recalculate).
 * No delete / merge / create here — those live in the Locations admin page.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  ApiError,
  api,
  type ChargingSessionPayload,
  type InsightsLocationRow,
  type LocationListPayload,
} from '@/api/client'
import { LocationEditForm } from '@/components/locations/LocationEditForm'
import { SessionsTable } from '@/components/sessions/SessionsTable'
import { Card } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { GradientNumber } from '@/components/ui/GradientNumber'
import { PageHeader } from '@/components/ui/PageHeader'
import { useSetting } from '@/stores/settingsStore'
import { formatCurrency } from '@/utils/currency'

interface Toast {
  kind: 'success' | 'error'
  message: string
}

export default function LocationDetail() {
  const { id } = useParams<{ id: string }>()
  const numericId = Number(id)
  const currency = useSetting<string>('currency') ?? 'GBP'

  const [location, setLocation] = useState<LocationListPayload | null>(null)
  const [insightsRow, setInsightsRow] = useState<InsightsLocationRow | null>(null)
  const [sessions, setSessions] = useState<ChargingSessionPayload[]>([])
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<Toast | null>(null)

  const load = useCallback(async () => {
    if (!Number.isFinite(numericId)) {
      setNotFound(true)
      setLoading(false)
      return
    }
    try {
      setLoading(true)
      const [locs, insights, sess] = await Promise.all([
        api.getLocations(),
        api.getInsightsByLocation(),
        api.getSessions(`?location_id=${numericId}`),
      ])
      const match = locs.find((l) => l.id === numericId) ?? null
      if (match === null) {
        setNotFound(true)
      } else {
        setLocation(match)
        setInsightsRow(insights.rows.find((r) => r.location_id === numericId) ?? null)
        setSessions(sess)
        setNotFound(false)
      }
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load location')
    } finally {
      setLoading(false)
    }
  }, [numericId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (toast === null) return
    const handle = window.setTimeout(() => setToast(null), 4000)
    return () => window.clearTimeout(handle)
  }, [toast])

  const stats = useMemo(() => {
    if (location === null) return null
    const row = insightsRow
    return {
      spend: row?.spend_pence ?? 0,
      kwh: row?.kwh ?? 0,
      sessions: row?.sessions ?? 0,
      avg: row?.avg_p_per_kwh ?? null,
      lastVisited: row?.last_at ?? null,
    }
  }, [location, insightsRow])

  if (loading) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-8">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    )
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-8" data-testid="location-not-found">
        <EmptyState
          title="Location not found"
          body="This location doesn't exist or isn't yours."
        />
        <Link to="/insights" className="mt-4 inline-block text-sm text-cyan-600 hover:underline">
          ← Back to Insights
        </Link>
      </div>
    )
  }

  if (error || location === null || stats === null) {
    return (
      <div className="mx-auto max-w-7xl px-6 py-8">
        <div role="alert" className="text-sm text-red-600">
          {error ?? 'Failed to load location'}
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-8">
      <PageHeader
        title={location.name ?? `Location #${location.id}`}
        subtitle={location.address ?? undefined}
        actions={
          <Link to="/insights" className="text-sm text-cyan-600 hover:underline">
            ← Insights
          </Link>
        }
      />

      {toast && (
        <div
          role="status"
          className={
            'mb-4 rounded p-3 text-sm ' +
            (toast.kind === 'success'
              ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200'
              : 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-200')
          }
        >
          {toast.message}
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-5">
        <Stat label="Total spend">
          <GradientNumber size="lg">{formatCurrency(stats.spend, currency)}</GradientNumber>
        </Stat>
        <Stat label="Total kWh">{stats.kwh.toFixed(1)}</Stat>
        <Stat label="Sessions">{stats.sessions}</Stat>
        <Stat label="Avg p/kWh">
          {stats.avg === null ? '—' : `${stats.avg.toFixed(1)}p`}
        </Stat>
        <Stat label="Last visited">
          {stats.lastVisited ? stats.lastVisited.slice(0, 10) : '—'}
        </Stat>
      </div>

      <Card className="mb-6">
        <h2 className="mb-3 text-sm font-semibold">Edit location</h2>
        <LocationEditForm
          location={location}
          onSaved={load}
          onToast={setToast}
        />
      </Card>

      <h2 className="mb-3 text-sm font-semibold">
        Charges here ({sessions.length})
      </h2>
      {sessions.length === 0 ? (
        <EmptyState title="No charges yet" body="Charges logged at this location will appear here." />
      ) : (
        <SessionsTable sessions={sessions} currency={currency} />
      )}
    </div>
  )
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Card>
      <p className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-1 text-sm tabular-nums text-slate-700 dark:text-slate-200">{children}</p>
    </Card>
  )
}
