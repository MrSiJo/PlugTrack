import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

export interface ProgressBarProps extends HTMLAttributes<HTMLDivElement> {
  value: number
  gradient?: boolean
  pulsing?: boolean
}

export function ProgressBar({
  value,
  gradient = true,
  pulsing = false,
  className,
  ...rest
}: ProgressBarProps) {
  const clamped = Math.min(100, Math.max(0, value))
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      {...rest}
      className={cn(
        'h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800',
        className,
      )}
    >
      <div
        className={cn(
          'h-full rounded-full transition-[width] duration-500',
          gradient ? 'bg-gradient-electric' : 'bg-cyan-500',
          pulsing && 'animate-pulse-soft',
        )}
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}
