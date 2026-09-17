/**
 * Sales control — TanStack Query hooks and nothing else
 * (CONVENTIONS-CLIENT.md §1).
 *
 * Module mapping: the panel's `sales` module reads the server's `sales` module
 * (`server/src/api/panel/sales.py`) **one to one**.
 *
 * Ported from `../BonviZvonki/services/web/src/modules/sales/api.ts`, which
 * hand-wrote sixteen response interfaces. Not one of them survives: every type
 * below comes from `types.gen.ts` (CONVENTIONS.md §1), so a renamed server
 * field is a compile error here rather than a `NaN` in a spreadsheet somebody
 * emails to a manager.
 *
 * ⚠️ THE VERDICT IS NOT STORED. It is recomputed on every request, because a
 * call can sync AFTER the sale it belongs to and a "suspicious" written into a
 * column would then be a lie. Two consequences for this file: nothing here is
 * cached for long, and every mutation invalidates the whole module.
 *
 * Access: `reports:read` to read, `settings:write` to import or to take a
 * customer or a branch out of scope, `calls:note` to record a decision. The
 * `sales` ROLE holds none of the three — this is a check carried out ON
 * salespeople, so it is not a page they open. This module hides buttons, which
 * is presentation; the server refuses regardless (CONVENTIONS-CLIENT.md §2).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api, type Query } from '@/shared/api/client'
import { moduleKey, queryKey } from '@/shared/api/queryKeys'
import type { components, operations } from '@/shared/api/types.gen'

export type ComplianceList = components['schemas']['ComplianceListResponse']
export type ComplianceItem = components['schemas']['ComplianceItem']
export type ComplianceSummary = components['schemas']['ComplianceSummaryResponse']
export type AgentBreakdown = components['schemas']['AgentBreakdownOut']
export type ComplianceTimeline = components['schemas']['ComplianceTimelineResponse']
export type TimelineClient = components['schemas']['TimelineClientOut']
export type TimelineEvent = components['schemas']['TimelineEventOut']
export type SaleBranchList = components['schemas']['SaleBranchListResponse']
export type SaleBranch = components['schemas']['SaleBranchOut']
export type SaleReview = components['schemas']['SaleReviewOut']
export type SaleReviewStatus = components['schemas']['SaleReviewStatus']
export type SaleReviewReason = components['schemas']['SaleReviewReason']
export type PartnerExclusion = components['schemas']['PartnerExclusionResponse']
export type ImportPreview = components['schemas']['ImportPreviewResponse']
export type ImportReport = components['schemas']['ImportReportResponse']
export type PreviewWarning = components['schemas']['PreviewWarningOut']
export type PreviewTypeCount = components['schemas']['PreviewTypeCount']
export type PreviewDayCount = components['schemas']['PreviewDayCount']
export type DigestTest = components['schemas']['DigestTestResponse']
export type ClientKind = components['schemas']['ClientKind']
export type Verdict = components['schemas']['Verdict']
export type Rule = components['schemas']['Rule']
export type ReviewState = components['schemas']['ReviewState']

/**
 * ⚠️ THREE QUERY TYPES, AND THE SPLIT IS THE POINT.
 *
 * The summary deliberately accepts NEITHER `verdict`, `rule`, `review` nor
 * `over_limit`. All three class counts have to stay on the screen: picking
 * "suspicious" would otherwise drop two of the three cards to zero, and
 * "how many could not be checked" — the measure of SAP's own data quality —
 * would have no answer at all.
 *
 * BonviZvonki enforced that by destructuring the unwanted keys back out of one
 * shared object, which works only as long as nobody adds a fourth. Here the
 * SCOPE is its own generated type, so a filter that narrows the list cannot
 * reach the counts: it would not compile.
 */
export type ComplianceScope = NonNullable<
  operations['compliance_summary_api_v1_sales_compliance_summary_get']['parameters']['query']
>

export type ComplianceQuery = NonNullable<
  operations['compliance_api_v1_sales_compliance_get']['parameters']['query']
>

export type TimelineQuery = NonNullable<
  operations['compliance_timeline_api_v1_sales_compliance_timeline_get']['parameters']['query']
>

/**
 * Rows per page — fixed, not a picker.
 *
 * The source shipped a "20 / 50" choice and the manager had it removed
 * (24.08.2026): it answered no question anybody asked, 20 rows did not fill a
 * screen, and the choice reset to 20 on every reload. 50 is also what `/calls`
 * and `/clients` use, so the three list pages page alike.
 */
export const PAGE_SIZE = 50

/** The three classes, in the order the cards are drawn. */
export const VERDICTS: readonly Verdict[] = ['ok', 'suspicious', 'not_checkable']

/** The three rules, always in this order — so badges do not move about. */
export const RULES: readonly Rule[] = ['R1', 'R2', 'R3']

/**
 * The review filter, queue first.
 *
 * ⚠️ "Hammasi" is an EXPLICIT value (`all`), never an omitted parameter: the
 * server's default is `new`, so an empty query means "undecided", not
 * "everything", and a picker reading "Hammasi" while the server served the
 * queue would simply be lying.
 */
export const REVIEW_STATES: readonly ReviewState[] = ['new', 'justified', 'confirmed', 'all']

/** The five justifications, in the order the picker offers them. */
export const REVIEW_REASONS: readonly SaleReviewReason[] = [
  'walk_in',
  'telegram',
  'visit',
  'contract',
  'other',
]

/**
 * How long an answer is considered fresh.
 *
 * Short on purpose: the verdict is recomputed per request and a call that
 * syncs during the meeting changes it. Long enough that switching between the
 * two sections does not re-run the aggregates twice.
 */
const STALE_MS = 30_000

/** The branch map changes when somebody edits it, not on its own. */
const BRANCHES_STALE_MS = 5 * 60_000

/**
 * A generated query object as `client.ts` wants it.
 *
 * The spread is what makes this safe: every value is a string, number,
 * boolean, array of strings, null or undefined, and `buildUrl` drops the empty
 * ones and repeats the arrays. No cast, so a filter of an unsupported type
 * fails to compile here rather than on the wire.
 */
function toQuery(params: ComplianceScope | ComplianceQuery | TimelineQuery): Query {
  return { ...params }
}

/**
 * One cursor page of the queue.
 *
 * ⚠️ CURSOR-PAGED, ordered by `(occurred_on, id)`, and there is NO `sort`
 * parameter. Three of the source's four sort orders were deliberately not
 * ported: a sort a keyset cursor cannot express silently loses rows, and this
 * is the one list in the product where a lost row is a sale nobody checked.
 *
 * `keepPreviousData` so paging does not blank the table — the rows on screen
 * stay put while the next page is in flight, which is what makes the buttons
 * feel like controls rather than reloads.
 */
export function useCompliance(params: ComplianceQuery): UseQueryResult<ComplianceList> {
  return useQuery({
    queryKey: queryKey('sales', 'compliance', params),
    queryFn: () => api.get<ComplianceList>('/sales/compliance', toQuery(params)),
    placeholderData: keepPreviousData,
    staleTime: STALE_MS,
  })
}

/**
 * The three class counts and the per-employee cut.
 *
 * Asked with the SCOPE — period, employee, branch, search, section — and never
 * with the list's own narrowing filters, which the type makes impossible. The
 * cards are buttons, and a button that erases its own basis is not one.
 */
export function useComplianceSummary(
  params: ComplianceScope,
): UseQueryResult<ComplianceSummary> {
  return useQuery({
    queryKey: queryKey('sales', 'summary', params),
    queryFn: () => api.get<ComplianceSummary>('/sales/compliance/summary', toQuery(params)),
    staleTime: STALE_MS,
  })
}

/**
 * The customer chains — conversations and sales on ONE axis.
 *
 * ⚠️ The events come back as one type told apart by `kind`, ALREADY ORDERED,
 * and on a single day the call precedes the sale (SAP gives a sale no clock).
 * Nothing here re-sorts them: doing so would put the sale first and quietly
 * contradict the rule the verdict was computed with.
 *
 * `enabled` so the chart is not fetched until somebody asks for it — it is the
 * most expensive read in the module.
 */
export function useSaleTimeline(
  params: TimelineQuery,
  enabled: boolean,
): UseQueryResult<ComplianceTimeline> {
  return useQuery({
    queryKey: queryKey('sales', 'timeline', params),
    queryFn: () => api.get<ComplianceTimeline>('/sales/compliance/timeline', toQuery(params)),
    enabled,
    staleTime: STALE_MS,
  })
}

/** The branch → employee map, busiest branch first. */
export function useSaleBranches(enabled = true): UseQueryResult<SaleBranchList> {
  return useQuery({
    queryKey: queryKey('sales', 'branches'),
    queryFn: () => api.get<SaleBranchList>('/sales/branches'),
    enabled,
    staleTime: BRANCHES_STALE_MS,
  })
}

/**
 * Everything in sales control goes stale at once.
 *
 * A decision changes the list (the default filter shows only undecided sales,
 * so a decided row must leave it immediately) AND the counts above it. An
 * exclusion moves whole histories between sections. There is no narrower
 * invalidation that is honest.
 */
function useInvalidateSales(): () => void {
  const client = useQueryClient()
  return () => {
    void client.invalidateQueries({ queryKey: moduleKey('sales') })
  }
}

export interface ReviewInput {
  saleId: string
  status: SaleReviewStatus
  reason?: SaleReviewReason | null
  note?: string | null
}

/**
 * Record a decision.
 *
 * ⚠️ `reason` IS REFUSED WITH `confirmed` — a 422 whose `detail.field` is
 * `"reason"`, not a silently dropped field. The source dropped it, so a
 * manager could pick "Kelib oldi" beside "really suspicious" and watch it
 * vanish. The modal therefore sends `reason` only with `justified`, and the
 * server is the backstop rather than the only guard.
 */
export function useReviewSale(): UseMutationResult<SaleReview, Error, ReviewInput> {
  const invalidate = useInvalidateSales()
  return useMutation({
    mutationFn: ({ saleId, ...body }: ReviewInput) =>
      api.post<SaleReview>(`/sales/${saleId}/review`, body),
    onSuccess: invalidate,
  })
}

/**
 * Link a branch to an employee, or unlink it.
 *
 * ⚠️ A FIELD THAT IS NOT SENT IS NOT TOUCHED, and `agent_id: null` is a full
 * value meaning "unlink" — different from omitting it. That is why this
 * mutation sends `agent_id` and nothing else.
 *
 * ⚠️ The branch name is part of the path and arrives in Cyrillic, with spaces
 * and full stops ("Кукон метан булими"). Without `encodeURIComponent` the URL
 * is malformed.
 */
export function useAssignBranch(): UseMutationResult<
  SaleBranch,
  Error,
  { branch: string; agentId: string | null }
> {
  const invalidate = useInvalidateSales()
  return useMutation({
    mutationFn: ({ branch, agentId }) =>
      api.put<SaleBranch>(`/sales/branches/${encodeURIComponent(branch)}`, {
        agent_id: agentId,
      }),
    onSuccess: invalidate,
  })
}

/**
 * Take a branch out of sales control, or put it back.
 *
 * ⚠️ A SEPARATE MUTATION from `useAssignBranch`, although the path is the
 * same. Both controls are on screen at once, and with one shared pending state
 * excluding a branch would also disable its employee picker — the reader could
 * not tell which action was in flight. Two mutations, two states.
 *
 * ⚠️ `agent_id` is deliberately NOT sent. The field is optional and its absence
 * means "leave alone"; sending it would wash out an employee the manager set by
 * hand, and putting the branch back would leave it empty.
 */
export function useExcludeBranch(): UseMutationResult<
  SaleBranch,
  Error,
  { branch: string; excluded: boolean }
> {
  const invalidate = useInvalidateSales()
  return useMutation({
    mutationFn: ({ branch, excluded }) =>
      api.put<SaleBranch>(`/sales/branches/${encodeURIComponent(branch)}`, { excluded }),
    onSuccess: invalidate,
  })
}

/**
 * Take a CUSTOMER out of sales control, or put them back.
 *
 * ⚠️ A DIFFERENT AXIS from the branch, though both are called "out of scope".
 * A branch is the SELLER's side ("Логистика" works here but sells nothing a
 * call could precede); a customer is the BUYER's side. Excluding a customer
 * reaches the walk-in section as well; excluding a branch does not.
 *
 * ⚠️ The code is part of the path and its `К` is CYRILLIC (`К02154`). Without
 * `encodeURIComponent` the URL is malformed — and a Latin `K` is a 404, which
 * is the server refusing to quietly answer "done" for a customer that does not
 * exist.
 *
 * Invalidates `clients` too: the same customer's card carries this history, and
 * leaving one of the two stale puts contradictory numbers on two screens.
 */
export function useExcludePartner(): UseMutationResult<
  PartnerExclusion,
  Error,
  { code: string; excluded: boolean }
> {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ code, excluded }) =>
      api.put<PartnerExclusion>(`/sales/partners/${encodeURIComponent(code)}/exclusion`, {
        excluded,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: moduleKey('sales') })
      void client.invalidateQueries({ queryKey: moduleKey('clients') })
    },
  })
}

/**
 * Step one of the upload: say what the file WOULD do. Nothing is written.
 *
 * ⚠️ A MUTATION, not a query, and never cached. Picking the same file twice can
 * legitimately give a different answer — if a real import happened in between,
 * `new_rows` drops to zero — and a cached estimate would then promise work
 * that has already been done.
 *
 * ⚠️ It deliberately does NOT invalidate. Nothing changed, and refetching the
 * table would tell the reader it had, before a single row was written.
 */
export function usePreviewSalesImport(): UseMutationResult<ImportPreview, Error, File> {
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      // `Content-Type` is deliberately not set: the browser owns the multipart
      // boundary (`shared/api/client.ts`).
      return api.postForm<ImportPreview>('/sales/import/preview', form)
    },
  })
}

/**
 * Step two: actually write the file.
 *
 * The kind (register / catalogue / balance) is decided by the server from the
 * HEADER, never from the name and never from a picker on screen — a picker
 * would only ever be a source of error.
 *
 * ⚠️ It is handed the SAME in-memory `File` the estimate read, so what was
 * shown is what gets written.
 */
export function useImportSales(): UseMutationResult<ImportReport, Error, File> {
  const invalidate = useInvalidateSales()
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.postForm<ImportReport>('/sales/import', form)
    },
    onSuccess: invalidate,
  })
}

/**
 * Assemble the daily message now, and show it.
 *
 * ⚠️ NOTHING IS EVER SENT FROM THIS DEPLOYMENT. The only transport
 * implementation writes a log line, so the answer always comes back
 * `sent: false` with `reason: "send_failed"` and
 * `error: "no_transport_configured"`. That is deliberate and is not a fault for
 * the panel to route around — `text` is what the button exists for.
 *
 * No invalidation: the run is recorded with `kind='test'` and changes nothing
 * the panel shows.
 */
export function useDigestTest(): UseMutationResult<DigestTest, Error, void> {
  return useMutation({
    mutationFn: () => api.post<DigestTest>('/sales/digest/test'),
  })
}
