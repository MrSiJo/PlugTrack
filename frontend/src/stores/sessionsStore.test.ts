import { describe, it, expect } from 'vitest'
import { useSessionsStore } from './sessionsStore'

describe('sessionsStore (placeholder)', () => {
  it('initialises empty', () => {
    const state = useSessionsStore.getState()
    expect(state.sessions).toEqual([])
    expect(state.loaded).toBe(false)
  })
})
