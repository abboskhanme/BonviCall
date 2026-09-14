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
import { useAlerts } from '@/modules/alerts/api'
import { ALERT_SEVERITY_LABEL, ALERT_SEVERITY_TONE } from '@/modules/alerts/routing'
import { t } from '@/shared/i18n'
import { formatInstantTitle } from '@/shared/lib/format'
import { relativeText } from '@/shared/lib/relativeText'
import { Badge } from '@/shared/ui/primitives'
import { Section } from '@/shared/ui/detail'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

/** A card is a summary. Somebody reading further is looking for a pattern,
 *  and a pattern shows in twenty rows. */
const HISTORY_LIMIT = 20

export function AlertHistorySection({ agentId }: { agentId: string }) {
  const query = useAlerts({ agent_id: agentId, open_only: false, limit: HISTORY_LIMIT })

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
        {(data) => (
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
                {data.items.map((alert) => (
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
        )}
      </QueryBoundary>
    </Section>
  )
}
