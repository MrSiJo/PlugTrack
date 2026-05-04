/**
 * SyncStreamSubscriber.
 *
 * Mounted ONCE in App.tsx. On mount:
 * 1. Fetch /api/sync/status to discover any cars with active jobs.
 * 2. For each one, open an EventSource and pipe events into syncStore.
 *
 * Cleanup on unmount: close every EventSource.
 *
 * No UI of its own — pure side-effect bridge between the SSE stream and
 * the zustand store that pages read from.
 */
import { useEffect } from 'react'
import { ApiError, api } from '@/api/client'
import { useSyncStore } from '@/stores/syncStore'

export default function SyncStreamSubscriber() {
  const startStream = useSyncStore((s) => s.startStream)
  const stopAllStreams = useSyncStore((s) => s.stopAllStreams)
  const setStatus = useSyncStore((s) => s.setStatus)

  useEffect(() => {
    let cancelled = false

    void (async () => {
      try {
        const status = await api.getSyncStatus()
        if (cancelled) return
        for (const [carIdStr, snapshot] of Object.entries(status.cars)) {
          const carId = Number(carIdStr)
          setStatus(carId, {
            lastState: snapshot.last_state,
            lastSoc: snapshot.last_soc,
            nextPollAt: snapshot.next_poll_at,
          })
          if (snapshot.active_job_id) {
            const streamUrl = `/api/sync/stream/${snapshot.active_job_id}`
            startStream(carId, snapshot.active_job_id, streamUrl, 'periodic')
          }
        }
      } catch (err) {
        // 401 just means we're not logged in yet — silent. Other errors
        // log so the dev console surfaces them.
        if (err instanceof ApiError && err.status === 401) {
          return
        }
        // eslint-disable-next-line no-console
        console.warn('SyncStreamSubscriber bootstrap failed', err)
      }
    })()

    return () => {
      cancelled = true
      stopAllStreams()
    }
    // Run exactly once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return null
}
