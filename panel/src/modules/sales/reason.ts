/**
 * "Why is this suspicious" — ONE sentence, assembled from the evidence.
 *
 * ⚠️ WHY IT EXISTS. The table carries `R1`/`R2`/`R3` and those codes explain
 * nothing on their own: even a reader who knows them has to open the row to
 * learn WHICH two sales had no conversation between them. A company director
 * opens this screen too, and will not spend time decoding a column — so the
 * MEANING is carried by a sentence, and the badges stay beside it for whoever
 * is doing the analysis.
 *
 * ⚠️ THE SENTENCE IS BUILT FROM FACTS, never invented: the date, the day count
 * and the previous sale are all fields of the response. A manager can read it
 * and check it against SAP on the spot.
 *
 * ⚠️ ORDER — STRONGEST FIRST: R3 → R1 → R2. A row can break several rules, but
 * there is only ever ONE sentence: beside "we have never spoken to this
 * customer", "no call before the sale" is noise.
 *
 * ⚠️ THE SENTENCE NEVER GOES IN A TABLE CELL. It was tried: "Oldingi savdo
 * 19/08/2026 — orasida 0 ta suhbat" wrapped to four lines in a narrow column
 * and made that row three times the height of its neighbours. It belongs to
 * the card and the attention list, both of which have the width.
 */
import { t } from '@/shared/i18n'

import { formatSaleDate } from './saleDate'
import type { Rule, Verdict } from './api'

/**
 * Enough facts for the sentence, deliberately NOT `ComplianceItem`.
 *
 * The same fields ride on the timeline's sale events, and both screens have to
 * produce the SAME sentence for the same sale. Two texts would be two truths.
 */
export interface SaleFacts {
  /** `YYYY-MM-DD` — no clock. */
  occurred_on: string
  verdict: Verdict
  broken_rules: Rule[]
  skip_reason?: string | null
  last_call_at?: string | null
  last_call_agent?: string | null
  days_before?: number | null
  previous_sale_on?: string | null
}

/**
 * The sentence for one sale.
 *
 * `windowDays` comes from the RESPONSE (`window_days`), never from a constant
 * here: the setting can change, and a number copied into the panel would be a
 * second truth that drifts from the first.
 */
export function saleReason(sale: SaleFacts, windowDays?: number): string {
  /* Not checkable — the cause is in SAP's data, not in the sale. That is NOT
     the same as clean, and the sentence says so. */
  if (sale.verdict === 'not_checkable') {
    if (sale.skip_reason === 'generic_code') return t('sales.why.genericCode')
    if (sale.skip_reason === 'no_phone') return t('sales.why.noPhone')
    return t('sales.verdictHint.not_checkable')
  }

  const rules = sale.broken_rules

  // R3 — the strongest: not one conversation in the whole history.
  if (rules.includes('R3')) return t('sales.why.never')

  // R1 — nothing inside the window before the sale. When a conversation DID
  // happen, just outside it, its date is given: that number is the answer to
  // the manager's actual question.
  if (rules.includes('R1')) {
    return sale.last_call_at
      ? t('sales.why.noCallBefore', {
          count: sale.days_before ?? 0,
          date: formatSaleDate(sale.last_call_at),
        })
      : t('sales.why.noCallWindow', { count: windowDays ?? 0 })
  }

  // R2 — no conversation between two sales. Both dates are named, or "which
  // two?" is left hanging.
  if (rules.includes('R2')) {
    return sale.previous_sale_on
      ? t('sales.why.betweenSales', {
          from: formatSaleDate(sale.previous_sale_on),
          to: formatSaleDate(sale.occurred_on),
        })
      : t('sales.rule.R2')
  }

  /* Clean, and said out loud. An empty cell would read as "not checked", when
     in fact there is evidence here. */
  if (sale.last_call_at) {
    const date = formatSaleDate(sale.last_call_at)
    return sale.last_call_agent
      ? t('sales.why.ok', { date, agent: sale.last_call_agent })
      : t('sales.why.okShort', { date })
  }

  return t('sales.verdictHint.ok')
}
