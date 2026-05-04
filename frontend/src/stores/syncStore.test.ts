import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useSyncStore } from './syncStore'

describe('syncStore', () => {
  beforeEach(() => {
    useSyncStore.getState().reset()
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('initialises empty', () => {
    const s = useSyncStore.getState()
    expect(s.currentJobsByCarId).toEqual({})
    expect(s.recentlyImportedSessionIds).toEqual([])
    expect(s.lastErrorByCarId).toEqual({})
    expect(s.statusByCarId).toEqual({})
  })

  it('markRecentlyImported prepends session id and dedupes', () => {
    const { markRecentlyImported } = useSyncStore.getState()
    markRecentlyImported(1)
    markRecentlyImported(2)
    markRecentlyImported(1)
    expect(useSyncStore.getState().recentlyImportedSessionIds).toEqual([1, 2])
  })

  it('markRecentlyImported clears entries after the highlight window', () => {
    const { markRecentlyImported } = useSyncStore.getState()
    markRecentlyImported(42)
    expect(useSyncStore.getState().recentlyImportedSessionIds).toContain(42)
    vi.advanceTimersByTime(3500)
    expect(useSyncStore.getState().recentlyImportedSessionIds).not.toContain(42)
  })

  it('caps recently imported list at 20 entries', () => {
    const { markRecentlyImported } = useSyncStore.getState()
    for (let i = 0; i < 25; i++) {
      markRecentlyImported(i)
    }
    expect(useSyncStore.getState().recentlyImportedSessionIds.length).toBe(20)
    // Most recent should be at index 0.
    expect(useSyncStore.getState().recentlyImportedSessionIds[0]).toBe(24)
  })

  it('setStatus merges per-car snapshot', () => {
    useSyncStore.getState().setStatus(7, { lastState: 'CHARGING', lastSoc: 55 })
    useSyncStore.getState().setStatus(7, { nextPollAt: '2026-05-04T13:00:00Z' })
    expect(useSyncStore.getState().statusByCarId[7]).toEqual({
      lastState: 'CHARGING',
      lastSoc: 55,
      nextPollAt: '2026-05-04T13:00:00Z',
    })
  })

  it('setError sets and clears per-car error', () => {
    useSyncStore.getState().setError(2, 'auth_failed')
    expect(useSyncStore.getState().lastErrorByCarId[2]).toBe('auth_failed')
    useSyncStore.getState().setError(2, null)
    expect(useSyncStore.getState().lastErrorByCarId[2]).toBeUndefined()
  })

  it('startStream registers a job and creates an EventSource', () => {
    const closeSpy = vi.fn()
    const addEventListenerSpy = vi.fn()

    class MockEventSource {
      url: string
      withCredentials: boolean
      readyState = 1
      addEventListener = addEventListenerSpy
      close = closeSpy
      constructor(url: string, init?: { withCredentials?: boolean }) {
        this.url = url
        this.withCredentials = init?.withCredentials ?? false
      }
    }
    vi.stubGlobal('EventSource', MockEventSource)

    useSyncStore
      .getState()
      .startStream(1, 'job-abc', '/api/sync/stream/job-abc', 'force')

    const job = useSyncStore.getState().currentJobsByCarId[1]
    expect(job?.jobId).toBe('job-abc')
    expect(job?.kind).toBe('force')

    // At least one handler registered (sync.session_opened, etc.).
    expect(addEventListenerSpy).toHaveBeenCalled()

    useSyncStore.getState().stopStream(1)
    expect(closeSpy).toHaveBeenCalled()
    expect(useSyncStore.getState().currentJobsByCarId[1]).toBeUndefined()

    vi.unstubAllGlobals()
  })

  it('stopAllStreams closes every EventSource', () => {
    const closeSpy = vi.fn()
    class MockEventSource {
      url: string
      addEventListener = vi.fn()
      close = closeSpy
      constructor(url: string) {
        this.url = url
      }
    }
    vi.stubGlobal('EventSource', MockEventSource)

    useSyncStore.getState().startStream(1, 'a', '/stream/a')
    useSyncStore.getState().startStream(2, 'b', '/stream/b')
    expect(Object.keys(useSyncStore.getState().currentJobsByCarId).length).toBe(2)

    useSyncStore.getState().stopAllStreams()
    expect(closeSpy).toHaveBeenCalledTimes(2)
    expect(useSyncStore.getState().currentJobsByCarId).toEqual({})

    vi.unstubAllGlobals()
  })
})
