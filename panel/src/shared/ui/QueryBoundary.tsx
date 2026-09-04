/**
 * Loading, empty and error have ONE answer, not twenty
 * (CONVENTIONS-CLIENT.md §2).
 *
 * A page passes its query result in and renders only the success branch. The
 * check that keeps this honest is
 * `grep -rn "isLoading\|isPending" panel/src/modules/` → empty, and ESLint
 * enforces it as well.
 *
 * *This is new.* BonviZvonki handles `isLoading` 67 times across 33 files with
 * no convention, so every page's empty state looks slightly different.
 *
 * Empty states are explicit and are NOT interchangeable (SPEC §5.3): "no calls
 * yet", "nothing matches this filter" and "this device has never connected" are
 * three different sentences, so `emptyTitle` is a prop the page supplies rather
 * than one generic line owned by this component.
 */
import type { UseQueryResult } from '@tanstack/react-query'
import { AlertTriangle, Inbox } from 'lucide-react'
import type { ReactNode } from 'react'

import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { Button, Card, Skeleton } from './primitives'

export function LoadingState({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('space-y-2', className)} data-testid="query-loading">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-12 w-full" />
      ))}
    </div>
  )
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <Card className="flex flex-col items-center gap-2 p-10 text-center" data-testid="query-empty">
      <Inbox className="size-8 text-muted" aria-hidden />
      <p className="text-sm font-medium text-text">{title}</p>
      {hint ? <p className="max-w-md text-xs text-muted">{hint}</p> : null}
      {action}
    </Card>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <Card className="flex flex-col items-center gap-3 p-10 text-center" data-testid="query-error">
      <AlertTriangle className="size-8 text-bad" aria-hidden />
      <p className="text-sm font-medium text-text">{t('common.errorTitle')}</p>
      <p className="max-w-md text-xs text-muted">{messageForError(error)}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      ) : null}
    </Card>
  )
}

export interface QueryBoundaryProps<TData> {
  query: UseQueryResult<TData>
  /** What "there is nothing here" means for this data. Default: no check. */
  isEmpty?: (data: TData) => boolean
  /** The empty sentence for THIS page. Explicit on purpose (SPEC §5.3). */
  emptyTitle?: string
  emptyHint?: string
  emptyAction?: ReactNode
  skeletonRows?: number
  children: (data: TData) => ReactNode
}

export function QueryBoundary<TData>({
  query,
  isEmpty,
  emptyTitle,
  emptyHint,
  emptyAction,
  skeletonRows,
  children,
}: QueryBoundaryProps<TData>) {
  if (query.isPending) return <LoadingState rows={skeletonRows} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  const data = query.data as TData
  if (isEmpty?.(data)) {
    return (
      <EmptyState title={emptyTitle ?? t('common.empty')} hint={emptyHint} action={emptyAction} />
    )
  }
  return <>{children(data)}</>
}
