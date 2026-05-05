import { describe, expect, it } from 'vitest'
import { classifyCostBand } from './costBand'

describe('classifyCostBand', () => {
  it('returns green for free locations', () => {
    expect(
      classifyCostBand(
        { is_free: true, default_cost_per_kwh_p: null },
        { homeRatePence: 25 },
      ),
    ).toBe('green')
  })

  it('returns cyan when rate is at or below home rate × 1.2', () => {
    expect(
      classifyCostBand(
        { is_free: false, default_cost_per_kwh_p: 25 },
        { homeRatePence: 25 },
      ),
    ).toBe('cyan')
    expect(
      classifyCostBand(
        { is_free: false, default_cost_per_kwh_p: 30 },
        { homeRatePence: 25 },
      ),
    ).toBe('cyan')
  })

  it('returns amber when between 1.2x and 2.5x home rate', () => {
    expect(
      classifyCostBand(
        { is_free: false, default_cost_per_kwh_p: 50 },
        { homeRatePence: 25 },
      ),
    ).toBe('amber')
  })

  it('returns red when more than 2.5x home rate', () => {
    expect(
      classifyCostBand(
        { is_free: false, default_cost_per_kwh_p: 70 },
        { homeRatePence: 25 },
      ),
    ).toBe('red')
  })

  it('returns slate when rate is unknown', () => {
    expect(
      classifyCostBand(
        { is_free: false, default_cost_per_kwh_p: null },
        { homeRatePence: 25 },
      ),
    ).toBe('slate')
  })

  it('falls back to slate when home rate is unset', () => {
    expect(
      classifyCostBand(
        { is_free: false, default_cost_per_kwh_p: 30 },
        { homeRatePence: 0 },
      ),
    ).toBe('slate')
  })
})
