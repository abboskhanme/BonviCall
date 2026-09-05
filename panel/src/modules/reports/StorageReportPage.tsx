/**
 * `/reports/storage` — how much we have, and when we run out (N18).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * Two numbers that cannot come from the same place, which is why both are
 * rendered:
 *
 *   **Today's total** is counted from the audio rows. It has to be, because
 *   the nightly rollup does not exist until the job has run once — and the
 *   endpoint used to read only the rollup, so on a fresh deployment it
 *   reported "0 bytes" while 26 recordings sat on disk. A storage page that
 *   says zero when the disk is not empty is worse than no page.
 *
 *   **The growth curve** comes from the snapshots, because a rate needs
 *   history and a single count cannot supply one.
 *
 * The projection is shown against the provisioned disk rather than on its own:
 * "10 GB in twelve months" is a number, "4% of the disk" is an answer, and
 * "180% of the disk" is a decision somebody has to make this quarter.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { HardDrive, TrendingUp } from 'lucide-react'

import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { formatBytes, formatCount, formatDate } from '@/shared/lib/format'
import { Badge, Card } from '@/shared/ui/primitives'
import { ProgressBar } from '@/shared/ui/ProgressBar'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Section } from '@/shared/ui/detail'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import {
  STORAGE_PROVISION_BYTES,
  provisionFraction,
  useDataUsage,
  useStorageReport,
  type StorageReport,
} from './api'

function Headline({ report }: { report: StorageReport }) {
  const fraction = provisionFraction(report.projected_bytes_12m)
  const overProvision = report.projected_bytes_12m > STORAGE_PROVISION_BYTES
  const tone = overProvision ? 'bad' : fraction > 0.7 ? 'warn' : 'accent'

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Card className="p-4">
        <p className="flex items-center gap-2 text-2xs font-medium uppercase tracking-wide text-muted">
          <HardDrive className="size-4" aria-hidden />
          {t('storage.totalNow')}
        </p>
        <p className="mt-1 text-2xl font-semibold text-text">
          {formatBytes(report.audio_bytes_total)}
        </p>
        {/* Counted from the rows, not from a rollup that may not exist yet. */}
        <p className="mt-1 text-xs text-muted">
          {t('storage.fileCount', { n: formatCount(report.audio_files) })}
        </p>
      </Card>

      <Card className="p-4">
        <p className="flex items-center gap-2 text-2xs font-medium uppercase tracking-wide text-muted">
          <TrendingUp className="size-4" aria-hidden />
          {t('storage.growth30d')}
        </p>
        <p className="mt-1 text-2xl font-semibold text-text">
          {formatBytes(report.bytes_added_30d)}
        </p>
        <p className="mt-1 text-xs text-muted">{t('storage.growth30dHint')}</p>
      </Card>

      <Card className="p-4 sm:col-span-2">
        <p className="text-2xs font-medium uppercase tracking-wide text-muted">
          {t('storage.projection12m')}
        </p>
        <p className="mt-1 text-2xl font-semibold text-text">
          {formatBytes(report.projected_bytes_12m)}
        </p>
        <div className="mt-2 space-y-1">
          <ProgressBar fraction={fraction} tone={tone} label={t('storage.projection12m')} />
          <p className="text-xs text-muted">
            {t('storage.ofProvision', {
              percent: Math.round((report.projected_bytes_12m / STORAGE_PROVISION_BYTES) * 100),
              provision: formatBytes(STORAGE_PROVISION_BYTES),
            })}
          </p>
        </div>
        {overProvision ? (
          <p className="mt-2 text-xs text-bad">{t('storage.overProvision')}</p>
        ) : null}
        {/* The retention window is why the projection is not simply
            "growth × 12": recordings older than it are deleted, so the curve
            flattens once the first year rolls over. */}
        <p className="mt-2 text-xs text-muted">{t('storage.retentionNote')}</p>
      </Card>
    </div>
  )
}

export function StorageReportPage() {
  const storageQuery = useStorageReport()
  const usageQuery = useDataUsage()

  return (
    <Page>
      <PageHeader title={t('page.storageReport')} description={t('storage.subtitle')} />

      <QueryBoundary
        query={storageQuery}
        isEmpty={(report) => report.audio_files === 0 && report.audio_bytes_total === 0}
        emptyTitle={t('storage.emptyAll')}
        emptyHint={t('storage.emptyAllHint')}
        skeletonRows={4}
      >
        {(report) => (
          <div className="flex flex-col gap-4">
            <Headline report={report} />

            <Section title={t('storage.historyTitle')} description={t('storage.historySubtitle')}>
              {report.history.length === 0 ? (
                // A rate needs history; one day is not a trend and the page
                // should not draw one.
                <p className="text-sm text-muted">{t('storage.historyEmpty')}</p>
              ) : (
                <TableWrap>
                  <Table>
                    <THead>
                      <tr>
                        <TH>{t('storage.colDay')}</TH>
                        <TH className="text-end">{t('storage.colTotal')}</TH>
                        <TH className="text-end">{t('storage.colFiles')}</TH>
                        <TH className="text-end">{t('storage.colAdded')}</TH>
                        <TH className="text-end">{t('storage.colDeleted')}</TH>
                      </tr>
                    </THead>
                    <TBody>
                      {[...report.history]
                        .sort((a, b) => b.period_date.localeCompare(a.period_date))
                        .map((point) => (
                          <TR key={point.period_date}>
                            <TD className="whitespace-nowrap text-muted">
                              {formatDate(point.period_date)}
                            </TD>
                            <TD className="text-end font-mono tabular-nums">
                              {formatBytes(point.audio_bytes_total)}
                            </TD>
                            <TD className="text-end font-mono tabular-nums text-muted">
                              {formatCount(point.audio_files)}
                            </TD>
                            <TD className="text-end font-mono tabular-nums text-good">
                              {formatBytes(point.bytes_added)}
                            </TD>
                            <TD className="text-end font-mono tabular-nums text-muted">
                              {/* Retention removing old recordings is the
                                  system working, so this is not red. */}
                              {formatBytes(point.bytes_deleted)}
                            </TD>
                          </TR>
                        ))}
                    </TBody>
                  </Table>
                </TableWrap>
              )}
            </Section>

            <QueryBoundary
              query={usageQuery}
              isEmpty={(usage) => usage.items.length === 0}
              emptyTitle={t('storage.usageEmpty')}
              emptyHint={t('storage.usageEmptyHint')}
              skeletonRows={4}
            >
              {(usage) => (
                <Section
                  title={t('storage.usageTitle')}
                  description={t('storage.usageSubtitle', {
                    cap: formatBytes(usage.cap_bytes_month),
                  })}
                >
                  <TableWrap>
                    <Table>
                      <THead>
                        <tr>
                          <TH>{t('gap.agent')}</TH>
                          <TH className="text-end">{t('storage.colCellular')}</TH>
                          <TH className="text-end">{t('storage.colWifi')}</TH>
                          <TH className="text-end">{t('storage.colRequests')}</TH>
                          <TH>{t('storage.colCap')}</TH>
                        </tr>
                      </THead>
                      <TBody>
                        {[...usage.items]
                          .sort((a, b) => b.cellular_bytes_month - a.cellular_bytes_month)
                          .map((row) => (
                            <TR key={row.installation_id}>
                              <TD>{row.agent_name}</TD>
                              <TD className="text-end font-mono tabular-nums">
                                {formatBytes(row.cellular_bytes_month)}
                              </TD>
                              <TD className="text-end font-mono tabular-nums text-muted">
                                {formatBytes(row.wifi_bytes_month)}
                              </TD>
                              <TD className="text-end font-mono tabular-nums text-muted">
                                {formatCount(row.requests_month)}
                              </TD>
                              <TD className="w-40">
                                {/* Past the cap the app stops uploading audio
                                    over cellular (N14) — the employee is
                                    paying for this data. */}
                                {row.over_cap ? (
                                  <Badge tone="bad">{t('storage.overCap')}</Badge>
                                ) : (
                                  <ProgressBar
                                    fraction={
                                      row.cap_bytes_month > 0
                                        ? row.cellular_bytes_month / row.cap_bytes_month
                                        : 0
                                    }
                                    tone="accent"
                                    label={t('storage.colCap')}
                                  />
                                )}
                              </TD>
                            </TR>
                          ))}
                      </TBody>
                    </Table>
                  </TableWrap>
                </Section>
              )}
            </QueryBoundary>
          </div>
        )}
      </QueryBoundary>
    </Page>
  )
}
