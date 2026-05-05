export interface GroupableSession {
  id: number
  date: string
  cost_pence: number | null
}

export interface MonthGroup<T extends GroupableSession> {
  /** YYYY-MM key, used internally for stable grouping */
  key: string
  /** Display label e.g. "May 2026" */
  label: string
  count: number
  totalCostPence: number
  sessions: T[]
}

const MONTH_LABEL = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const

export function groupSessionsByMonth<T extends GroupableSession>(
  sessions: T[],
): MonthGroup<T>[] {
  const groups: MonthGroup<T>[] = []
  let current: MonthGroup<T> | null = null

  for (const session of sessions) {
    const [yearStr, monthStr] = session.date.split('-')
    if (!yearStr || !monthStr) continue
    const key = `${yearStr}-${monthStr}`
    if (current === null || current.key !== key) {
      const monthIdx = Math.max(0, Math.min(11, parseInt(monthStr, 10) - 1))
      current = {
        key,
        label: `${MONTH_LABEL[monthIdx]} ${yearStr}`,
        count: 0,
        totalCostPence: 0,
        sessions: [],
      }
      groups.push(current)
    }
    current.count += 1
    current.totalCostPence += session.cost_pence ?? 0
    current.sessions.push(session)
  }

  return groups
}
