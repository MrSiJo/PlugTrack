import { describe, expect, it } from 'vitest'
import { groupSessionsByMonth } from './groupSessionsByMonth'
import type { GroupableSession } from './groupSessionsByMonth'

function s(id: number, date: string, costPence: number | null): GroupableSession {
  return { id, date, cost_pence: costPence }
}

describe('groupSessionsByMonth', () => {
  it('returns an empty array for empty input', () => {
    expect(groupSessionsByMonth([])).toEqual([])
  })

  it('groups a single month with totals', () => {
    const groups = groupSessionsByMonth([
      s(1, '2026-05-05', 400),
      s(2, '2026-05-01', 600),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]?.label).toBe('May 2026')
    expect(groups[0]?.count).toBe(2)
    expect(groups[0]?.totalCostPence).toBe(1000)
    expect(groups[0]?.sessions.map((x) => x.id)).toEqual([1, 2])
  })

  it('preserves input order across months (assumed pre-sorted desc)', () => {
    const groups = groupSessionsByMonth([
      s(1, '2026-05-05', 400),
      s(2, '2026-04-28', 800),
      s(3, '2026-04-01', 100),
    ])
    expect(groups.map((g) => g.label)).toEqual(['May 2026', 'Apr 2026'])
    expect(groups[0]?.count).toBe(1)
    expect(groups[1]?.count).toBe(2)
    expect(groups[1]?.totalCostPence).toBe(900)
  })

  it('handles year boundary', () => {
    const groups = groupSessionsByMonth([
      s(1, '2026-01-05', 100),
      s(2, '2025-12-30', 200),
    ])
    expect(groups.map((g) => g.label)).toEqual(['Jan 2026', 'Dec 2025'])
  })

  it('treats null cost as zero in totals', () => {
    const groups = groupSessionsByMonth([
      s(1, '2026-05-05', null),
      s(2, '2026-05-01', 200),
    ])
    expect(groups[0]?.totalCostPence).toBe(200)
  })
})
