import { describe, it, expect } from 'vitest'
import { fmtChargeSeconds } from './SessionDetail'

describe('fmtChargeSeconds', () => {
  it('formats sub-hour durations as minutes', () => {
    expect(fmtChargeSeconds(45 * 60)).toBe('45m')
  })

  it('formats multi-hour durations as h + zero-padded minutes', () => {
    expect(fmtChargeSeconds(9 * 3600 + 9 * 60)).toBe('9h 09m')
  })

  it('returns a dash for null', () => {
    expect(fmtChargeSeconds(null)).toBe('—')
  })
})
