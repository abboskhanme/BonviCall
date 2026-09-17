/**
 * The leaderboard (SPEC-ANALYTICS phase 2; BonviZvonki's `AgentTable`).
 *
 * Ported with three columns removed rather than faked: the customer's own CSAT
 * rating, the AI-against-customer divergence and the avatar. The first two read
 * survey tables this product does not have (§1.4), and the third needs an
 * avatar component the panel has never had — the agent's stored `color` is a
 * hex literal, which a page here may not render (CONVENTIONS-CLIENT.md §11).
 *
 * What is kept is the part that earns the table: the rank, the average with a
 * bar behind it, the volume it was measured on, the breaches and the movement
 * since the previous period. Sorting is the SERVER's — one order, the one the
 * rank numbers were computed in, so the column a reader sorts by cannot
 * contradict the "#1" beside it. Their client-side sort could.
 */
import { ArrowDown, ArrowUp, Minus } from 'lucide-react'

import { BAND_TONE } from '@/modules/analysis/labels'
import { t } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { EM_DASH, formatCount, formatDuration } from '@/shared/lib/format'
import { Badge } from '@/shared/ui/primitives'
import { ProgressBar } from '@/shared/ui/ProgressBar'
import { Table, TableWrap, TBody, TD, TH, THead, TR } from '@/shared/ui/table'

import type { AgentRankRow } from './api'
import { bandOf, toNumber } from './chart'

/**
 * Places gained since the previous window.
 *
 * `null` is not zero: an agent who scored nothing last period has no place to
 * have gained, and drawing them as "unchanged" would say they held a rank they
 * never had.
 */
function RankDelta({ delta }: { delta: number | null }) {
  if (delta === null) {
    return <span className="text-2xs text-muted">{EM_DASH}</span>
  }
  if (delta === 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-2xs text-muted">
        <Minus className="size-3" aria-hidden />
        {t('analytics.rankSame')}
      </span>
    )
  }
  const up = delta > 0
  return (
    <span
      className={cn(
        'inline-flex items-center gap-0.5 text-2xs font-medium',
        up ? 'text-good' : 'text-bad',
      )}
      title={t(up ? 'analytics.rankUp' : 'analytics.rankDown', {
        n: String(Math.abs(delta)),
      })}
    >
      {up ? (
        <ArrowUp className="size-3" aria-hidden />
      ) : (
        <ArrowDown className="size-3" aria-hidden />
      )}
      <span className="tabular-nums">{Math.abs(delta)}</span>
    </span>
  )
}

function ScoreCell({ row }: { row: AgentRankRow }) {
  const score = toNumber(row.ai_score)
  if (score === null) return <span className="text-muted">{EM_DASH}</span>
  const tone = BAND_TONE[bandOf(score)]
  return (
    <span className="flex items-center justify-end gap-2">
      <span className="font-mono text-sm font-semibold tabular-nums text-text">
        {row.ai_score}
      </span>
      {/* The bar is the shape of the answer; the number beside it is the
          answer. A score is already out of 100, so the fraction is exact. */}
      <span className="hidden w-20 sm:block">
        <ProgressBar fraction={score / 100} tone={tone} label={t('analytics.colScore')} />
      </span>
    </span>
  )
}

export function AgentRankingTable({ rows }: { rows: readonly AgentRankRow[] }) {
  return (
    <TableWrap>
      <Table>
        <THead>
          <tr>
            <TH className="w-12">{t('analytics.colRank')}</TH>
            <TH>{t('analytics.colAgent')}</TH>
            <TH className="text-end">{t('analytics.colCalls')}</TH>
            <TH className="text-end">{t('analytics.colScore')}</TH>
            <TH className="text-end">{t('analytics.colFlags')}</TH>
            <TH className="text-end">{t('analytics.colDuration')}</TH>
            <TH className="text-end">{t('analytics.colTrend')}</TH>
          </tr>
        </THead>
        <TBody>
          {rows.map((row) => (
            <TR key={row.agent_id}>
              <TD className="font-mono text-2xs text-muted">
                {String(row.rank).padStart(2, '0')}
              </TD>
              <TD className="whitespace-nowrap font-medium">{row.agent_name}</TD>
              <TD className="text-end font-mono tabular-nums text-muted">
                {formatCount(row.calls)}
              </TD>
              <TD className="text-end">
                <ScoreCell row={row} />
              </TD>
              <TD className="text-end">
                {row.red_flags > 0 ? (
                  <Badge tone="bad">{formatCount(row.red_flags)}</Badge>
                ) : (
                  <span className="text-muted">0</span>
                )}
              </TD>
              <TD className="text-end font-mono tabular-nums text-muted">
                {formatDuration(row.avg_duration_sec)}
              </TD>
              <TD className="text-end">
                <RankDelta delta={row.rank_delta} />
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </TableWrap>
  )
}
