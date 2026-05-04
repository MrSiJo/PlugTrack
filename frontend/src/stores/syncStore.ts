/**
 * Sync store — full Phase 4 implementation.
 *
 * Holds live SSE state for any in-flight sync jobs, the most recently
 * imported session ids (drives a fade-in highlight on the Sessions
 * list), and a snapshot of per-car state populated from
 * GET /api/sync/status.
 *
 * EventSource lifecycle is owned by `<SyncStreamSubscriber />`; this
 * store exposes pure state mutators so unit tests can drive transitions
 * without spinning up the DOM.
 */
import { create } from 'zustand'

export interface ActiveJob {
  jobId: string
  kind: string
  startedAt: string
}

export interface CarStatus {
  lastState: string | null
  lastSoc: number | null
  nextPollAt: string | null
}

const RECENTLY_IMPORTED_CAP = 20
const RECENTLY_IMPORTED_TTL_MS = 3000

export interface SyncStoreState {
  /** car_id → ActiveJob currently streaming (if any). */
  currentJobsByCarId: Record<number, ActiveJob>
  /** Most-recently-arrived session ids, capped + auto-clearing. */
  recentlyImportedSessionIds: number[]
  /** car_id → last error message surfaced from a sync.error / sync.failed. */
  lastErrorByCarId: Record<number, string>
  /** car_id → snapshot of per-car state (state, SoC, next-poll ETA). */
  statusByCarId: Record<number, CarStatus>

  /** Per-job EventSource references — used by SyncStreamSubscriber to clean up. */
  _eventSources: Record<number, EventSource>

  startStream: (carId: number, jobId: string, streamUrl: string, kind?: string) => void
  stopStream: (carId: number) => void
  stopAllStreams: () => void

  markRecentlyImported: (sessionId: number) => void

  /** Test/wiring helpers. */
  setStatus: (carId: number, status: Partial<CarStatus>) => void
  setError: (carId: number, message: string | null) => void
  reset: () => void
}

function makeInitial() {
  return {
    currentJobsByCarId: {} as Record<number, ActiveJob>,
    recentlyImportedSessionIds: [] as number[],
    lastErrorByCarId: {} as Record<number, string>,
    statusByCarId: {} as Record<number, CarStatus>,
    _eventSources: {} as Record<number, EventSource>,
  }
}

export const useSyncStore = create<SyncStoreState>((set, get) => ({
  ...makeInitial(),

  startStream: (carId, jobId, streamUrl, kind = 'periodic') => {
    // Tear down any existing stream for this car first.
    get().stopStream(carId)

    if (typeof EventSource === 'undefined') return

    const es = new EventSource(streamUrl, { withCredentials: true })
    const handlers: Array<[string, (e: MessageEvent) => void]> = []

    const addHandler = (
      eventName: string,
      handler: (data: Record<string, unknown>) => void,
    ) => {
      const wrapped = (e: MessageEvent) => {
        let payload: Record<string, unknown> = {}
        try {
          payload = JSON.parse(e.data) as Record<string, unknown>
        } catch {
          payload = {}
        }
        handler(payload)
      }
      es.addEventListener(eventName, wrapped)
      handlers.push([eventName, wrapped])
    }

    addHandler('sync.session_opened', (data) => {
      const sessionId = (data.session as { id?: number } | undefined)?.id
      if (typeof sessionId === 'number') {
        get().markRecentlyImported(sessionId)
      }
    })
    addHandler('sync.session_closed', (data) => {
      const sessionId = (data.session as { id?: number } | undefined)?.id
      if (typeof sessionId === 'number') {
        get().markRecentlyImported(sessionId)
      }
    })
    addHandler('sync.poll_completed', (data) => {
      const stateObserved = data.state_observed as string | undefined
      if (stateObserved) {
        get().setStatus(carId, { lastState: stateObserved })
      }
    })
    addHandler('sync.transition', (data) => {
      const to = data.to as string | undefined
      if (to) {
        get().setStatus(carId, { lastState: to })
      }
    })
    addHandler('sync.error', (data) => {
      const message = (data.message as string | undefined) ?? 'sync error'
      get().setError(carId, message)
    })
    addHandler('sync.failed', (data) => {
      const reason = (data.reason as string | undefined) ?? 'sync failed'
      get().setError(carId, reason)
      get().stopStream(carId)
    })
    addHandler('sync.completed', () => {
      get().stopStream(carId)
    })

    set((s) => ({
      currentJobsByCarId: {
        ...s.currentJobsByCarId,
        [carId]: {
          jobId,
          kind,
          startedAt: new Date().toISOString(),
        },
      },
      _eventSources: { ...s._eventSources, [carId]: es },
    }))
  },

  stopStream: (carId) => {
    const es = get()._eventSources[carId]
    if (es) {
      try {
        es.close()
      } catch {
        // best-effort
      }
    }
    set((s) => {
      const nextJobs = { ...s.currentJobsByCarId }
      delete nextJobs[carId]
      const nextSources = { ...s._eventSources }
      delete nextSources[carId]
      return {
        currentJobsByCarId: nextJobs,
        _eventSources: nextSources,
      }
    })
  },

  stopAllStreams: () => {
    const ids = Object.keys(get()._eventSources).map(Number)
    for (const carId of ids) {
      get().stopStream(carId)
    }
  },

  markRecentlyImported: (sessionId) => {
    set((s) => {
      const dedup = s.recentlyImportedSessionIds.filter((id) => id !== sessionId)
      const next = [sessionId, ...dedup].slice(0, RECENTLY_IMPORTED_CAP)
      return { recentlyImportedSessionIds: next }
    })

    // Clear after the highlight window.
    if (typeof window !== 'undefined') {
      window.setTimeout(() => {
        set((s) => ({
          recentlyImportedSessionIds: s.recentlyImportedSessionIds.filter(
            (id) => id !== sessionId,
          ),
        }))
      }, RECENTLY_IMPORTED_TTL_MS)
    }
  },

  setStatus: (carId, status) => {
    set((s) => ({
      statusByCarId: {
        ...s.statusByCarId,
        [carId]: { ...(s.statusByCarId[carId] ?? { lastState: null, lastSoc: null, nextPollAt: null }), ...status },
      },
    }))
  },

  setError: (carId, message) => {
    set((s) => {
      const next = { ...s.lastErrorByCarId }
      if (message === null) {
        delete next[carId]
      } else {
        next[carId] = message
      }
      return { lastErrorByCarId: next }
    })
  },

  reset: () => {
    get().stopAllStreams()
    set(makeInitial())
  },
}))
