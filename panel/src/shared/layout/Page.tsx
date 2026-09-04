/**
 * Page layout (CONVENTIONS-CLIENT.md §3). No hard `max-width`: the `viewer`
 * board is a television and a 1280px column in the middle of a 4K screen is
 * the reason that rule exists.
 */
import type { ReactNode } from 'react'

import { cn } from '@/shared/lib/cn'

export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('flex flex-col gap-6 p-6', className)}>{children}</div>
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: ReactNode
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold text-text">{title}</h1>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </header>
  )
}

export function PageGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('grid gap-4 sm:grid-cols-2 xl:grid-cols-3 3xl:grid-cols-4', className)}>
      {children}
    </div>
  )
}
