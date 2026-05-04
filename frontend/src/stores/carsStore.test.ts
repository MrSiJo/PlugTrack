import { describe, it, expect } from 'vitest'
import { useCarsStore } from './carsStore'

describe('carsStore (placeholder)', () => {
  it('initialises empty', () => {
    const state = useCarsStore.getState()
    expect(state.cars).toEqual([])
    expect(state.activeCarId).toBeNull()
    expect(state.loaded).toBe(false)
  })
})
