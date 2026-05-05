import type { ReactNode } from 'react'
import { Card } from './Card'
import { cn } from '@/lib/cn'

export interface StatTileProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  className?: string
  'data-testid'?: string
}

export function StatTile({
  label,
  value,
  sub,
  className,
  ...rest
}: StatTileProps) {
  return (
    <Card
      data-testid={rest['data-testid']}
      className={cn('flex flex-col gap-1', className)}
    >
      <p className="text-[10px] uppercase tracking-[0.1em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="text-2xl font-semibold tabular-nums tracking-tight text-slate-900 dark:text-slate-100">
        {value}
      </p>
      {sub && (
        <p className="text-xs text-slate-500 dark:text-slate-400">{sub}</p>
      )}
    </Card>
  )
}
