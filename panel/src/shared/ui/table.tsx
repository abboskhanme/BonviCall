/**
 * Table primitives.
 *
 * Every list page in SPEC §5.2 — calls, agents, numbers, devices, alerts,
 * audit, users, app versions — renders the same table, so it lives in
 * `shared/ui` rather than being re-invented per module
 * (CONVENTIONS-CLIENT.md §1). Colour comes from the tokens only: no hex, no
 * `dark:` variant, no inline style (§3).
 *
 * The wrapper scrolls horizontally instead of the page: a call row carries
 * seven columns and a narrow laptop must not hide the audio state, which is
 * the column the page exists for.
 */
import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from 'react'

import { cn } from '@/shared/lib/cn'

export function TableWrap({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('overflow-x-auto rounded-xl border border-border bg-surface', className)}>
      {children}
    </div>
  )
}

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return <table className={cn('w-full border-collapse text-sm', className)} {...props} />
}

export function THead({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn('border-b border-border bg-surface-2 text-start text-muted', className)}
      {...props}
    />
  )
}

export function TBody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('divide-y divide-border', className)} {...props} />
}

export interface TRProps extends HTMLAttributes<HTMLTableRowElement> {
  /** Renders the row as a keyboard-reachable link target. */
  interactive?: boolean
}

export function TR({ interactive = false, className, ...props }: TRProps) {
  return (
    <tr
      className={cn(
        interactive &&
          'cursor-pointer transition-colors hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none',
        className,
      )}
      {...props}
    />
  )
}

export function TH({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn('whitespace-nowrap px-3 py-2 text-start text-2xs font-semibold uppercase tracking-wide', className)}
      {...props}
    />
  )
}

export function TD({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('px-3 py-2 align-middle text-text', className)} {...props} />
}
