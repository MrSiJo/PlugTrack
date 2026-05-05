import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

const TONE_CLASS = {
  slate: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  cyan: 'bg-cyan-100 text-cyan-800 dark:bg-cyan-950/60 dark:text-cyan-300',
  green:
    'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300',
  amber: 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300',
  purple:
    'bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300',
  red: 'bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300',
} as const

export type PillTone = keyof typeof TONE_CLASS

export interface PillProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: PillTone
}

export function Pill({
  tone = 'slate',
  className,
  children,
  ...rest
}: PillProps) {
  return (
    <span
      {...rest}
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium tracking-wide',
        TONE_CLASS[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
