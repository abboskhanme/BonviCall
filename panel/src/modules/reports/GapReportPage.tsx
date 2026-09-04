/**
 * `/reports/gap` — the product's own smoke alarm (UC-23).
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * "Which calls have no recording, and whose fault is it." Three cuts of the
 * same number: by reason, by handset model against the M0 baseline, and by
 * agent.
 *
 * **A retention-expired recording is NOT a gap.** It existed; the 12-month
 * job removed it; nobody did anything wrong. The server already knows this —
 * `GapByReasonOut.counts_against_capture_rate` is false for `pending_upload`
 * and `not_expected`, and an expired recording never had a missing reason at
 * all, so it is not in this report's numerator. The page renders that
 * distinction rather than flattening it, because the whole purpose of the
 * report is to decide whether a handset or a person has a problem, and a
 * number that includes normal retention points at the wrong one.
 *
 * Nothing is recomputed here. Every percentage is the string the server sent,
 * displayed as sent — re-rounding a NUMERIC on the way to the screen is how a
 * report ends up disagreeing with the list it is supposed to reconcile with.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { Link, useSearchParams } from 'react-router-dom'
import { TrendingDown } from 'lucide-react'

import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { EM_DASH, formatCount } from '@/shared/lib/format'
import { Badge, Card } from '@/shared/ui/primitives'
import { FilterField, SELECT_CLASS } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'
import { Section } from '@/shared/ui/detail'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import { AUDIO_MISSING_REASON_LABEL } from '@/modules/calls/labels'
import { percentValue, useGapReport, type GapReport } from './api'

const PARAM_FROM = 'date_from'
const PARAM_TO = 'date_to'

/** A percentage as the server wrote it, never re-rounded. */
function Percent({ value }: { value: string | null | undefined }) {
  if (value === null || value === undefined) return <>{EM_DASH}</>
  return <>{value}%</>
}

function Headline({ report }: { report: GapReport }) {
  const rate = percentValue(report.capture_rate)
  const tone = rate === null ? 'neutral' : rate >= 90 ? 'good' : rate >= 70 ? 'warn' : 'bad'
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Card className="p-4">
        <p className="text-2xs font-medium uppercase tracking-wide text-muted">
          {t('gap.captureRate')}
        </p>
        <p className="mt-1 text-2xl font-semibold text-text">
          <Percent value={report.capture_rate} />
        </p>
        <Badge tone={tone}>{t('gap.ofAnswered')}</Badge>
      </Card>
      <Card className="p-4">
        <p className="text-2xs font-medium uppercase tracking-wide text-muted">
          {t('gap.answeredCalls')}
        </p>
        <p className="mt-1 text-2xl font-semibold text-text">
          {formatCount(report.answered_calls)}
        </p>
      </Card>
      <Card className="p-4">
        <p className="text-2xs font-medium uppercase tracking-wide text-muted">
          {t('gap.withAudio')}
        </p>
        <p className="mt-1 text-2xl font-semibold text-good">
          {formatCount(report.calls_with_audio)}
        </p>
      </Card>
      <Card className="p-4">
        <p className="text-2xs font-medium uppercase tracking-wide text-muted">
          {t('gap.missingTotal')}
        </p>
        <p className="mt-1 text-2xl font-semibold text-bad">
          {formatCount(report.missing_total)}
        </p>
        {/* UC-22: this number must equal the filtered call list, because the
            same filter builder produces both. The link is the proof. */}
        <Link
          to="/calls?has_audio=false"
          className="text-xs text-accent underline-offset-2 hover:underline"
        >
          {t('gap.openCalls')}
        </Link>
      </Card>
    </div>
  )
}

export function GapReportPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const dateFrom = searchParams.get(PARAM_FROM) ?? undefined
  const dateTo = searchParams.get(PARAM_TO) ?? undefined

  const reportQuery = useGapReport({
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
  })

  function applyFilter(key: string, value: string | null) {
    const next = new URLSearchParams(searchParams)
    if (value === null || value === '') next.delete(key)
    else next.set(key, value)
    setSearchParams(next, { replace: true })
  }

  return (
    <Page>
      <PageHeader title={t('page.gapReport')} description={t('gap.subtitle')} />

      <Card className="flex flex-wrap items-end gap-3 p-3">
        <FilterField label={t('calls.filterDateFrom')}>
          <input
            type="date"
            className={SELECT_CLASS}
            value={dateFrom ?? ''}
            max={dateTo}
            onChange={(event) => applyFilter(PARAM_FROM, event.target.value || null)}
          />
        </FilterField>
        <FilterField label={t('calls.filterDateTo')}>
          <input
            type="date"
            className={SELECT_CLASS}
            value={dateTo ?? ''}
            min={dateFrom}
            onChange={(event) => applyFilter(PARAM_TO, event.target.value || null)}
          />
        </FilterField>
      </Card>

      <QueryBoundary
        query={reportQuery}
        isEmpty={(report) => report.answered_calls === 0 && report.missing_total === 0}
        emptyTitle={t('gap.emptyAll')}
        emptyHint={t('gap.emptyAllHint')}
        skeletonRows={5}
      >
        {(report) => (
          <div className="flex flex-col gap-4">
            <Headline report={report} />

            <Section title={t('gap.byReasonTitle')} description={t('gap.byReasonSubtitle')}>
              <TableWrap>
                <Table>
                  <THead>
                    <tr>
                      <TH>{t('gap.reason')}</TH>
                      <TH className="text-end">{t('gap.calls')}</TH>
                      <TH>{t('gap.countsAgainst')}</TH>
                    </tr>
                  </THead>
                  <TBody>
                    {report.by_reason.map((row) => (
                      <TR key={row.reason}>
                        <TD>{t(AUDIO_MISSING_REASON_LABEL[row.reason])}</TD>
                        <TD className="text-end font-mono tabular-nums">
                          {formatCount(row.calls)}
                        </TD>
                        <TD>
                          {/* `pending_upload` and `not_expected` are excluded
                              from the denominator on purpose — neither is a
                              capture failure, and counting them would make a
                              healthy fleet look broken for the ninety seconds
                              between a call ending and its audio arriving. */}
                          {row.counts_against_capture_rate ? (
                            <Badge tone="bad">{t('gap.isGap')}</Badge>
                          ) : (
                            <Badge tone="neutral">{t('gap.notAGap')}</Badge>
                          )}
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </TableWrap>
            </Section>

            <Section title={t('gap.byModelTitle')} description={t('gap.byModelSubtitle')}>
              <TableWrap>
                <Table>
                  <THead>
                    <tr>
                      <TH>{t('gap.model')}</TH>
                      <TH>{t('gap.variant')}</TH>
                      <TH className="text-end">{t('gap.answered')}</TH>
                      <TH className="text-end">{t('gap.rate')}</TH>
                      <TH className="text-end">{t('gap.baseline')}</TH>
                      <TH className="text-end">{t('gap.delta')}</TH>
                    </tr>
                  </THead>
                  <TBody>
                    {report.by_model.map((row) => (
                      <TR key={`${row.manufacturer}-${row.model}-${row.app_variant}`}>
                        <TD>
                          <span className="text-text">{`${row.manufacturer} ${row.model}`}</span>
                          {row.regression ? (
                            <Badge tone="bad" className="ms-2">
                              <TrendingDown className="me-1 size-3" aria-hidden />
                              {t('gap.regression')}
                            </Badge>
                          ) : null}
                        </TD>
                        <TD className="text-xs text-muted">
                          {row.app_variant} · API {row.api_level}
                        </TD>
                        <TD className="text-end font-mono tabular-nums">
                          {formatCount(row.answered_calls)}
                        </TD>
                        <TD className="text-end font-mono tabular-nums">
                          <Percent value={row.capture_rate} />
                        </TD>
                        <TD className="text-end font-mono tabular-nums text-muted">
                          {/* Blank until T14 measures this model. An absent
                              baseline is not a passing one. */}
                          <Percent value={row.baseline_rate} />
                        </TD>
                        <TD className="text-end font-mono tabular-nums">
                          {row.delta_pp === null || row.delta_pp === undefined ? (
                            EM_DASH
                          ) : (
                            <span className={row.regression ? 'text-bad' : 'text-muted'}>
                              {row.delta_pp}
                            </span>
                          )}
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </TableWrap>
            </Section>

            <Section title={t('gap.byAgentTitle')}>
              <TableWrap>
                <Table>
                  <THead>
                    <tr>
                      <TH>{t('gap.agent')}</TH>
                      <TH className="text-end">{t('gap.answered')}</TH>
                      <TH className="text-end">{t('gap.withAudioShort')}</TH>
                      <TH className="text-end">{t('gap.rate')}</TH>
                    </tr>
                  </THead>
                  <TBody>
                    {report.by_agent.map((row) => (
                      <TR key={row.agent_id}>
                        <TD>
                          <Link
                            to={`/agents/${row.agent_id}`}
                            className="text-text underline-offset-2 hover:text-accent hover:underline"
                          >
                            {row.agent_name}
                          </Link>
                        </TD>
                        <TD className="text-end font-mono tabular-nums">
                          {formatCount(row.answered_calls)}
                        </TD>
                        <TD className="text-end font-mono tabular-nums">
                          {formatCount(row.calls_with_audio)}
                        </TD>
                        <TD className="text-end font-mono tabular-nums">
                          <Percent value={row.capture_rate} />
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </TableWrap>
            </Section>

            {report.open_deltas.length > 0 ? (
              <Section title={t('gap.deltasTitle')} description={t('gap.deltasSubtitle')}>
                <TableWrap>
                  <Table>
                    <THead>
                      <tr>
                        <TH>{t('gap.agent')}</TH>
                        <TH>{t('gap.day')}</TH>
                        <TH className="text-end">{t('gap.deviceCounted')}</TH>
                        <TH className="text-end">{t('gap.uploaded')}</TH>
                        <TH className="text-end">{t('gap.missing')}</TH>
                      </tr>
                    </THead>
                    <TBody>
                      {report.open_deltas.map((row) => (
                        <TR key={`${row.installation_id}-${row.period_date}`}>
                          <TD>{row.agent_name}</TD>
                          <TD className="whitespace-nowrap text-muted">{row.period_date}</TD>
                          <TD className="text-end font-mono tabular-nums">
                            {formatCount(row.device_counted)}
                          </TD>
                          <TD className="text-end font-mono tabular-nums">
                            {formatCount(row.uploaded_count)}
                          </TD>
                          <TD className="text-end font-mono tabular-nums text-bad">
                            {formatCount(row.delta)}
                          </TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </TableWrap>
              </Section>
            ) : null}
          </div>
        )}
      </QueryBoundary>
    </Page>
  )
}
