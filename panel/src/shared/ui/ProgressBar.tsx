/**
 * A proportion bar, without an inline style.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Tailwind generates classes by scanning source, so `w-[47%]` works only when
 * those exact characters appear in a file — a computed width cannot become a
 * class, and `style={{ width }}` is forbidden (CONVENTIONS-CLIENT.md §11).
 *
 * So the width is quantised to 5% steps and looked up in a table that is
 * written out literally. Twenty-one classes is more than enough resolution for
 * a bar somebody reads at a glance, and the number beside it always carries
 * the exact value — the bar is the shape of the answer, not the answer.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { cn } from '@/shared/lib/cn'
import { widthClass } from '@/shared/lib/widthClass'

type BarTone = 'accent' | 'good' | 'warn' | 'bad'

const TONE_CLASS: Record<BarTone, string> = {
  accent: 'bg-accent',
  good: 'bg-good',
  warn: 'bg-warn',
  bad: 'bg-bad',
}

export function ProgressBar({
  fraction,
  tone = 'accent',
  label,
}: {
  fraction: number
  tone?: BarTone
  /** Read out to assistive technology, which cannot see a bar at all. */
  label: string
}) {
  const percent = Math.round(Math.max(0, Math.min(1, fraction)) * 100)
  return (
    <div
      className="h-2 w-full overflow-hidden rounded-sm bg-surface-2"
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div className={cn('h-full', TONE_CLASS[tone], widthClass(fraction))} />
    </div>
  )
}
