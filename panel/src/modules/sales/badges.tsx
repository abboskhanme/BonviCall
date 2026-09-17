/**
 * The status vocabulary of sales control: verdict, rule, decision.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ⚠️ THE COLOURS DO NOT ACCUSE. A suspicious sale is AMBER, never red: this is
 * a queue to be checked, not a charge. Red appears only after a HUMAN has
 * decided "really suspicious" — so the colour shows the manager's judgement,
 * not the machine's guess.
 *
 * ⚠️ `not_checkable` IS NOT A KIND OF `ok`, and it is not amber either. It is
 * neutral: a measure of SAP's own data quality, which should fall over time.
 * Folding it into "clean" would write "all is well" over the one number that
 * says our records are incomplete.
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * ⚠️ A BADGE CARRIES A CODE, NEVER A SENTENCE. The explanation was tried in
 * the cell: "Oldingi savdo 19/08/2026 — orasida 0 ta suhbat" wrapped to four
 * lines in a narrow column and made that row three times the height of its
 * neighbours. The codes stay here, their meaning goes in `RuleLegend` under
 * the table header — once, for every row — and the full sentence lives in the
 * card.
 */
import { CircleHelp, CircleSlash, ShieldCheck, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'

import { t, type MessageKey } from '@/shared/i18n'
import { Badge } from '@/shared/ui/primitives'

import {
  RULES,
  RULE_LABEL,
  RULE_SHORT,
  SKIP_HINT,
  SKIP_LABEL,
  VERDICT_HINT,
  VERDICT_LABEL,
  type Rule,
  type SaleReview,
  type Verdict,
} from './api'

type Tone = 'neutral' | 'accent' | 'good' | 'warn' | 'bad'

const VERDICT_TONE: Record<Verdict, Tone> = {
  ok: 'good',
  suspicious: 'warn',
  not_checkable: 'neutral',
}

/**
 * A badge with a hover explanation.
 *
 * `Badge` takes no `title` — it is a presentational primitive and gets no
 * props it does not need — so the hint goes on a wrapper. `whitespace-nowrap`
 * is MANDATORY: "Tekshirib bo'lmadi" splits over two lines in a narrow column
 * and takes the whole row's height with it.
 */
function Hinted({
  hint,
  tone,
  children,
}: {
  hint?: string
  tone: Tone
  children: ReactNode
}) {
  return (
    <span className="inline-flex shrink-0" title={hint}>
      <Badge tone={tone} className="whitespace-nowrap">
        {children}
      </Badge>
    </span>
  )
}

const VERDICT_ICON: Record<Verdict, typeof ShieldCheck> = {
  ok: ShieldCheck,
  suspicious: TriangleAlert,
  not_checkable: CircleHelp,
}

export function VerdictBadge({
  verdict,
  skipReason,
}: {
  verdict: Verdict
  /** Why it could not be checked — said plainly in the hover text. */
  skipReason?: string | null
}) {
  const Icon = VERDICT_ICON[verdict]
  // For an unusable row the SPECIFIC cause is more use than the class name, so
  // it wins the hover; otherwise the class explains itself.
  const skip = skipReason ? SKIP_HINT[skipReason] : undefined
  const hint = verdict === 'not_checkable' && skip ? t(skip) : t(VERDICT_HINT[verdict])

  return (
    <Hinted tone={VERDICT_TONE[verdict]} hint={hint}>
      <Icon className="me-1 size-3" aria-hidden />
      {t(VERDICT_LABEL[verdict])}
    </Hinted>
  )
}

/**
 * Why a sale could not be checked — TWO WORDS.
 *
 * The full sentence ("Umumiy kod: bitta kod ostida ko'p mijoz…") becomes a
 * paragraph inside a cell and triples the row height. It is the hover text.
 *
 * Renders nothing for a cause outside the documented set: a raw identifier in
 * a table cell is a bug with a border.
 */
export function SkipBadge({ reason }: { reason: string }) {
  const label = SKIP_LABEL[reason]
  const hint = SKIP_HINT[reason]
  if (!label) return null
  return (
    <Hinted tone="neutral" hint={hint ? t(hint) : undefined}>
      {t(label)}
    </Hinted>
  )
}

/**
 * The broken rules.
 *
 * The badge is the bare code; the meaning is in the hover and, for a
 * touchscreen where there is no hover at all, in `RuleLegend` above the table.
 *
 * ⚠️ An empty list renders NOTHING, not an em dash. A dash fills the row with
 * noise while the verdict badge beside it already says "no rule was broken".
 */
export function RuleBadges({
  rules,
  windowDays,
  hints,
}: {
  rules: Rule[]
  /** R1's window — "the day of the sale and the N days before it". */
  windowDays?: number
  /** The EVIDENCE for a rule, appended to the hover. The question "when was
   *  the previous sale?" arrives the moment the badge is seen, and the cell
   *  has no room for the answer. */
  hints?: Partial<Record<Rule, string>>
}) {
  if (!rules.length) return null

  return (
    <span className="inline-flex shrink-0 items-center gap-1">
      {rules.map((rule) => {
        const base =
          rule === 'R1' && windowDays
            ? t('sales.rule.R1window', { count: windowDays })
            : t(RULE_LABEL[rule])
        const hint = hints?.[rule]
        return (
          <Hinted key={rule} tone="warn" hint={hint ? `${base} — ${hint}` : base}>
            {rule}
          </Hinted>
        )
      })}
    </span>
  )
}

/**
 * What the codes mean — ONE line under the table header.
 *
 * ⚠️ IT SITS OUTSIDE THE TABLE. The table scrolls horizontally in its own
 * container, which clips a native tooltip, and on a touchscreen a tooltip
 * never opens at all. Three short clauses fit on one line and are readable
 * without hovering anything.
 */
export function RuleLegend({ windowDays }: { windowDays?: number }) {
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs leading-relaxed text-muted">
      {RULES.map((rule, index) => (
        <span key={rule} className="inline-flex items-center gap-1.5">
          {index > 0 ? (
            <span className="text-muted/40" aria-hidden>
              ·
            </span>
          ) : null}
          <span
            className="font-semibold text-warn"
            title={
              rule === 'R1' && windowDays
                ? t('sales.rule.R1window', { count: windowDays })
                : t(RULE_LABEL[rule])
            }
          >
            {rule}
          </span>
          <span>— {t(RULE_SHORT[rule])}</span>
        </span>
      ))}
    </p>
  )
}

/**
 * The manager's decision.
 *
 * `null` is a STATE, not a blank: "nobody has looked at this yet" and "the
 * data failed to load" must not look the same, so the undecided case is
 * written out too.
 */
export function ReviewBadge({ review }: { review?: SaleReview | null }) {
  if (!review) {
    return (
      <Hinted tone="accent">
        <CircleSlash className="me-1 size-3" aria-hidden />
        {t('sales.review.new')}
      </Hinted>
    )
  }

  const justified = review.status === 'justified'
  const label: MessageKey = justified ? 'sales.review.justified' : 'sales.review.confirmed'
  const Icon = justified ? ShieldCheck : TriangleAlert

  return (
    <Hinted tone={justified ? 'good' : 'bad'} hint={review.note ?? undefined}>
      <Icon className="me-1 size-3" aria-hidden />
      {t(label)}
    </Hinted>
  )
}
