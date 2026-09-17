/**
 * One employee's unreached customers — THE DIALOG THAT PROVES THE NUMBER.
 *
 * Ported from BonviZvonki `web/src/modules/activity/MissedClientsModal.tsx`.
 *
 * WHY IT EXISTS. A row reading "15 missed, 100 % called back" looks wrong, and
 * the first question is "really?". It is right: the 15 events came from 9
 * different customers, some of whom tried two or three times, and every one of
 * them was spoken to. Without showing that, nobody believes the figure.
 *
 * So each customer is listed separately: how many times they tried, when the
 * last attempt was, and WHO spoke to them afterwards and HOW LONG after. The
 * sum of the attempts equals the "missed" column and the number of rows equals
 * the "customers" column — and the line at the foot says so out loud, because
 * that equality is the whole argument.
 *
 * Unreached customers sort first: the list is a work list.
 */
import { CheckCircle2, PhoneIncoming, PhoneOutgoing, XCircle } from 'lucide-react'

import { EM_DASH, formatDateTime, formatPhone } from '@/shared/lib/format'
import { cn } from '@/shared/lib/cn'
import { Badge } from '@/shared/ui/primitives'
import { Modal } from '@/shared/ui/Modal'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { useMissedClients, type ActivityQuery } from './api'
import { t } from '@/shared/i18n'

export function MissedClientsModal({
  agentId,
  agentName,
  query,
  onClose,
}: {
  /** `null` closes the dialog and stops the request. */
  agentId: string | null
  agentName: string
  /** ⚠️ THE SAME WINDOW THE REPORT WAS ASKED WITH. If the two drift, the
   *  detail contradicts the total and the tool built to make a figure
   *  believable is what makes it doubtful. */
  query: ActivityQuery
  onClose: () => void
}) {
  const report = useMissedClients(agentId, query)

  return (
    <Modal
      open={Boolean(agentId)}
      onOpenChange={(open) => !open && onClose()}
      title={agentName}
      description={t('activity.drillHint', {
        hours: report.data?.callback_window_hours ?? 24,
      })}
      className="max-w-4xl"
    >
      <QueryBoundary
        query={report}
        isEmpty={(data) => data.clients.length === 0}
        emptyTitle={t('activity.noMissed')}
        skeletonRows={6}
      >
        {(data) => {
          const attempts = data.clients.reduce((sum, row) => sum + row.attempts, 0)
          return (
            <>
              <TableWrap>
                <Table>
                  <THead>
                    <tr>
                      <TH>{t('activity.drillClient')}</TH>
                      <TH className="text-end">{t('activity.drillAttempts')}</TH>
                      <TH>{t('activity.drillLastMissed')}</TH>
                      <TH>{t('activity.drillContact')}</TH>
                    </tr>
                  </THead>
                  <TBody>
                    {data.clients.map((row) => {
                      const reached = row.contacted_at !== null
                      return (
                        <TR key={row.phone_key}>
                          <TD>
                            <div className="flex items-center gap-2">
                              {reached ? (
                                <CheckCircle2 className="size-4 shrink-0 text-good" aria-hidden />
                              ) : (
                                <XCircle className="size-4 shrink-0 text-bad" aria-hidden />
                              )}
                              <div className="min-w-0">
                                <div className="truncate font-mono tabular-nums">
                                  {formatPhone(row.phone_key) ?? EM_DASH}
                                </div>
                                {/* The handset's own contact name. Decoration,
                                    never identity — there is no customer
                                    catalogue behind it (L3). */}
                                {row.contact_name ? (
                                  <div className="truncate text-2xs text-muted">
                                    {row.contact_name}
                                  </div>
                                ) : null}
                              </div>
                            </div>
                          </TD>
                          <TD
                            className={cn(
                              'text-end tabular-nums',
                              row.attempts > 1 && 'font-semibold',
                            )}
                          >
                            {row.attempts}
                          </TD>
                          <TD className="whitespace-nowrap tabular-nums text-muted">
                            {formatDateTime(row.last_missed_at)}
                          </TD>
                          <TD>
                            {!reached ? (
                              <Badge tone="bad">{t('activity.drillNotReached')}</Badge>
                            ) : (
                              <div className="flex flex-wrap items-center gap-1.5">
                                {/* Direction matters: the customer trying again
                                    and somebody calling them back are two
                                    different things. */}
                                {row.contact_inbound ? (
                                  <PhoneIncoming
                                    className="size-3.5 shrink-0 text-accent"
                                    aria-hidden
                                  />
                                ) : (
                                  <PhoneOutgoing
                                    className="size-3.5 shrink-0 text-good"
                                    aria-hidden
                                  />
                                )}
                                <span className="text-2xs tabular-nums">
                                  {t('activity.drillAfter', {
                                    minutes: row.minutes_to_contact ?? 0,
                                  })}
                                </span>
                                {row.contacted_by ? (
                                  <span className="text-2xs text-muted">
                                    · {row.contacted_by}
                                  </span>
                                ) : null}
                              </div>
                            )}
                          </TD>
                        </TR>
                      )
                    })}
                  </TBody>
                </Table>
              </TableWrap>

              {/* ⚠️ THE EQUALITY IS STATED. This dialog exists to make a number
                  believable, so its relationship to the table is spelled out:
                  rows = "customers", sum of attempts = "missed". */}
              <p className="rounded-md bg-surface-2 px-3 py-2 text-2xs leading-relaxed text-muted">
                {t('activity.drillTotals', {
                  clients: data.clients.length,
                  attempts,
                  unreached: data.unreached,
                })}
              </p>
            </>
          )
        }}
      </QueryBoundary>
    </Modal>
  )
}
