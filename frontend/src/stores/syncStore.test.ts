import { describe, it, expect } from 'vitest'
import { useSyncStore } from './syncStore'

describe('syncStore (placeholder)', () => {
  it('initialises with unknown state and no last sync', () => {
    const state = useSyncStore.getState()
    expect(state.state).toBe('unknown')
    expect(state.lastSyncAt).toBeNull()
  })
})
