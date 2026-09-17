/**
 * The misconduct criteria a customer ticked, as chips.
 *
 * ⚠️ **The labels come from the server on every render** — this component
 * holds no list, and neither does its module. A criterion added on the server
 * appears here without a panel deploy, which is the whole reason the registry
 * is an endpoint. A key whose label has not arrived renders as the key rather
 * than disappearing.
 *
 * ═══ Why one tone and not a colour per criterion ═══════════════════════════
 * BonviZvonki hashes the key into an eight-colour palette so each criterion
 * gets its own hue. That needs `style={{ background }}` with a computed hex —
 * forbidden here (CONVENTIONS-CLIENT.md §11), and `style={{...}}` appears
 * nowhere else in this panel. It also spent eight colours distinguishing
 * things that mean the same thing: **every one of these is a complaint**, and
 * a palette that makes "was rude" visually distinct from "never called back"
 * implies a ranking nobody defined. One `bad` token, and the LABEL carries the
 * difference.
 */
import { t } from '@/shared/i18n'

export function RedFlagChips({
  keys,
  flagLabel,
  max,
}: {
  keys: string[]
  flagLabel: (key: string) => string
  /** A card has room for a few; the rest collapse into a count. */
  max?: number
}) {
  if (keys.length === 0) return null
  const shown = max ? keys.slice(0, max) : keys
  const hidden = keys.length - shown.length

  return (
    <div className="flex flex-wrap items-center gap-1">
      {shown.map((key) => (
        <span
          key={key}
          title={flagLabel(key)}
          className="inline-flex items-center gap-1 rounded-full bg-bad/10 px-2 py-0.5 text-2xs font-medium text-bad"
        >
          <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-bad" />
          {flagLabel(key)}
        </span>
      ))}
      {hidden > 0 ? (
        <span className="rounded-full bg-bad/10 px-2 py-0.5 text-2xs font-medium text-bad">
          {t('surveys.redFlagCount', { count: hidden })}
        </span>
      ) : null}
    </div>
  )
}
