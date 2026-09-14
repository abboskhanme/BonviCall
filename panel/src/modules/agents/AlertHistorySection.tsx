/**
 * Everything ever raised about one salesperson, on their own card.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Ogohlantirishlar is the **open** list since 2026-09-14 — an inbox that never
 * empties is an inbox nobody works — so the closed half had to keep a home,
 * and the home is the person it was about. "This phone was silent for three
 * days in August" is evidence about the rollout, not noise to be swept up: it
 * is the half of the history the open list drops, and the half somebody asks
 * about when a salesperson's numbers look wrong.
 *
 * Nothing is deleted anywhere to make this work. An alert is acknowledged or
 * resolved, never removed (SPEC §3.8), and this reads the same rows the inbox
 * stops showing.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'

import { useAlerts } from '@/modules/alerts/api'
import { ALERT_SEVERITY_LABEL, ALERT_SEVERITY_TONE } from '@/modules/alerts/routing'
import { t } from '@/shared/i18n'
import { formatCount, formatInstantTitle } from '@/shared/lib/format'
import { relativeText } from '@/shared/lib/relativeText'
import { Badge, Button } from '@/shared/ui/primitives'
import { Section } from '@/shared/ui/detail'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

/**
 * How many rows are asked for, and how many are shown at once.
 *
 * The history is paged **in the browser**, not by the server, and that is a
 * deliberate limit rather than a shortcut. `GET /alerts` takes `limit` and no
 * offset, and one salesperson's history is small by construction: alerts
 * dedupe, so a phone offline for a week is one row with a repeat count, not
 * five hundred. Fetching the lot once and turning ten at a time costs one
 * request and no contract change. If this list ever approaches `FETCH_LIMIT`
 * the endpoint needs an offset, and the count below is what will say so.
 */
const FETCH_LIMIT = 200
const PAGE_SIZE = 10

export function AlertHistorySection({ agentId }: { agentId: string }) {
  const query = useAlerts({ agent_id: agentId, open_only: false, limit: FETCH_LIMIT })
  const [page, setPage] = useState(0)

  // Opening a different agent must not land on page four of a history that is
  // now shorter than four pages.
  useEffect(() => setPage(0), [agentId])

  return (
    <Section
      title={t('agentDetail.alertsTitle')}
      description={t('agentDetail.alertsSubtitle')}
    >
      <QueryBoundary
        query={query}
        isEmpty={(data) => data.items.length === 0}
        // Nothing ever raised about this person is good news and reads as
        // such, rather than as the same grey box every empty list shows.
        emptyTitle={t('agentDetail.alertsEmpty')}
        emptyHint={t('agentDetail.alertsEmptyHint')}
        skeletonRows={3}
      >
        {(data) => {
          const pageCount = Math.max(1, Math.ceil(data.items.length / PAGE_SIZE))
          // A refetch can shorten the list under a reader who is on the last
          // page; clamping here keeps the table from going blank.
          const current = Math.min(page, pageCount - 1)
          const rows = data.items.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE)
          return (
          <>
          <TableWrap>
            <Table>
              <THead>
                <tr>
                  <TH>{t('agentDetail.alertsColWhen')}</TH>
                  <TH>{t('agentDetail.alertsColWhat')}</TH>
                  <TH>{t('agentDetail.alertsColSeverity')}</TH>
                  <TH>{t('agentDetail.alertsColState')}</TH>
                </tr>
              </THead>
              <TBody>
                {rows.map((alert) => (
                  <TR key={alert.id}>
                    <TD
                      className="whitespace-nowrap text-muted"
                      title={formatInstantTitle(alert.last_seen_at)}
                    >
                      {relativeText(alert.last_seen_at)}
                    </TD>
                    <TD>
                      <span className="block text-sm text-text">{alert.title_uz}</span>
                      {/* The repeat count, not a row per occurrence: a phone
                          offline for a week is one alert seen many times. */}
                      {alert.occurrence_count > 1 ? (
                        <span className="text-2xs text-muted">
                          {t('agentDetail.alertsRepeats', { n: alert.occurrence_count })}
                        </span>
                      ) : null}
                    </TD>
                    <TD className="whitespace-nowrap">
                      <Badge tone={ALERT_SEVERITY_TONE[alert.severity]}>
                        {t(ALERT_SEVERITY_LABEL[alert.severity])}
                      </Badge>
                    </TD>
                    <TD className="whitespace-nowrap">
                      {alert.resolved_at ? (
                        <Badge tone="good">{t('agentDetail.alertsResolved')}</Badge>
                      ) : alert.acknowledged_at ? (
                        <Badge tone="neutral">{t('agentDetail.alertsAcknowledged')}</Badge>
                      ) : (
                        <Badge tone="warn">{t('agentDetail.alertsOpen')}</Badge>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </TableWrap>

          {data.items.length > PAGE_SIZE ? (
            <div className="mt-3 flex items-center justify-between gap-3">
              <span className="text-xs text-muted">
                {t('agentDetail.alertsCount', { n: formatCount(data.items.length) })}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={current === 0}
                  onClick={() => setPage(current - 1)}
                >
                  <ChevronLeft className="size-4" aria-hidden />
                  {t('calls.prevPage')}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={current >= pageCount - 1}
                  onClick={() => setPage(current + 1)}
                >
                  {t('calls.nextPage')}
                  <ChevronRight className="size-4" aria-hidden />
                </Button>
              </div>
            </div>
          ) : null}
          </>
          )
        }}
      </QueryBoundary>
    </Section>
  )
}
