/**
 * "Who made this sale" — one answer, from two sources.
 *
 * ⚠️ SAP's `Подразделение` IS THE EMPLOYEE, not a branch. People are written
 * there under the name of the territory they work ("Нукус", "Бухоро",
 * "Телефон савдо") and sometimes under their own ("Зухриддин"). So the word
 * "branch" appears nowhere on the row or in the card: there is ONE column, and
 * it is the employee.
 *
 * ⚠️ NOT TWO LINES. The source once put "Filial: Зухриддин" next to "Xodim:
 * biriktirilmagan" and the screen contradicted itself — a person's name labelled
 * as a branch, and the employee said to be missing. One name now, with the
 * unlinked state as the note under it.
 *
 * ⚠️ UNLINKED IS NEVER HIDDEN. With no employee card in the system the sale
 * falls out of the per-employee cut entirely, so saying nothing would lose it
 * quietly. The note is drawn in the warning tone for exactly that reason.
 */
import { t } from '@/shared/i18n'

/**
 * The facts this needs, deliberately NOT `ComplianceItem`.
 *
 * The timeline's client rows and the card render the same name from the same
 * two fields, and two screens showing one sale under two names is the defect
 * this narrow type prevents.
 */
export interface SellerFacts {
  /** SAP's own name — a territory, or a person. */
  branch?: string | null
  /** The employee card in this system, when one was matched. */
  agent_name?: string | null
}

/** The name to show. `null` — neither SAP nor we have one. */
export function sellerName(row: SellerFacts): string | null {
  return row.agent_name || row.branch || null
}

/**
 * The note under the name, or `null` when none is needed.
 *
 * Two cases: unlinked (a warning), or both names known but DIFFERENT — and
 * then SAP's own wording is printed too, because without it the manager cannot
 * find the row in SAP.
 */
export function sellerHint(row: SellerFacts): string | null {
  if (!row.agent_name) return row.branch ? t('sales.notLinked') : null
  if (row.branch && row.branch !== row.agent_name) {
    return t('sales.sapName', { name: row.branch })
  }
  return null
}

/** Whether the note is a warning — the unlinked case only. */
export function sellerUnlinked(row: SellerFacts): boolean {
  return !row.agent_name && Boolean(row.branch)
}
