import type { ReactNode } from 'react'

export interface EmptyStateProps {
  title: string
  body?: ReactNode
  icon?: ReactNode
  action?: ReactNode
}

export function EmptyState({ title, body, icon, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center dark:border-slate-700 dark:bg-slate-900">
      {icon && (
        <div className="text-slate-400 dark:text-slate-500">{icon}</div>
      )}
      <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
        {title}
      </h3>
      {body && (
        <p className="max-w-md text-sm text-slate-500 dark:text-slate-400">
          {body}
        </p>
      )}
      {action}
    </div>
  )
}
