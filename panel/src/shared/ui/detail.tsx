/**
 * The label/value pairs every detail page is built from.
 *
 * Extracted from `modules/calls/CallDetailPage.tsx`, which built them first;
 * the call card, the agent card and the device card all render the same thing
 * and must render it identically (CONVENTIONS-CLIENT.md §1).
 *
 * A value that is absent renders an em dash, never an empty cell: "we have no
 * reading for this" and "there is nothing here" look the same when both are
 * blank, and on a device page the difference is the whole point.
 */
import type { ReactNode } from 'react'

import { EM_DASH } from '@/shared/lib/format'
import { cn } from '@/shared/lib/cn'
import { Card } from './primitives'

export function Field({
  label,
  value,
  title,
  mono = false,
  children,
}: {
  label: string
  value?: string | null
  title?: string
  mono?: boolean
  /** For a value that is a badge or a link rather than text. */
  children?: ReactNode
}) {
  return (
    <div className="min-w-0">
      <dt className="text-2xs font-medium uppercase tracking-wide text-muted">{label}</dt>
      <dd
        className={cn('text-sm text-text', mono && 'truncate font-mono')}
        title={title}
      >
        {children ?? value ?? EM_DASH}
      </dd>
    </div>
  )
}

export function FieldGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <dl className={cn('grid gap-4 sm:grid-cols-2 xl:grid-cols-3', className)}>{children}</dl>
  )
}

export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <Card className={cn('p-4', className)}>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-text">{title}</h2>
          {description ? <p className="mt-0.5 text-xs text-muted">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </Card>
  )
}
