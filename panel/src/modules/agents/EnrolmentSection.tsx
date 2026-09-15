/**
 * How far through enrolment one agent is, and if they are stuck, at which step.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * This is the useful half of what `/enrolment` used to be. R17 — a
 * non-technical salesperson failing to complete a 15-minute unaided install —
 * is the project's top practical risk, and the failure mode that makes it
 * expensive is **silence**: the person gets stuck at a permission screen, says
 * nothing, and an admin finds out a week later from a device-silence alert.
 *
 * So this section is built to be read by somebody who is *not* on the phone
 * with them. It always answers three questions, in this order:
 *
 *   1. where are they now      — the stage chip and the progress bar
 *   2. what should happen next — `FUNNEL_STAGE_HINT`, an instruction, not a noun
 *   3. what went wrong         — the last failed attempt, with its timestamp
 *
 * The receiver banner sits above all of it because if the callback receiver is
 * down, nobody can enrol at all and every other answer on the page is a
 * distraction (SPEC §5.2). Absence of enrolment must be an event, not a stall.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useState } from 'react'
import { AlertTriangle, Copy, KeyRound, Check, ShieldQuestion } from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import {
  ENROLMENT_ATTEMPT_KIND_LABEL,
  ENROLMENT_OUTCOME_LABEL,
  FUNNEL_PATH,
  FUNNEL_STAGE_HINT,
  FUNNEL_STAGE_LABEL,
  FUNNEL_STAGE_TONE,
  isStuckStage,
} from '@/modules/devices/labels'
import { useDevice, type Installation } from '@/modules/devices/api'
import {
  CAPABILITY_BLOCKING_ORDER,
  CAPABILITY_LABEL,
  CAPABILITY_STATE_LABEL,
} from '@/modules/devices/labels'
import { Perm } from '@/shared/auth/permissions'
import { messageForError } from '@/shared/api/errors'
import { t } from '@/shared/i18n'
import { formatDateTime, formatInstantTitle } from '@/shared/lib/format'
import { relativeText } from '@/shared/lib/relativeText'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { Section } from '@/shared/ui/detail'

import { AttestModal } from './AttestModal'
import { attestStance, stanceReasonKey } from './attestation'
import { installUrl } from '@/modules/numbers/installUrl'
import {
  isCodeLive,
  useEnrolmentAttempts,
  useEnrolmentCodes,
  useIssueEnrolmentCode,
  useReceiverStatus,
  useRevokeEnrolmentCode,
  type EnrolmentCode,
  type RegisteredNumber,
} from '@/modules/numbers/api'

function ReceiverBanner() {
  const can = useAuth((state) => state.can)
  const query = useReceiverStatus(can(Perm.ENROLMENT_READ))
  const status = query.data
  // No banner while unknown: a scary line that turns out to be a loading state
  // is worse than a moment of nothing.
  if (!status || status.enrolment_possible) return null
  // …and none at all where the callback route is not part of this deployment.
  // It needs a receiver on a known line, which no deployment has ever had, so
  // this banner sat red for months over a rollout that was working — and a
  // banner that is always red is one nobody reads on the day it means
  // something (`enrolment.callback_enabled`).
  if (status.callback_enabled === false) return null
  return (
    <Card className="flex items-start gap-3 border-bad/40 bg-bad/5 p-3">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-bad" aria-hidden />
      <div>
        <p className="text-sm font-medium text-text">{t('enrol.receiverDown')}</p>
        <p className="mt-0.5 text-xs text-muted">{t('enrol.receiverDownHint')}</p>
      </div>
    </Card>
  )
}

/** The journey as a bar. Stages off the path carry no position by design. */
function StageProgress({ stage }: { stage: Installation['funnel_stage'] }) {
  const index = FUNNEL_PATH.indexOf(stage)
  // `verified_by_admin` is real progress but is not on the nominal path; it
  // sits where `number_verified` does, because that is what it substitutes for.
  const position = stage === 'verified_by_admin' ? FUNNEL_PATH.indexOf('number_verified') : index
  // ...and it is drawn differently there. A proven binding is a fact the
  // system established; an attested one is a person's word. Filling the same
  // cell the same way would quietly erase the difference (SPEC §9.3).
  const attestedAt = stage === 'verified_by_admin' ? FUNNEL_PATH.indexOf('number_verified') : -1

  return (
    <ol className="flex flex-wrap items-center gap-1" aria-label={t('enrol.progress')}>
      {FUNNEL_PATH.map((step, stepIndex) => {
        const done = position >= 0 && stepIndex <= position
        const attested = stepIndex === attestedAt
        return (
          <li key={step} className="flex items-center gap-1">
            <span
              title={attested ? t('attest.stepAttested') : undefined}
              className={
                attested
                  ? 'rounded-sm border border-dashed border-warn bg-warn/10 px-2 py-0.5 text-2xs font-medium text-warn'
                  : done
                    ? 'rounded-sm bg-accent-soft px-2 py-0.5 text-2xs font-medium text-accent'
                    : 'rounded-sm bg-surface-2 px-2 py-0.5 text-2xs text-muted'
              }
            >
              {attested ? t('funnel.verified_by_admin') : t(FUNNEL_STAGE_LABEL[step])}
            </span>
            {stepIndex < FUNNEL_PATH.length - 1 ? (
              <span className="text-2xs text-muted" aria-hidden>
                ›
              </span>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}

function CodeRow({ code, mayWrite }: { code: EnrolmentCode; mayWrite: boolean }) {
  const revoke = useRevokeEnrolmentCode()
  const [copied, setCopied] = useState(false)
  const live = isCodeLive(code)


  async function copy() {
    try {
      await navigator.clipboard.writeText(t('enrol.smsTemplate', { url: installUrl(code.code) }))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard access is refused on an insecure origin and in some
      // browsers without a user gesture. The code is on screen either way, so
      // this fails quietly rather than with an alarming dialog.
      setCopied(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-border p-3">
      <span className="font-mono text-base font-semibold tracking-widest text-text">
        {code.code}
      </span>
      {live ? (
        <Badge tone="good">{t('enrol.codeLive')}</Badge>
      ) : code.redeemed_at ? (
        <Badge tone="neutral">{t('enrol.codeRedeemed')}</Badge>
      ) : code.revoked_at ? (
        <Badge tone="neutral">{t('enrol.codeRevoked')}</Badge>
      ) : (
        <Badge tone="warn">{t('enrol.codeExpired')}</Badge>
      )}
      <span className="text-xs text-muted" title={formatInstantTitle(code.expires_at)}>
        {t('enrol.codeExpires', { at: formatDateTime(code.expires_at) })}
      </span>
      {code.attempt_count > 0 ? (
        <span className="text-xs text-muted">
          {t('enrol.codeAttempts', { n: code.attempt_count })}
        </span>
      ) : null}
      {live ? (
        <div className="ms-auto flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => void copy()}>
            {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
            {copied ? t('enrol.copied') : t('enrol.copyLink')}
          </Button>
          {mayWrite ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => revoke.mutate(code.id)}
              disabled={revoke.status === 'pending'}
            >
              {t('enrol.revokeCode')}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

export function EnrolmentSection({
  number,
  installation,
  agentName,
  olderInstallations = 0,
}: {
  number: RegisteredNumber | null
  installation: Installation | null
  /** Named in the attestation dialog: the admin is asserting something about
   *  a person, not about a row. */
  agentName: string
  /** How many earlier attempts exist. A rollout retries, and twenty silent
   *  installations behind one agent is worth saying out loud. */
  olderInstallations?: number
}) {
  const can = useAuth((state) => state.can)
  const mayWrite = can(Perm.ENROLMENT_WRITE)
  const mayAttest = can(Perm.ENROLMENT_ATTEST)
  const [attesting, setAttesting] = useState(false)

  const codesQuery = useEnrolmentCodes(number?.id)
  const attemptsQuery = useEnrolmentAttempts(number?.id)
  const receiverQuery = useReceiverStatus(can(Perm.ENROLMENT_READ))
  // The capability states, which now arrive BEFORE verification — this is the
  // data R17 needs and the funnel could not previously show.
  const deviceQuery = useDevice(
    can(Perm.DEVICES_READ) || can(Perm.DEVICES_READ_OWN) ? installation?.id : undefined,
  )
  const issue = useIssueEnrolmentCode(number?.id ?? '')

  const codes = [...(codesQuery.data?.items ?? [])].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  )
  const liveCode = codes.find((code) => isCodeLive(code)) ?? null
  /** The one code this card shows. See the block that renders it. */
  const shownCode = liveCode ?? codes[0] ?? null

  const attempts = [...(attemptsQuery.data?.items ?? [])].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  )
  const lastFailure = attempts.find((attempt) => attempt.outcome !== 'ok') ?? null

  // Without a number there is nothing to enrol against: a code is issued for a
  // LINE, not for a person, because the line is what the phone proves it holds.
  if (!number) {
    return (
      <Section title={t('enrol.title')} description={t('enrol.subtitle')}>
        <p className="text-sm text-muted">{t('enrol.needsNumber')}</p>
      </Section>
    )
  }

  const stage = installation?.funnel_stage ?? 'invited'
  const stuck = isStuckStage(stage)
  // Whether the escape hatch is open, and why. Computed rather than assumed:
  // offering it first every time would turn every binding into the weaker kind.
  /**
   * The capabilities standing in the way, worst first.
   *
   * `not_applicable` is excluded: the handset does not have the feature, which
   * is nobody's problem and would bury the ones that are.
   */
  const blocking = (deviceQuery.data?.capabilities ?? [])
    .filter((c) => c.state !== 'granted_working' && c.state !== 'not_applicable')
    .sort((a, b) => CAPABILITY_BLOCKING_ORDER[a.state] - CAPABILITY_BLOCKING_ORDER[b.state])

  const stance = attestStance({
    stage,
    verifiedAt: installation?.verified_at ?? null,
    attempts,
    receiver: receiverQuery.data,
  })

  return (
    <div className="space-y-3">
      <ReceiverBanner />

      <Section
        title={t('enrol.title')}
        description={t('enrol.subtitle')}
        actions={
          mayWrite ? (
            <Button
              size="sm"
              onClick={() => issue.mutate()}
              disabled={issue.status === 'pending'}
            >
              <KeyRound className="size-4" aria-hidden />
              {liveCode ? t('enrol.reissue') : t('enrol.issue')}
            </Button>
          ) : undefined
        }
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Badge tone={FUNNEL_STAGE_TONE[stage]}>{t(FUNNEL_STAGE_LABEL[stage])}</Badge>
            {installation ? (
              <span
                className="text-xs text-muted"
                title={formatInstantTitle(installation.funnel_changed_at)}
              >
                {t('enrol.since', { when: relativeText(installation.funnel_changed_at) })}
              </span>
            ) : null}
          </div>

          <StageProgress stage={stage} />

          {/* The instruction, not the noun. The stage NAME tells an admin
              nothing they can act on; `FUNNEL_STAGE_HINT` says what to do
              next. §14 keeps the wording itself in uz.json. */}
          <p className={stuck ? 'text-sm font-medium text-warn' : 'text-sm text-text'}>
            {t(FUNNEL_STAGE_HINT[stage])}
          </p>

          {/* ═══════════════════════════════════════════════════════════════
              WHICH capability is blocking, by name.

              This is what R17 needs and what the funnel could not say until
              the telemetry gate opened: a phone reports its capabilities
              before it verifies, so while somebody is stuck at a permission
              screen the panel now knows exactly which screen. "Ruxsatlar
              berilmagan" sends an admin to look; "Mikrofon — butunlay rad
              etilgan" tells them what to do when they get there.
              ═══════════════════════════════════════════════════════════════ */}
          {blocking.length > 0 ? (
            <div className="space-y-1 rounded-md border border-warn/40 bg-warn/5 p-3">
              <p className="text-xs font-medium text-text">{t('enrol.blockingTitle')}</p>
              <ul className="space-y-0.5">
                {blocking.map((capability) => (
                  <li key={capability.capability} className="text-sm text-text">
                    {t(CAPABILITY_LABEL[capability.capability])}
                    {' — '}
                    <span className="text-warn">
                      {t(CAPABILITY_STATE_LABEL[capability.state])}
                    </span>
                    {capability.detail ? (
                      /* The device's own words — English, because it is the
                         OEM's diagnostic string and not a sentence anybody
                         wrote for a reader. Muted and parenthesised so it
                         reads as evidence rather than as instruction. */
                      <span className="ms-1 text-2xs text-muted">
                        {'('}
                        {capability.detail}
                        {')'}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {olderInstallations > 0 ? (
            /* A rollout retries. Showing only the newest attempt is right, but
               silently discarding nineteen others is not. */
            <p className="text-2xs text-muted">
              {t('enrol.olderAttempts', { n: olderInstallations })}
            </p>
          ) : null}

          {issue.error ? (
            <p className="text-xs text-bad">{messageForError(issue.error)}</p>
          ) : null}

          {/* The escape hatch, open only when the automatic routes cannot
              finish — and saying which one failed, so it never reads as a
              shortcut somebody took because it was quicker. */}
          {installation && stance.kind === 'offered' ? (
            <div className="space-y-2 rounded-md border border-warn/40 bg-warn/5 p-3">
              <p className="text-sm font-medium text-text">{t('attest.offerTitle')}</p>
              <p className="text-xs text-muted">{t(stanceReasonKey(stance))}</p>
              {mayAttest ? (
                <Button variant="secondary" size="sm" onClick={() => setAttesting(true)}>
                  <ShieldQuestion className="size-3.5" aria-hidden />
                  {t('attest.action')}
                </Button>
              ) : (
                <p className="text-xs text-muted">{t('attest.needsAdmin')}</p>
              )}
            </div>
          ) : null}

          {installation?.attest_reason ? (
            /* An attested binding carries its reason wherever it shows: six
               months on, "why is this installation trusted" must have an
               answer that is not "somebody clicked". */
            <p className="text-xs text-warn">
              {t('attest.attestedBecause', { reason: installation.attest_reason })}
            </p>
          ) : null}

          {/* ONE code, not three.
              ═══════════════════════════════════════════════════════════════
              Reissuing is normal — an agent mistypes, a code expires over a
              weekend — so the list grew and the three most recent were shown.
              Only one of them is ever read aloud to anybody, and the other two
              are noise on a card an admin opens to answer one question: what
              do I give this person right now.

              LIVE first, newest second. The two are the same code in every
              ordinary case, because issuing a new one is what makes it the
              live one; they differ only if the newest has already been
              redeemed or has expired, and there a code that still works is
              strictly more useful than a more recent one that does not.
              The rest are counted, so the churn stays visible. */}
          {shownCode ? (
            <div className="space-y-2">
              <CodeRow code={shownCode} mayWrite={mayWrite} />
              {codes.length > 1 ? (
                <p className="text-2xs text-muted">
                  {t('enrol.olderCodes', { n: codes.length - 1 })}
                </p>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-muted">{t('enrol.noCodes')}</p>
          )}

          {/* The last failure, with its timestamp. This is the answer to
              "they say it does not work" and it is why the attempts endpoint
              exists (UC-01). */}
          {lastFailure ? (
            <div className="rounded-md border border-warn/40 bg-warn/5 p-3">
              <p className="text-xs font-medium text-text">{t('enrol.lastFailure')}</p>
              <p className="mt-1 text-sm text-text">
                {t(ENROLMENT_OUTCOME_LABEL[lastFailure.outcome])}
              </p>
              <p className="mt-1 text-2xs text-muted">
                {t(ENROLMENT_ATTEMPT_KIND_LABEL[lastFailure.kind])}
                {' · '}
                <span title={formatInstantTitle(lastFailure.created_at)}>
                  {formatDateTime(lastFailure.created_at)}
                </span>
                {lastFailure.device_model ? ` · ${lastFailure.device_model}` : ''}
              </p>
            </div>
          ) : null}
        </div>
      </Section>

      {mayAttest && installation ? (
        <AttestModal
          open={attesting}
          onOpenChange={setAttesting}
          installationId={installation.id}
          agentName={agentName}
          e164={number.e164}
          reasonHintKey={
            stance.kind === 'offered' ? stanceReasonKey(stance) : 'attest.becauseBoth'
          }
        />
      ) : null}
    </div>
  )
}
