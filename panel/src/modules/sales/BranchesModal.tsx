/**
 * The branch → employee map.
 *
 * WHY THIS SCREEN EXISTS. SAP does not carry the salesperson's name — only
 * `Подразделение`. A sale is tied to an employee through exactly this map, so
 * if the map is wrong the whole report names the wrong person. It is therefore
 * not a hidden setting: the manager sees it and fixes it in one click.
 *
 * ⚠️ AUTOMATIC MATCHING IS BY EXACT EQUALITY, never fuzzy: attributing a sale
 * to the wrong employee is worse than leaving it unattributed. That is also
 * why unlinked branches stay in the list — otherwise there would be nowhere to
 * find and link them.
 *
 * ⚠️ AN EMPLOYEE SET BY HAND SURVIVES EVERY LATER IMPORT
 * (`matched_automatically = false`). That is what the badge in this table is
 * for: the manager can see which row is their decision and which is the
 * machine's guess.
 *
 * ⚠️ OUT OF SCOPE IS A THIRD STATE. Some departments ("Маркетинг булими",
 * "Логистика") work here but are not part of sales control. Leaving them
 * unlinked is not enough — their sales would stay in the list and be counted
 * suspicious every time. Excluding moves them to the out-of-scope section.
 *
 * ⚠️ NOTHING IS DELETED — a change from the source, where excluding a branch
 * dropped its sales from the database and putting it back restored them only
 * on the next import. Here the sales are separated by the QUERY, so putting a
 * branch back returns its whole history at once. The confirmation says so,
 * because "will I lose the history?" is the actual fear.
 *
 * ⚠️ THE CONFIRMATION IS NOT `window.confirm` and not a second dialog: a
 * browser prompt steals focus inside a modal and cannot be translated, and a
 * modal inside a modal loses the row being talked about. It takes over the row.
 */
import { useMemo, useState } from 'react'
import { Eye, EyeOff, Link2Off, TriangleAlert, UserCheck, Wand2 } from 'lucide-react'

import { useAgentDirectory } from '@/modules/agents/api'
import { useAuth } from '@/modules/auth/store'
import { messageForError } from '@/shared/api/errors'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { EM_DASH, formatCount } from '@/shared/lib/format'
import { SELECT_CLASS } from '@/shared/ui/filters'
import { Badge, Button } from '@/shared/ui/primitives'
import { Modal } from '@/shared/ui/Modal'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { useAssignBranch, useExcludeBranch, useSaleBranches, type SaleBranch } from './api'

function MatchBadge({ assigned, automatic }: { assigned: boolean; automatic: boolean }) {
  if (!assigned) {
    return (
      <span className="inline-flex" title={t('sales.branches.noneHint')}>
        <Badge tone="warn" className="whitespace-nowrap">
          <Link2Off className="me-1 size-3" aria-hidden />
          {t('sales.branches.none')}
        </Badge>
      </span>
    )
  }
  if (automatic) {
    return (
      <span className="inline-flex" title={t('sales.branches.autoHint')}>
        <Badge tone="neutral" className="whitespace-nowrap">
          <Wand2 className="me-1 size-3" aria-hidden />
          {t('sales.branches.auto')}
        </Badge>
      </span>
    )
  }
  return (
    <span className="inline-flex" title={t('sales.branches.manualHint')}>
      <Badge tone="accent" className="whitespace-nowrap">
        <UserCheck className="me-1 size-3" aria-hidden />
        {t('sales.branches.manual')}
      </Badge>
    </span>
  )
}

export function BranchesModal({
  open,
  onOpenChange,
  canEdit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** `settings:write`. Without it the map opens read-only. */
  canEdit: boolean
}) {
  const can = useAuth((state) => state.can)
  const branches = useSaleBranches(open)
  /* Archived employees are included: a historic sale can belong to one, and a
     picker missing that name would silently blank the value. */
  const agents = useAgentDirectory(open && can(Perm.AGENTS_READ))
  const assign = useAssignBranch()
  const exclude = useExcludeBranch()

  const [error, setError] = useState<string | null>(null)
  /** The branch awaiting confirmation — one at a time. */
  const [confirming, setConfirming] = useState<string | null>(null)

  const options = useMemo(
    () =>
      [...(agents.data?.items ?? [])].sort((a, b) =>
        a.full_name.localeCompare(b.full_name, 'ru'),
      ),
    [agents.data],
  )

  function change(branch: string, agentId: string) {
    setError(null)
    assign.mutate(
      { branch, agentId: agentId || null },
      { onError: (failure) => setError(messageForError(failure)) },
    )
  }

  /* The confirmation closes whatever the request does: a row frozen in the
     confirming state leaves the manager unable to tell whether it happened.
     The failure gets its own line. */
  function setExcluded(branch: string, next: boolean) {
    setError(null)
    setConfirming(null)
    exclude.mutate(
      { branch, excluded: next },
      { onError: (failure) => setError(messageForError(failure)) },
    )
  }

  /**
   * Unlinked first — those need work — then the busiest.
   *
   * Alphabetical is useless here: this is a list of things to do. Excluded
   * branches always sit LAST; they are a settled matter and at the top they
   * would hide the rows that still need attention. They are never dropped from
   * the list, because this is the only place they can be put back.
   */
  function sortRows(rows: SaleBranch[]): SaleBranch[] {
    return [...rows].sort((a, b) => {
      if (a.excluded !== b.excluded) return a.excluded ? 1 : -1
      const aLinked = a.agent_id ? 1 : 0
      const bLinked = b.agent_id ? 1 : 0
      if (aLinked !== bLinked) return aLinked - bLinked
      return b.sales - a.sales || a.branch.localeCompare(b.branch, 'ru')
    })
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => {
        if (next) {
          onOpenChange(true)
          return
        }
        // A half-pressed "exclude" waiting on reopen would be dangerous.
        setConfirming(null)
        setError(null)
        onOpenChange(false)
      }}
      title={t('sales.branches.title')}
      description={t('sales.branches.hint')}
      className="w-[min(56rem,calc(100vw-2rem))]"
    >
      <div className="space-y-4">
        {error ? (
          <div className="flex items-start gap-3 rounded-md bg-bad/10 p-3" role="alert">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-bad" aria-hidden />
            <p className="min-w-0 text-2xs leading-relaxed text-bad">{error}</p>
          </div>
        ) : null}

        <QueryBoundary
          query={branches}
          isEmpty={(data) => data.items.length === 0}
          emptyTitle={t('sales.branches.empty')}
          emptyHint={t('sales.branches.emptyHint')}
          skeletonRows={6}
        >
          {(data) => {
            const rows = sortRows(data.items)
            /* Coverage counts only branches IN scope: an excluded one is not
               "unlinked", it is out of the reckoning. Otherwise the figure
               could never reach zero and the line would stay amber for ever,
               meaning nothing. */
            const supervised = rows.filter((row) => !row.excluded)
            const unassigned = supervised.filter((row) => !row.agent_id).length
            const excludedCount = rows.length - supervised.length

            return (
              <>
                {/* The coverage is stated: an incomplete map is the EXPECTED
                    state, not a fault, and without a number that difference is
                    invisible. */}
                <p
                  className={cn(
                    'rounded-md px-3 py-2 text-2xs leading-relaxed',
                    supervised.length === 0
                      ? 'bg-surface-2 text-muted'
                      : unassigned > 0
                        ? 'bg-warn/10 text-warn'
                        : 'bg-good/10 text-good',
                  )}
                >
                  {supervised.length > 0
                    ? unassigned > 0
                      ? t('sales.branches.unassigned', {
                          count: unassigned,
                          total: supervised.length,
                        })
                      : t('sales.branches.allAssigned', { count: supervised.length })
                    : null}
                  {/* Said HERE: the number above is no longer the whole list,
                      and unexplained that prompts "where did my branches go?" */}
                  {excludedCount > 0 ? (
                    <span className={cn(supervised.length > 0 && 'opacity-70')}>
                      {supervised.length > 0 ? ' · ' : ''}
                      {t('sales.branches.excludedCount', { count: excludedCount })}
                    </span>
                  ) : null}
                </p>

                <TableWrap>
                  <Table>
                    <THead>
                      <tr>
                        <TH>{t('sales.branches.branch')}</TH>
                        <TH className="text-end">{t('sales.col.sales')}</TH>
                        <TH>{t('sales.branches.match')}</TH>
                        <TH>{t('sales.col.agent')}</TH>
                        {/* No heading: the buttons carry their own words. */}
                        {canEdit ? <TH className="w-px" /> : null}
                      </tr>
                    </THead>
                    <TBody>
                      {rows.map((row) => {
                        const saving =
                          assign.status === 'pending' && assign.variables?.branch === row.branch
                        const excluding =
                          exclude.status === 'pending' && exclude.variables?.branch === row.branch

                        /* The confirmation TAKES THE WHOLE ROW. A small
                           yes/no would not fit the action column, and the
                           number of sales has to be visible — it is the price
                           of the action. */
                        if (confirming === row.branch) {
                          return (
                            <TR key={row.branch}>
                              <TD colSpan={canEdit ? 5 : 4}>
                                <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-bad/10 px-3 py-2">
                                  <p className="min-w-0 text-2xs leading-relaxed text-bad">
                                    {t('sales.branches.excludeConfirm', {
                                      branch: row.branch,
                                      count: row.sales,
                                    })}
                                  </p>
                                  <div className="flex shrink-0 items-center gap-2">
                                    <Button
                                      variant="secondary"
                                      size="sm"
                                      onClick={() => setConfirming(null)}
                                    >
                                      {t('common.cancel')}
                                    </Button>
                                    <Button
                                      variant="danger"
                                      size="sm"
                                      disabled={excluding}
                                      onClick={() => setExcluded(row.branch, true)}
                                    >
                                      {t('sales.branches.excludeYes')}
                                    </Button>
                                  </div>
                                </div>
                              </TD>
                            </TR>
                          )
                        }

                        return (
                          <TR
                            key={row.branch}
                            /* Faded: the row is still listed but is out of the
                               reckoning. */
                            className={cn(row.excluded && 'opacity-60')}
                          >
                            <TD className="font-medium">{row.branch}</TD>
                            <TD className="text-end tabular-nums text-muted">
                              {formatCount(row.sales)}
                            </TD>
                            <TD>
                              {/* "Matched" means nothing for an excluded
                                  branch: whether it has an employee changes
                                  nothing. So the badge changes instead. */}
                              {row.excluded ? (
                                <span
                                  className="inline-flex"
                                  title={t('sales.branches.excludedHint')}
                                >
                                  <Badge tone="bad" className="whitespace-nowrap">
                                    <EyeOff className="me-1 size-3" aria-hidden />
                                    {t('sales.branches.excluded')}
                                  </Badge>
                                </span>
                              ) : (
                                <MatchBadge
                                  assigned={Boolean(row.agent_id)}
                                  automatic={row.matched_automatically}
                                />
                              )}
                            </TD>
                            <TD>
                              {canEdit ? (
                                <select
                                  className={cn(SELECT_CLASS, 'min-w-[12rem]')}
                                  aria-label={t('sales.branches.agentOf', {
                                    branch: row.branch,
                                  })}
                                  disabled={saving || excluding || row.excluded}
                                  value={row.agent_id ?? ''}
                                  onChange={(event) => change(row.branch, event.target.value)}
                                >
                                  {/* An empty value is a full choice: some
                                      branches are deliberately left unlinked. */}
                                  <option value="">{t('sales.noAgent')}</option>
                                  {options.map((agent) => (
                                    <option key={agent.id} value={agent.id}>
                                      {agent.full_name}
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                <span className="text-sm">{row.agent_name ?? EM_DASH}</span>
                              )}
                            </TD>
                            {canEdit ? (
                              <TD className="text-end">
                                {row.excluded ? (
                                  // Putting a branch back is harmless — no
                                  // confirmation.
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    disabled={excluding}
                                    onClick={() => setExcluded(row.branch, false)}
                                  >
                                    <Eye className="size-3.5" aria-hidden />
                                    {t('sales.branches.include')}
                                  </Button>
                                ) : (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    disabled={excluding}
                                    title={t('sales.branches.excludeHint')}
                                    onClick={() => setConfirming(row.branch)}
                                  >
                                    <EyeOff className="size-3.5" aria-hidden />
                                    {t('sales.branches.exclude')}
                                  </Button>
                                )}
                              </TD>
                            ) : null}
                          </TR>
                        )
                      })}
                    </TBody>
                  </Table>
                </TableWrap>
              </>
            )
          }}
        </QueryBoundary>

        <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
          {t('sales.branches.manualNote')}
        </p>

        {/* What excluding actually does, stated before the button is pressed
            rather than after. */}
        {canEdit ? (
          <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
            {t('sales.branches.excludedNote')}
          </p>
        ) : null}
      </div>
    </Modal>
  )
}
