import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import SyncStreamSubscriber from './SyncStreamSubscriber'
import { api } from '@/api/client'
import { useSyncStore } from '@/stores/syncStore'

describe('SyncStreamSubscriber', () => {
  let closeSpy: ReturnType<typeof vi.fn>
  let constructed: string[]

  beforeEach(() => {
    useSyncStore.getState().reset()
    closeSpy = vi.fn()
    constructed = []
    class MockEventSource {
      url: string
      addEventListener = vi.fn()
      close = closeSpy
      constructor(url: string, _init?: { withCredentials?: boolean }) {
        this.url = url
        constructed.push(url)
      }
    }
    vi.stubGlobal('EventSource', MockEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('fetches status, opens EventSource for active jobs, cleans up on unmount', async () => {
    vi.spyOn(api, 'getSyncStatus').mockResolvedValue({
      cars: {
        '1': {
          last_state: 'CHARGING',
          last_soc: 60,
          next_poll_at: '2026-05-04T13:00:00Z',
          last_error: null,
          active_job_id: 'job-xyz',
          consecutive_failures: 0,
          auth_invalid: false,
        },
        '2': {
          last_state: 'IDLE',
          last_soc: 80,
          next_poll_at: '2026-05-04T13:30:00Z',
          last_error: null,
          active_job_id: null,
          consecutive_failures: 0,
          auth_invalid: false,
        },
      },
    })

    const { unmount } = render(<SyncStreamSubscriber />)

    await waitFor(() => {
      expect(constructed).toContain('/api/sync/stream/job-xyz')
    })

    // No EventSource opened for car 2 (no active job).
    expect(constructed.length).toBe(1)

    // Status snapshot pushed into the store.
    expect(useSyncStore.getState().statusByCarId[1]?.lastState).toBe('CHARGING')
    expect(useSyncStore.getState().statusByCarId[2]?.lastState).toBe('IDLE')
    expect(useSyncStore.getState().currentJobsByCarId[1]?.jobId).toBe('job-xyz')

    unmount()
    // EventSource closed on unmount.
    expect(closeSpy).toHaveBeenCalled()
    expect(useSyncStore.getState().currentJobsByCarId[1]).toBeUndefined()
  })

  it('surfaces auth_invalid from the status snapshot into the banner store', async () => {
    // A silent periodic failure: no active job to stream, but the snapshot
    // reports the car as auth_invalid. The subscriber must seed
    // lastErrorByCarId so AuthFailureBanner lights up without waiting for a
    // user-watched force-sync.
    vi.spyOn(api, 'getSyncStatus').mockResolvedValue({
      cars: {
        '1': {
          last_state: 'IDLE',
          last_soc: 79,
          next_poll_at: null,
          last_error: 'credentials_invalid',
          active_job_id: null,
          consecutive_failures: 461,
          auth_invalid: true,
        },
      },
    })

    const { unmount } = render(<SyncStreamSubscriber />)

    await waitFor(() => {
      expect(useSyncStore.getState().lastErrorByCarId[1]).toBe(
        'credentials_invalid',
      )
    })
    // No stream opened — there was no active job.
    expect(constructed.length).toBe(0)
    unmount()
  })

  it('renders nothing on 401 (not logged in)', async () => {
    const { ApiError } = await import('@/api/client')
    vi.spyOn(api, 'getSyncStatus').mockRejectedValue(
      new ApiError(401, 'Authentication required', null),
    )

    const { container, unmount } = render(<SyncStreamSubscriber />)
    await waitFor(() => {
      // No EventSources opened.
      expect(constructed.length).toBe(0)
    })
    expect(container.firstChild).toBeNull()
    unmount()
  })

  it('handles empty status snapshot cleanly', async () => {
    vi.spyOn(api, 'getSyncStatus').mockResolvedValue({ cars: {} })
    const { unmount } = render(<SyncStreamSubscriber />)
    await waitFor(() => {
      expect(useSyncStore.getState().currentJobsByCarId).toEqual({})
    })
    unmount()
  })
})
