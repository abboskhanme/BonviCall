/**
 * Which work number is this agent's — and which ones used to be.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **The mapping is time-boxed, and the history is not decoration.**
 *
 * An assignment is a half-open period `[valid_from, valid_to)`. When a line
 * moves from one salesperson to another, the calls made before the handover
 * still belong to the previous holder (SPEC §3.3, D-08) — attribution uses
 * `started_at`, so a call from before the change does not follow the number.
 *
 * A page that showed only "current holder: Aziz" would therefore be lying by
 * omission on exactly the day somebody asks why last month's calls are filed
 * under a different name. So the timeline is the primary rendering here and
 * the current holder is just its first row.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Phone, Plus, Scissors } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { formatDate, formatInstantTitle, formatPhone } from '@/shared/lib/format'
import { Badge, Button } from '@/shared/ui/primitives'
import { Section } from '@/shared/ui/detail'

import { AssignNumberModal } from './AssignNumberModal'
import { CloseAssignmentModal } from './CloseAssignmentModal'
import { isOpen, type AgentAssignment } from '@/modules/numbers/api'
import type { Agent } from './api'

export function NumberSection({
  agent,
  rows,
  loadFailed,
}: {
  agent: Agent
  rows: AgentAssignment[]
  loadFailed: boolean
}) {
  const can = useAuth((state) => state.can)
  const mayWrite = can(Perm.NUMBERS_WRITE)
  const [assigning, setAssigning] = useState(false)
  const [closing, setClosing] = useState<AgentAssignment | null>(null)

  const open = rows.filter((row) => isOpen(row.assignment))
  const past = rows.filter((row) => !isOpen(row.assignment))

  return (
    <Section
      title={t('numbers.title')}
      description={t('numbers.subtitle')}
      actions={
        mayWrite ? (
          <Button size="sm" variant="secondary" onClick={() => setAssigning(true)}>
            <Plus className="size-4" aria-hidden />
            {t('numbers.assign')}
          </Button>
        ) : undefined
      }
    >
      <div className="space-y-4">
        {loadFailed ? (
          <p className="text-xs text-bad">{t('numbers.historyPartial')}</p>
        ) : null}

        {open.length === 0 ? (
          <p className="text-sm text-muted">{t('numbers.noneOpen')}</p>
        ) : (
          <div className="space-y-2">
            {open.map(({ assignment, number }) => (
              <div
                key={assignment.id}
                className="flex flex-wrap items-center gap-3 rounded-md border border-border p-3"
              >
                <Phone className="size-4 shrink-0 text-muted" aria-hidden />
                <span className="font-mono text-base font-semibold text-text">
                  {formatPhone(number.e164) ?? number.e164}
                </span>
                <Badge tone="good">{t('numbers.holdsNow')}</Badge>
                {number.operator ? (
                  <span className="text-xs text-muted">{number.operator}</span>
                ) : null}
                <span
                  className="text-xs text-muted"
                  title={formatInstantTitle(assignment.valid_from)}
                >
                  {t('numbers.since', { date: formatDate(assignment.valid_from) })}
                </span>
                {mayWrite ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ms-auto"
                    onClick={() => setClosing({ assignment, number })}
                  >
                    <Scissors className="size-3.5" aria-hidden />
                    {t('numbers.close')}
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
        )}

        {past.length > 0 ? (
          <div>
            <p className="mb-2 text-2xs font-semibold uppercase tracking-wide text-muted">
              {t('numbers.historyTitle')}
            </p>
            {/* Why this list is here at all: calls from these periods are still
                attributed to this agent, and nowhere else in the panel says so. */}
            <p className="mb-2 text-xs text-muted">{t('numbers.historyHint')}</p>
            <ol className="space-y-1">
              {past.map(({ assignment, number }) => (
                <li
                  key={assignment.id}
                  className="flex flex-wrap items-center gap-2 border-s-2 border-border ps-3 text-sm"
                >
                  <span className="font-mono text-text">
                    {formatPhone(number.e164) ?? number.e164}
                  </span>
                  <span className="text-xs text-muted">
                    {t('numbers.period', {
                      from: formatDate(assignment.valid_from),
                      to: assignment.valid_to ? formatDate(assignment.valid_to) : '',
                    })}
                  </span>
                  {assignment.note ? (
                    <span className="text-xs text-muted">· {assignment.note}</span>
                  ) : null}
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        <Link
          to={`/calls?agent_id=${agent.id}`}
          className="inline-block text-xs text-accent underline-offset-2 hover:underline"
        >
          {t('numbers.viewCalls')}
        </Link>
      </div>

      {mayWrite ? (
        <>
          <AssignNumberModal open={assigning} onOpenChange={setAssigning} agent={agent} />
          <CloseAssignmentModal
            open={closing !== null}
            onOpenChange={(value) => !value && setClosing(null)}
            row={closing}
          />
        </>
      ) : null}
    </Section>
  )
}
