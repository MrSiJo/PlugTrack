import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

const SIZE_CLASS = {
  sm: 'text-lg',
  md: 'text-2xl',
  lg: 'text-3xl',
  xl: 'text-5xl',
} as const

export interface GradientNumberProps extends HTMLAttributes<HTMLSpanElement> {
  size?: keyof typeof SIZE_CLASS
}

export function GradientNumber({
  size = 'md',
  className,
  children,
  ...rest
}: GradientNumberProps) {
  return (
    <span
      {...rest}
      className={cn(
        'text-gradient-electric font-bold tabular-nums tracking-tight',
        SIZE_CLASS[size],
        className,
      )}
    >
      {children}
    </span>
  )
}
