import { describe, it, expect } from 'vitest'
import { formatDistance, kmToMi, miToKm } from './distance'

describe('distance utility', () => {
  it('km <-> mi round trip', () => {
    expect(kmToMi(0)).toBe(0)
    expect(kmToMi(1.609344)).toBeCloseTo(1, 6)
    expect(miToKm(1)).toBeCloseTo(1.609344, 6)
  })

  it('formatDistance produces a labelled string in the requested unit', () => {
    expect(formatDistance(100, 'km')).toBe('100 km')
    expect(formatDistance(100, 'mi')).toBe('62 mi')
    expect(formatDistance(0, 'mi')).toBe('0 mi')
    expect(formatDistance(0, 'km')).toBe('0 km')
  })

  it('handles large values', () => {
    expect(formatDistance(100_000, 'km')).toBe('100000 km')
    expect(formatDistance(100_000, 'mi')).toBe('62137 mi')
  })

  it('rounds floats sensibly', () => {
    expect(formatDistance(1.4, 'km')).toBe('1 km')
    expect(formatDistance(1.6, 'km')).toBe('2 km')
  })

  it('kmToMi matches a hand-calc reference', () => {
    // 161 km should be roughly 100 mi.
    expect(kmToMi(160.9344)).toBeCloseTo(100, 3)
  })
})
