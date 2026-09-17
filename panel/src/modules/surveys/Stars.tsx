/**
 * A 1-5 star reading.
 *
 * Rounded to whole stars: the average is shown as a number beside this, so the
 * stars are the glance and the number is the fact. Half-star rendering would
 * need a clip path and would tell the reader nothing the number does not.
 *
 * Colour comes from the `warn` token — the same amber every rating surface in
 * this panel uses — and never from a hex literal (CONVENTIONS-CLIENT.md §11).
 */
import { Star } from 'lucide-react'

import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'

export function Stars({ value, size = 'sm' }: { value: number; size?: 'sm' | 'md' }) {
  const filled = Math.round(value)
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={t('surveys.stars', { count: filled })}>
      {[1, 2, 3, 4, 5].map((star) => (
        <Star
          key={star}
          aria-hidden
          className={cn(
            size === 'md' ? 'size-4' : 'size-3.5',
            star <= filled ? 'fill-warn text-warn' : 'text-muted/40',
          )}
        />
      ))}
    </span>
  )
}
