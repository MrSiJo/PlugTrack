import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

const VARIANT_CLASS = {
  default:
    'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900',
  hero: 'border-cyan-200 bg-gradient-to-br from-white to-slate-50 dark:border-cyan-900/60 dark:from-slate-900 dark:to-[#0a1628] shadow-[0_0_0_1px_rgba(34,211,238,0.05),0_8px_24px_-12px_rgba(34,211,238,0.25)]',
  muted:
    'border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950/40',
} as const

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: keyof typeof VARIANT_CLASS
}

export function Card({
  variant = 'default',
  className,
  ...rest
}: CardProps) {
  return (
    <div
      {...rest}
      className={cn(
        'rounded-lg border p-4 text-sm',
        VARIANT_CLASS[variant],
        className,
      )}
    />
  )
}
