/**
 * "3 daqiqa oldin" — the Uzbek sentence for `relativeTo`'s language-free
 * answer.
 *
 * Split from `format.ts` on purpose: that file does arithmetic and knows no
 * words, this one only picks a catalogue key. Every page that shows "last
 * heard from" reads the same wording, which matters most on the device pages,
 * where the reader is comparing one phone against another.
 */
import { t } from '@/shared/i18n'
import { relativeTo } from './format'

export function relativeText(iso: string, now: Date = new Date()): string {
  const { unit, value } = relativeTo(iso, now)
  switch (unit) {
    case 'now':
      return t('time.justNow')
    case 'minute':
      return t('time.minutesAgo', { n: value })
    case 'hour':
      return t('time.hoursAgo', { n: value })
    case 'day':
      return t('time.daysAgo', { n: value })
    case 'future':
      // A handset with a wrong clock reports a heartbeat timestamped tomorrow.
      // Saying so is the point: this is the skew, made visible on the page
      // whose job is to show that the phone cannot be trusted about time.
      return t('time.inTheFuture')
  }
}
