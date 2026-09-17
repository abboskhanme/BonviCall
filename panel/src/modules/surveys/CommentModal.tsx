/**
 * One customer's rating in full — the stars, the ticks and the whole comment.
 *
 * A read-only dialog rather than an expanding row: a comment can be several
 * paragraphs, and a list that changes height as somebody reads down it loses
 * their place.
 *
 * The header repeats the anonymity line. It is the sentence that was promised
 * to the customer in their own chat, and the person reading this is the one it
 * constrains.
 */
import { Flag } from 'lucide-react'

import { t } from '@/shared/i18n'
import { formatDateTime } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/primitives'
import { Modal } from '@/shared/ui/Modal'

import { RedFlagChips } from './RedFlagChips'
import { Stars } from './Stars'
import type { FeedbackItem } from './api'

const RESOLUTION_TONE = {
  yes: 'good',
  partial: 'warn',
  no: 'bad',
} as const

const RESOLUTION_LABEL = {
  yes: 'surveys.resolution.yes',
  partial: 'surveys.resolution.partial',
  no: 'surveys.resolution.no',
} as const

export function CommentModal({
  item,
  showAgent,
  flagLabel,
  onClose,
}: {
  item: FeedbackItem | null
  showAgent: boolean
  flagLabel: (key: string) => string
  onClose: () => void
}) {
  const flags = item?.red_flags ?? []
  const resolution = item?.resolution as keyof typeof RESOLUTION_LABEL | null | undefined

  return (
    <Modal
      open={item !== null}
      onOpenChange={(open) => !open && onClose()}
      title={t('surveys.commentTitle')}
      description={t('surveys.anonymous')}
    >
      {item ? (
        <>
          <div className="flex flex-wrap items-center gap-2.5">
            <Stars value={item.csat} size="md" />
            <span className="text-sm font-semibold tabular-nums text-text">
              {t('surveys.starsOf', { value: item.csat })}
            </span>
            {resolution ? (
              <Badge tone={RESOLUTION_TONE[resolution]}>
                {t('surveys.resolutionLabel')}: {t(RESOLUTION_LABEL[resolution])}
              </Badge>
            ) : null}
          </div>

          {/* The full list here, never truncated — the card above already
              showed the first three and a count. */}
          {flags.length > 0 ? (
            <div className="rounded-md bg-bad/[0.06] p-3">
              <div className="mb-2 flex items-center gap-1.5 text-2xs font-medium text-bad">
                <Flag className="size-3" aria-hidden />
                {t('surveys.redFlags')}
              </div>
              <RedFlagChips keys={flags} flagLabel={flagLabel} />
            </div>
          ) : null}

          <p className="whitespace-pre-line text-sm leading-relaxed text-text">
            {item.comment ?? t('surveys.noComment')}
          </p>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border pt-3 text-2xs text-muted">
            {showAgent ? (
              <span className="font-medium text-text">{item.agent_name}</span>
            ) : null}
            <span className="ms-auto tabular-nums">{formatDateTime(item.responded_at)}</span>
          </div>
        </>
      ) : null}
    </Modal>
  )
}
