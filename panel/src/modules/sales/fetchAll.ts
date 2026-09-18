/**
 * Every row the filter selects — not the page on screen.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * WHY THIS EXISTS. The table shows 50 rows. An export of those 50 would answer
 * "there are 12 suspicious sales" when the filter holds 451 — a false
 * conclusion in a file that gets emailed on. Every sales export therefore
 * reads the WHOLE selection through this walker first.
 *
 * ⚠️ REWRITTEN FOR A CURSOR, not ported. BonviZvonki asked for
 * `page` / `page_size` and stopped when it had `total` rows. This list is
 * keyset-paged on `(occurred_on, id)` and has no page number
 * (`api.ts::useCompliance` says why: deciding on a sale removes it from the
 * default set, so every later OFFSET page shifts by one and a sale is never
 * seen at all). The walk follows `next_cursor` instead, which is stable under
 * exactly that edit.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { api, type Query } from '@/shared/api/client'

import type {
  ComplianceItem,
  ComplianceList,
  ComplianceQuery,
  ComplianceScope,
  ComplianceTimeline,
  TimelineQuery,
} from './api'

/**
 * Rows per request while walking.
 *
 * The server clamps `limit` to `MAX_LIMIT = 200` (`core/pagination.py`), so
 * this is the largest page it will serve: 20,000 rows are 100 requests, and
 * asking for more per request would simply be clamped back to this.
 */
export const BATCH = 200

/**
 * The most rows a file will ever hold.
 *
 * ⚠️ A CAP, NOT A GUESS, and the caller is TOLD when it bites (`truncated`).
 * A browser building a spreadsheet holds every row in memory and the library
 * holds them again while it writes; a filter accidentally set to five years
 * would otherwise take the tab down. 20,000 is the source's number and about
 * a year and a half of this company's sales.
 */
export const MAX_ROWS = 20_000

export interface AllCompliance {
  rows: ComplianceItem[]
  /** What the server said the filter holds, when it was asked for a count. */
  total: number | null
  /** The cap cut the list. Stated, or the file would quietly be incomplete. */
  truncated: boolean
}

/** A generated query object as `client.ts` wants it (`api.ts::toQuery`). */
function toQuery(params: ComplianceQuery | ComplianceScope | TimelineQuery): Query {
  return { ...params }
}

/**
 * Walk the whole selection.
 *
 * `params` is the screen's own filter. Its `cursor`, `limit` and `with_total`
 * are overwritten here: the file is the filter's rows from the beginning,
 * never the page the reader happens to be standing on.
 *
 * Three ways this stops, and all three are deliberate:
 *   - `has_more` is false — the end, the ordinary case;
 *   - the cap is reached — `truncated: true`, and the caller says so in the
 *     file and on screen;
 *   - the server repeats a cursor or answers an empty page while still
 *     claiming more. That is a server fault, and the alternative to stopping
 *     is a tab that spins for ever.
 */
export async function fetchAllCompliance(
  params: ComplianceQuery,
  { batch = BATCH, maxRows = MAX_ROWS }: { batch?: number; maxRows?: number } = {},
): Promise<AllCompliance> {
  const rows: ComplianceItem[] = []
  let cursor: string | undefined
  let total: number | null = null
  const seen = new Set<string>()

  for (;;) {
    const page: ComplianceList = await api.get<ComplianceList>(
      '/sales/compliance',
      toQuery({
        ...params,
        limit: batch,
        // Only the first request pays for the count.
        with_total: cursor === undefined,
        /* ⚠️ ALWAYS WRITTEN, never spread in conditionally. `params` is the
           screen's own filter and carries the cursor of the page the reader
           is standing on; a conditional spread leaves it in place on the first
           request, and the file then starts at page five and silently misses
           everything before it. `undefined` is dropped by `buildUrl`. */
        cursor,
      }),
    )
    if (typeof page.total === 'number') total = page.total
    rows.push(...page.items)

    if (rows.length >= maxRows) return { rows: rows.slice(0, maxRows), total, truncated: true }
    if (!page.has_more || !page.next_cursor) break
    if (!page.items.length) break
    if (seen.has(page.next_cursor)) break
    seen.add(page.next_cursor)
    cursor = page.next_cursor
  }

  return { rows, total, truncated: false }
}

/**
 * The per-customer chains for the suspicious-sales report.
 *
 * Not the panel's `useSaleTimeline` hook: this is a one-off read at the moment
 * a button is pressed, and caching a 1,000-customer answer beside the card's
 * own ±30-day chain would evict it.
 *
 * ⚠️ `only_suspicious: false` IS DELIBERATE. The manager's question is "how
 * many customers did this employee work with, and in how many of them is there
 * a doubt" — which needs the clean customers too. Without them the "customers"
 * column would repeat the suspicious count and quietly lie.
 *
 * ⚠️ `max_clients: 1000` is the endpoint's own ceiling, not a guess: three
 * weeks of this company's sales reach 467 customers and the server's default of
 * 300 would cut the list in silence. When it does cut, the answer says
 * `truncated` and the report prints that on the sheet.
 */
export function fetchComplianceTimeline(scope: ComplianceScope): Promise<ComplianceTimeline> {
  /* Typed as the endpoint's OWN generated query, with no cast: a parameter the
     server renames is then a compile error here rather than a filter silently
     dropped on the wire. */
  const params: TimelineQuery = { ...scope, only_suspicious: false, max_clients: 1000 }
  return api.get<ComplianceTimeline>('/sales/compliance/timeline', toQuery(params))
}
