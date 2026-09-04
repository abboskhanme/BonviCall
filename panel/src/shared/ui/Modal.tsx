/**
 * Create and edit happen ONLY here (CONVENTIONS-CLIENT.md §3, SPEC §5).
 * An inline form on a page is a house-convention violation; T88 already
 * assumes every agent/number form is a modal.
 */
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { FormEvent, ReactNode } from 'react'

import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { Button } from './primitives'

export interface ModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  children: ReactNode
  /** The confirm button. Omit for a read-only dialog. */
  onSubmit?: (event: FormEvent<HTMLFormElement>) => void
  submitLabel?: string
  submitting?: boolean
  submitDisabled?: boolean
  danger?: boolean
  className?: string
}

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  onSubmit,
  submitLabel,
  submitting = false,
  submitDisabled = false,
  danger = false,
  className,
}: ModalProps) {
  const body = (
    <>
      <div className="space-y-4 px-5 py-4">{children}</div>
      <footer className="flex justify-end gap-2 border-t border-border px-5 py-3">
        <Dialog.Close asChild>
          <Button variant="ghost">{t('common.cancel')}</Button>
        </Dialog.Close>
        {onSubmit ? (
          <Button
            type="submit"
            variant={danger ? 'danger' : 'primary'}
            disabled={submitting || submitDisabled}
          >
            {submitLabel ?? t('common.save')}
          </Button>
        ) : null}
      </footer>
    </>
  )

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-text/30 backdrop-blur-sm" />
        <Dialog.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 w-[min(32rem,calc(100vw-2rem))]',
            '-translate-x-1/2 -translate-y-1/2 rounded-xl border border-border',
            'bg-surface shadow-pop',
            className,
          )}
        >
          <header className="flex items-start justify-between gap-4 border-b border-border px-5 py-3">
            <div>
              <Dialog.Title className="text-sm font-semibold text-text">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="mt-1 text-xs text-muted">
                  {description}
                </Dialog.Description>
              ) : null}
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="sm" aria-label={t('common.close')} className="px-2">
                <X className="size-4" aria-hidden />
              </Button>
            </Dialog.Close>
          </header>
          {onSubmit ? <form onSubmit={onSubmit}>{body}</form> : body}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

/** One labelled field. Modals are built from these, not from ad-hoc markup. */
export function ModalField({
  htmlFor,
  label,
  error,
  children,
}: {
  htmlFor: string
  label: string
  error?: string
  children: ReactNode
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted">
        {label}
      </label>
      {children}
      {error ? <p className="text-2xs text-bad">{error}</p> : null}
    </div>
  )
}

export function ModalFields({ children }: { children: ReactNode }) {
  return <div className="space-y-4">{children}</div>
}
